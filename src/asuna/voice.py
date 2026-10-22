"""Voice messages arrive as text (ADR-093): a channel adapter that declares `voice_in` fetches each voice when its line
arrives and posts the audio (or why the platform did not give it); the program keeps the bytes (BlobStore kind `audio`)
only until it has turned them into text on this machine, whatever came of it, and her line shows the words.

- `receive` is the channel endpoint `POST /v1/channels/<id>/voice`: one voice segment of one stored line. The container
  is recognized by its first bytes (RIFF/WAVE, ID3 or an MPEG audio frame header) before anything else is read.
- `Service` is the background worker in the Host's process: one voice at a time, in arrival order. It decodes with av,
  resamples to 16 kHz mono PCM16 and hands the model float samples; SenseVoice int8 with Silero voice detection through
  sherpa-onnx, loaded when a voice comes and released after IDLE_SECONDS without one. The model files are checked
  against their pins (MODEL_FILES) once at start; missing or different, a voice reads 「没转出文字：识别模型不在」.
- A line's voices live on its message row as `voice`, one entry per voice segment in order (ENTRY_FIELDS). `line_text`
  is the line as she reads it: each voice placeholder replaced, in order, by its state's words (`words`); the stored
  text stays as it arrived.
- `await_turn` holds a turn up to WAIT_SECONDS in all while a voice in its lines is still being transcribed;
  `holds_projection` keeps such a line out of her conversation until its voice is settled or WAIT_SECONDS passed, and
  the worker projects it then (`attach`). A line that entered her conversation while still being transcribed is
  projected once more when its words are ready (`FOLLOW_UP`), since a line in the conversation is never rewritten.
"""
from __future__ import annotations

import hashlib
import io
import logging
import threading
import time
import traceback
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from queue import Empty, Queue

from .config import DATA
from .state import now

log = logging.getLogger(__name__)

KIND = 'audio'                        # BlobStore kind of voice bytes; never `image`
SOURCE = 'voice:'                     # source id prefix of stored voice bytes (media_life.POLICY)
CAPABILITY = 'voice_in'               # what an adapter declares when it posts voices (capabilities.py)
VOICE_TYPES = ('record', 'audio')     # media item types that are a voice
PLACEHOLDER = '[语音（未解析）]'        # what the adapter writes in the line for a voice segment
FOLLOW_UP = '#voice'                  # a line's second projection, once its words are ready

PENDING, TRANSCRIBED, NO_VOICE, NO_WORDS, FAILED, NOT_FETCHED = (
    'pending', 'transcribed', 'no_voice', 'no_words', 'failed', 'not_fetched')
FINAL = (TRANSCRIBED, NO_VOICE, NO_WORDS, FAILED, NOT_FETCHED)
# One entry per voice segment of a line, on its message row (`voice`); nothing else of the audio is kept:
ENTRY_FIELDS = {
    'index': 'its place among the line\'s voices (0 first)',
    'state': 'pending, transcribed, no_voice, no_words, failed or not_fetched',
    'seconds': 'length of the audio', 'text': 'the words, as the model wrote them',
    'events': 'its event labels other than speech', 'reason': 'why it failed or was not fetched, in words',
    'sha256': 'of the bytes as they came', 'size': 'bytes', 'head': 'the first 44 bytes, hex',
    'media_type': 'what the adapter declared', 'model': 'MODEL_ID',
    'arrived_at': 'when the bytes or the refusal came', 'finished_at': 'when it settled',
    'artifact_id': 'the stored bytes, while it is pending', 'audio_removed_at': 'when the bytes were deleted',
    'shown_pending': 'the line entered her conversation while still being transcribed',
}

WAIT_SECONDS = 10                     # a turn, and a line entering her conversation, wait this long in all (V6)
EXPECT_SECONDS = 120                  # a voice the adapter has not posted this long after its line is not coming
TURN_LOOKBACK_SECONDS = 600           # the lines a turn looks at for a voice still being transcribed
IDLE_SECONDS = 600                    # the model is released after this long with no voice
HEAD_BYTES = 44
# The HTTP server's bound on one voice's bytes (RUNTIME_API.md): far above any voice message; not a length limit.
BODY_LIMIT = 64 * 1024 * 1024

MODEL_ID = 'sensevoice-2024-07-17'
# The pins of DSH's own SenseVoice package (ADR-093 §4): name -> (bytes, sha256).
MODEL_FILES = {
    'model.int8.onnx': (239_233_841, 'c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51'),
    'tokens.txt': (315_894, 'f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc'),
    'silero_vad.onnx': (1_807_522, 'a35ebf52fd3ce5f1469b2a36158dba761bc47b973ea3382b3186ca15b1f5af28'),
}
RATE = 16000
THREADS = 4
# Silero voice detection (ADR-093 V4): speech and silence each at least 0.25 s, one piece at most 20 s.
VAD = {'min_speech_duration': 0.25, 'min_silence_duration': 0.25, 'max_speech_duration': 20}
VAD_BUFFER_SECONDS = 120              # what the detector holds before a piece is taken out; pieces leave as they end
ENGINE = {'engine': 'sherpa-onnx 1.13.8', 'model': MODEL_ID + ' int8', 'language': 'auto', 'itn': True,
          'rate': RATE, 'pcm': 's16 mono', 'vad': 'silero %(min_speech_duration)s/%(min_silence_duration)s/'
          '%(max_speech_duration)s s' % VAD}

MODEL_MISSING = '识别模型不在'
UNKNOWN_CONTAINER = '不是认得的音频格式（按开头的字节看不是 WAV 或 MP3）'
# A label the model gives a piece of audio other than speech, as her line names it.
EVENT_WORDS = {'BGM': '背景音乐', 'Laughter': '笑声', 'Applause': '掌声', 'Cry': '哭声', 'Sneeze': '打喷嚏',
               'Breath': '呼吸声', 'Cough': '咳嗽声', 'Sing': '唱歌', 'Speech_Noise': '嘈杂声', 'GBG': '杂音',
               'Event_UNK': '认不出的声音'}
OTHER_SOUND = '别的声音'
# Why the adapter got no audio, as her line says it (`receive`): the adapter sends one of these reasons.
REFUSAL_WORDS = {'gone': '平台上已经没有这条语音了', 'refused': '平台没给出音频', 'timeout': '向平台取音频超时了',
                 'unreachable': '连不上平台', 'no_audio': '平台的回话里没有音频'}

_lock = threading.RLock()             # every write of a row's `voice` goes through it
_settled = threading.Condition()      # notified whenever a voice settles
SERVICE = None                        # the running Service, when the Host has one
_project = None                       # the worker's projection of a line into her conversation (attach)


class VoiceError(Exception):
    """A voice that cannot be transcribed, with the reason in words."""


def attach(project):
    """`project(row_id, released)`: puts a line into her conversation once its voices settle (`released`: the wait
    ran out first)."""
    global _project
    _project = project


# ---- reading ------------------------------------------------------------------------------------------------------
def media_items(row):
    raw = ((row or {}).get('event') or {}).get('raw') or {}
    block = raw.get('asuna_media') if isinstance(raw, dict) else None
    items = (block or {}).get('items') if isinstance(block, dict) else None
    return [item for item in items or () if isinstance(item, dict)]


def voice_count(row):
    """How many voice segments the line carries, by its media block (entries never outnumber them)."""
    counted = sum(1 for item in media_items(row) if item.get('type') in VOICE_TYPES)
    return max(counted, len(entries_of(row)))


def entries_of(row):
    return [entry for entry in ((row or {}).get('voice') or ()) if isinstance(entry, dict)]


def _channel_of(row):
    return (((row or {}).get('event') or {}).get('channel') or {}).get('id') or (row or {}).get('adapter_id')


def _age_seconds(stamp, moment=None):
    try:
        then = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
    except ValueError:
        return None
    then = then if then.tzinfo else then.replace(tzinfo=timezone.utc)
    return ((moment or datetime.now(timezone.utc)) - then).total_seconds()


def expected(store, row, moment=None):
    """A voice of this line is still on its way from the adapter: the channel declares voice_in, the line carries a
    voice without an entry yet, and it arrived under EXPECT_SECONDS ago."""
    if store is None or entries_of(row) or not any(item.get('type') in VOICE_TYPES for item in media_items(row)):
        return False
    from . import capabilities
    if CAPABILITY not in capabilities.supports(store, _channel_of(row)):
        return False
    age = _age_seconds(row.get('received_at'), moment)
    return age is not None and age < EXPECT_SECONDS


def unsettled(store, row, moment=None):
    """A voice of this line is still being fetched or transcribed."""
    entries = entries_of(row)
    if entries:
        return any(entry.get('state') == PENDING for entry in entries)
    return expected(store, row, moment)


def _seconds(entry):
    value = entry.get('seconds')
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return ''
    return ' %d 秒' % max(1, int(value + 0.5))


def _heard(entry):
    names = [EVENT_WORDS.get(label, OTHER_SOUND) for label in entry.get('events') or ()]
    return '，听着像' + '、'.join(dict.fromkeys(names)) if names else ''


def words(entry):
    """One voice as her line shows it (ADR-093 V5); never empty."""
    state = (entry or {}).get('state')
    length = _seconds(entry or {})
    if state == TRANSCRIBED:
        return '[语音%s%s] %s' % (length, _heard(entry), ' '.join(str(entry.get('text') or '').split()))
    if state == NO_VOICE:
        return '[语音%s，里面没有人声]' % length
    if state == NO_WORDS:
        heard = _heard(entry)
        return ('[语音%s%s，听不出说的什么]' % (length, heard) if heard
                else '[语音%s，有人在说话，但听不出说的什么]' % length)
    if state == FAILED:
        return '[语音%s，没转出文字：%s]' % (length, entry.get('reason') or '原因没记下')
    if state == NOT_FETCHED:
        return '[语音，没拿到：%s]' % (entry.get('reason') or '原因没记下')
    return '[语音%s，正在转写，转完字会补在这一行]' % length


def line_text(row, store=None, moment=None):
    """The line's text as she reads it: each voice placeholder, in order, replaced by its voice's words. A line with no
    entries reads as it arrived, unless `store` shows its voices are still on their way (`expected`)."""
    text = str((row or {}).get('text') or '')
    entries = sorted(entries_of(row), key=lambda entry: entry.get('index') or 0)
    if entries:
        said = [words(entry) for entry in entries]
    elif expected(store, row, moment):
        said = [words({'state': PENDING})] * voice_count(row)
    else:
        return text
    pieces = text.split(PLACEHOLDER)
    out = [pieces[0]]
    for index, piece in enumerate(pieces[1:]):
        out.append(said[index] if index < len(said) else PLACEHOLDER)
        out.append(piece)
    extra = said[len(pieces) - 1:]
    return ''.join(out) + (' ' + ' '.join(extra) if extra else '')


def search_text(row):
    """The words of a line's voices, for a history search."""
    return ' '.join(str(entry.get('text') or '') for entry in entries_of(row) if entry.get('text'))


# ---- the container and the samples -------------------------------------------------------------------------------
def sniff(data):
    """The container by its first bytes, before any field is read: 'audio/wav', 'audio/mpeg' or None."""
    if len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WAVE':
        return 'audio/wav'
    if data[:3] == b'ID3':
        return 'audio/mpeg'
    if len(data) >= 4 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0:
        version, layer = (data[1] >> 3) & 3, (data[1] >> 1) & 3
        bitrate, rate = data[2] >> 4, (data[2] >> 2) & 3
        if version != 1 and layer != 0 and bitrate != 15 and rate != 3:   # an MPEG audio frame header
            return 'audio/mpeg'
    return None


AV_FORMATS = {'audio/wav': 'wav', 'audio/mpeg': 'mp3'}


def _av_words(exc):
    return ' '.join(str(exc).split())[:80] or type(exc).__name__


def probe_seconds(data, container):
    """The length the container states, best effort (the decode gives the exact one); None when it says nothing."""
    try:
        import av
        with av.open(io.BytesIO(data), format=AV_FORMATS[container]) as box:
            if box.duration:
                return box.duration / 1_000_000
            stream = box.streams.audio[0] if box.streams.audio else None
            if stream is not None and stream.duration and stream.time_base:
                return float(stream.duration * stream.time_base)
    except Exception:                      # noqa: BLE001 only a hint for the pending line
        return None
    return None


def pcm16(data, container):
    """The audio as 16 kHz mono PCM16 samples (numpy int16), whatever rate and depth arrived; the container is parsed
    by av (a WAV's chunks may come in any order)."""
    if container not in AV_FORMATS:
        raise VoiceError(UNKNOWN_CONTAINER)
    import av
    import numpy as np
    out = []
    try:
        with av.open(io.BytesIO(data), format=AV_FORMATS[container]) as box:
            if not box.streams.audio:
                raise VoiceError('里面没有音轨')
            resampler = av.AudioResampler(format='s16', layout='mono', rate=RATE)
            for frame in box.decode(audio=0):
                out.extend(part.to_ndarray().reshape(-1) for part in resampler.resample(frame))
            out.extend(part.to_ndarray().reshape(-1) for part in resampler.resample(None))
    except VoiceError:
        raise
    except Exception as exc:               # noqa: BLE001 av's own errors, in words
        raise VoiceError('音频解不开（%s）' % _av_words(exc)) from exc
    return np.concatenate(out).astype(np.int16) if out else np.zeros(0, dtype=np.int16)


def _has_words(text):
    return any(unicodedata.category(ch)[0] in 'LN' for ch in text)


def _join(pieces):
    out = ''
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if out and out[-1].isascii() and out[-1].isalnum() or out and out[-1] in ',.!?;:' and piece[0].isascii():
            out += ' '
        out += piece
    return out


def _tag(value):
    return str(value or '').strip().removeprefix('<|').removesuffix('|>')


def outcome(seconds, result):
    """Entry fields from a transcription: no speech found is no_voice; speech whose text has no letter or digit is
    no_words; else transcribed. Event labels other than speech are kept to be named."""
    pieces = result.get('pieces') or []
    text = _join(str(piece.get('text') or '') for piece in pieces)
    events = list(dict.fromkeys(_tag(piece.get('event')) for piece in pieces
                                if _tag(piece.get('event')) and _tag(piece.get('event')) != 'Speech'))
    langs = list(dict.fromkeys(_tag(piece.get('lang')) for piece in pieces if _tag(piece.get('lang'))))
    speech = round(float(result.get('speech_seconds') or 0), 2)
    fields = {'seconds': round(seconds, 2), 'speech_seconds': speech, 'events': events, 'lang': ','.join(langs)}
    if speech <= 0 or not pieces:
        return {**fields, 'state': NO_VOICE, 'text': ''}
    if not _has_words(text):
        return {**fields, 'state': NO_WORDS, 'text': text}
    return {**fields, 'state': TRANSCRIBED, 'text': text}


# ---- the engine ---------------------------------------------------------------------------------------------------
def model_dir():
    return DATA / 'models' / MODEL_ID


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


class SenseVoice:
    """SenseVoice int8 with Silero voice detection through sherpa-onnx, on this machine's CPU."""
    model_id = MODEL_ID
    engine = ENGINE

    def __init__(self, directory=None):
        self.directory = Path(directory or model_dir())
        self.ok, self.problems = None, []
        self.recognizer = None

    def check(self):
        """The three model files against their pins, and the package; done once (the Host's start)."""
        problems = []
        for name, (size, digest) in MODEL_FILES.items():
            path = self.directory / name
            if not path.is_file():
                problems.append('%s 不在' % name)
            elif path.stat().st_size != size:
                problems.append('%s 大小不对（%d 字节，应为 %d）' % (name, path.stat().st_size, size))
            elif _file_sha256(path) != digest:
                problems.append('%s 内容和登记的不一样' % name)
        import importlib.util
        for package in ('numpy', 'sherpa_onnx'):
            if importlib.util.find_spec(package) is None:
                problems.append('识别程序包没装（%s）' % package)
        self.ok, self.problems = not problems, problems
        return {'ok': self.ok, 'problems': problems, 'directory': str(self.directory)}

    def ready(self):
        return bool(self.ok)

    def loaded(self):
        return self.recognizer is not None

    def _load(self):
        if self.recognizer is None:
            import sherpa_onnx
            self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(self.directory / 'model.int8.onnx'), tokens=str(self.directory / 'tokens.txt'),
                num_threads=THREADS, use_itn=True, language='auto')
        return self.recognizer

    def transcribe(self, samples):
        """float32 samples at RATE -> {'speech_seconds', 'pieces': [{'text', 'lang', 'event'}]}: each piece the
        detector found, decoded on its own."""
        import sherpa_onnx
        recognizer = self._load()
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = str(self.directory / 'silero_vad.onnx')
        for key, value in VAD.items():
            setattr(config.silero_vad, key, value)
        config.sample_rate = RATE
        detector = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=VAD_BUFFER_SECONDS)
        window = config.silero_vad.window_size
        pieces, speech = [], 0.0

        def take():
            nonlocal speech
            while not detector.empty():
                piece = detector.front.samples
                speech += len(piece) / RATE
                stream = recognizer.create_stream()
                stream.accept_waveform(RATE, piece)
                recognizer.decode_stream(stream)
                result = stream.result
                pieces.append({'text': result.text, 'lang': getattr(result, 'lang', ''),
                               'event': getattr(result, 'event', '')})
                detector.pop()
        for start in range(0, len(samples), window):
            detector.accept_waveform(samples[start:start + window])
            take()
        detector.flush()
        take()
        return {'speech_seconds': speech, 'pieces': pieces}

    def release(self):
        self.recognizer = None


# ---- writing ------------------------------------------------------------------------------------------------------
def _change(store, row_id, index, fields, count=None):
    """Merge `fields` into one entry of a row's `voice` (created with the line's other voices pending); a field given
    as None is taken out. The field is written outside the row's revision (state.COUNTER_FIELDS); only this module
    writes it, under one lock."""
    with _lock:
        row = store.db.messages.find_one({'_id': row_id}, {'voice': 1, 'event.raw.asuna_media': 1, 'received_at': 1})
        if not row:
            return None
        entries = {entry.get('index'): dict(entry) for entry in entries_of(row)}
        total = max(count or 0, voice_count(row), index + 1)
        for number in range(total):
            entries.setdefault(number, {'index': number, 'state': PENDING})
        merged = {**entries[index], **fields, 'index': index}
        entries[index] = {key: value for key, value in merged.items() if value is not None}
        ordered = [entries[number] for number in sorted(entries)]
        store.db.messages.update_one({'_id': row_id}, {'$set': {'voice': ordered}})
        return entries[index]


def _settle(store, row_id):
    """A voice of this line settled: a waiting turn looks again, and once none of the line's voices is pending the
    line enters her conversation."""
    with _settled:
        _settled.notify_all()
    service = SERVICE
    row = store.db.messages.find_one({'_id': row_id}, {'voice': 1})
    if service is not None and not any(entry.get('state') == PENDING for entry in entries_of(row)):
        service.release(row_id)


def mark_shown(store, row_id):
    """The line entered her conversation while a voice of it was still pending: it is projected again once settled."""
    with _lock:
        row = store.db.messages.find_one({'_id': row_id}, {'voice': 1})
        entries = entries_of(row)
        if not entries or not any(entry.get('state') == PENDING for entry in entries):
            return
        changed = [{**entry, 'shown_pending': True} if entry.get('state') == PENDING else entry for entry in entries]
        store.db.messages.update_one({'_id': row_id}, {'$set': {'voice': changed}})


def shown_pending(row):
    return any(entry.get('shown_pending') for entry in entries_of(row))


def row_id_of(store, channel_id, route_id, event_id, occurred_at=None):
    """The stored line a channel's event became: the same identity Channels.receive gives it."""
    from .evidence import canonical, sha
    from .ingress import episode_id
    channel = (store.config.get('channels') or {}).get(channel_id) or {}
    route = (channel.get('routes') or {}).get(route_id)
    if not route:
        raise ValueError('VOICE_ROUTE_UNKNOWN: 这个通道没有路由 %s' % str(route_id)[:40])
    identity = [channel_id, channel['account_id'], route['scene_id'], event_id] + ([occurred_at] if occurred_at else [])
    event = {'scene_id': route['scene_id'], 'event_id': 'channel-' + sha(canonical(identity))}
    return 'in-' + episode_id(event), route


def _reason(refused):
    why = REFUSAL_WORDS.get(str(refused.get('reason') or ''), REFUSAL_WORDS['refused'])
    detail = []
    if isinstance(refused.get('retcode'), int) and not isinstance(refused.get('retcode'), bool):
        detail.append('retcode %d' % refused['retcode'])
    message = ' '.join(str(refused.get('message') or '').split())[:120]
    if message:
        detail.append(message)
    return why + ('（%s）' % '：'.join(detail) if detail else '')


FIELDS = ('route_id', 'event_id', 'occurred_at', 'index')


def receive(store, channel_id, fields, data=None, media_type=None, service=None):
    """One voice of one line: its bytes (`data`) or, as JSON, the platform's refusal (`fields['refused']`:
    `reason`, `retcode`, `message`). The bytes are kept as kind `audio` in the line's scope and queued for
    transcription; a refusal, or a container that is not WAV or MP3, settles the voice at once."""
    unknown = set(fields) - {*FIELDS, 'refused'}
    if unknown:
        raise ValueError('VOICE_FIELD_DENIED: 不认识的字段 %s' % '、'.join(sorted(unknown)))
    event_id, occurred_at = fields.get('event_id'), fields.get('occurred_at')
    if not isinstance(event_id, str) or not 1 <= len(event_id) <= 200:
        raise ValueError('VOICE_EVENT_ID_INVALID: event_id 要是 1–200 字的字符串')
    if occurred_at is not None and not isinstance(occurred_at, str):
        raise ValueError('VOICE_OCCURRED_AT_INVALID: occurred_at 要是字符串，和事件里的一样')
    try:
        index = int(fields.get('index'))
    except (TypeError, ValueError):
        raise ValueError('VOICE_INDEX_INVALID: index 要是这条消息里第几段语音（从 0 数）') from None
    row_id, route = row_id_of(store, channel_id, fields.get('route_id'), event_id, occurred_at)
    row = store.db.messages.find_one({'_id': row_id})
    if not row:
        raise ValueError('VOICE_LINE_NOT_FOUND: 这条语音所在的消息没有存下来（先送事件，被接受后再送语音）')
    count = voice_count(row)
    if not 0 <= index < count:
        raise ValueError('VOICE_INDEX_INVALID: 这条消息有 %d 段语音，没有第 %d 段（从 0 数）' % (count, index))
    current = next((entry for entry in entries_of(row) if entry.get('index') == index), None)
    if current and (current.get('state') != PENDING or current.get('sha256')):
        return {'status': 'duplicate', 'state': current.get('state')}
    moment = now()
    refused = fields.get('refused')
    if data is None:
        if not isinstance(refused, dict):
            raise ValueError('VOICE_BODY_INVALID: 要么送音频字节，要么用 JSON 送 refused')
        entry = _change(store, row_id, index, {'state': NOT_FETCHED, 'reason': _reason(refused), 'arrived_at': moment,
                                               'finished_at': moment}, count)
        _settle(store, row_id)
        return {'status': 'kept', 'state': entry['state']}
    if not data:
        raise ValueError('VOICE_BODY_INVALID: 音频是空的（0 字节）')
    container = sniff(data)
    kept = {'arrived_at': moment, 'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data),
            'head': data[:HEAD_BYTES].hex(), 'media_type': str(media_type or '')[:40]}
    if container is None:
        # Refused before any field is read, and nothing to transcribe: the bytes are never stored.
        entry = _change(store, row_id, index, {**kept, 'state': FAILED, 'reason': UNKNOWN_CONTAINER,
                                               'finished_at': moment}, count)
        _settle(store, row_id)
        return {'status': 'kept', 'state': entry['state']}
    from .blobs import BlobStore
    stored = BlobStore(store).put(data, row['scope_key'], KIND, media_type=container,
                                  source_ids=[SOURCE + row_id + ':' + str(index)])
    kept['artifact_id'] = stored['artifact_id']
    seconds = probe_seconds(data, container)
    if seconds:
        kept['seconds'] = round(seconds, 2)
    entry = _change(store, row_id, index, {**kept, 'state': PENDING}, count)
    service = service or SERVICE
    if service is not None:
        service.enqueue(row_id, index)
    return {'status': 'stored', 'state': entry['state']}


def drop_audio(store, artifact_id):
    """Delete a voice's stored bytes and their manifest; True when nothing of them is left."""
    from bson import ObjectId
    from gridfs import GridFSBucket
    row = store.db.artifacts.find_one({'_id': artifact_id, 'kind': KIND}, {'gridfs_id': 1})
    if row and row.get('gridfs_id'):
        try:
            GridFSBucket(store.db, bucket_name='artifact_blobs').delete(ObjectId(row['gridfs_id']))
        except Exception:                   # noqa: BLE001 the bytes are gone already: the manifest still goes
            pass
    store.db.artifacts.delete_one({'_id': artifact_id, 'kind': KIND})
    return store.db.artifacts.find_one({'_id': artifact_id}, {'_id': 1}) is None


# ---- a turn's wait ------------------------------------------------------------------------------------------------
def waiting_rows(store, scene_id, until_seq, moment=None):
    """The lines up to `until_seq` in this conversation whose voice is still being fetched or transcribed."""
    moment = moment or datetime.now(timezone.utc)
    since = (moment - timedelta(seconds=TURN_LOOKBACK_SECONDS)).isoformat()
    rows = store.db.messages.find({'scene_id': scene_id, 'direction': 'inbound', 'scene_seq': {'$lte': until_seq},
                                   'received_at': {'$gte': since},
                                   'event.raw.asuna_media.items.type': {'$in': list(VOICE_TYPES)}},
                                  {'voice': 1, 'event.raw.asuna_media': 1, 'event.channel': 1, 'adapter_id': 1,
                                   'received_at': 1})
    return [row['_id'] for row in rows if unsettled(store, row, moment)]


def await_turn(store, event, timeout=WAIT_SECONDS):
    """Before a turn on a platform line: wait up to `timeout` seconds in all for the voices in its lines, then go on
    with whatever state they have. Returns (seconds waited, the lines still waiting)."""
    if SERVICE is None or not event.get('channel'):
        return 0.0, []
    from .ingress import episode_id
    source = store.db.messages.find_one({'_id': 'in-' + episode_id(event)}, {'scene_seq': 1, 'scene_id': 1})
    if not source or source.get('scene_seq') is None:
        return 0.0, []
    started = time.monotonic()
    while True:
        rows = waiting_rows(store, source['scene_id'], source['scene_seq'])
        left = timeout - (time.monotonic() - started)
        if not rows or left <= 0:
            return round(time.monotonic() - started, 2), rows
        with _settled:
            _settled.wait(min(left, 1.0))


def holds_projection(store, row):
    """Keep this line out of her conversation for now: a voice of it is still on its way and a Service will put the
    line in once it settles (or WAIT_SECONDS passed)."""
    return SERVICE is not None and SERVICE.running() and _project is not None and unsettled(store, row)


# ---- the worker ---------------------------------------------------------------------------------------------------
class Service:
    """Transcribes voices one at a time in arrival order, in the Host's process, and releases the lines that wait for
    them. Never raises out of its loop: a failure settles that voice with its reason."""

    def __init__(self, store, evidence=None, engine=None, *, idle_seconds=IDLE_SECONDS, wait_seconds=WAIT_SECONDS):
        self.store, self.evidence = store, evidence
        self.engine = engine if engine is not None else SenseVoice()
        self.idle_seconds, self.wait_seconds = idle_seconds, wait_seconds
        self.jobs = Queue()
        self.holds = {}
        self.hold_lock = threading.Lock()
        self.stopping = threading.Event()
        self.checked = threading.Event()
        self.last_voice = None
        self.thread = threading.Thread(target=self._run, name='asuna-voice', daemon=True)

    def start(self):
        global SERVICE
        SERVICE = self
        self.thread.start()
        return self

    def running(self):
        return self.thread.is_alive() and not self.stopping.is_set()

    def close(self):
        global SERVICE
        self.stopping.set()
        with self.hold_lock:
            timers, self.holds = list(self.holds.values()), {}
        for timer in timers:
            timer.cancel()
        self.jobs.put(None)
        self.thread.join(timeout=10)
        if SERVICE is self:
            SERVICE = None
        self.engine.release()

    def enqueue(self, row_id, index):
        self.jobs.put((row_id, index))

    def hold(self, row_id):
        """A line waits out of her conversation until its voices settle, at most wait_seconds (its own timer, so a
        long transcription never holds a line longer)."""
        with self.hold_lock:
            if row_id in self.holds:
                return
            timer = threading.Timer(self.wait_seconds, self._wait_ran_out, args=(row_id,))
            timer.daemon = True
            self.holds[row_id] = timer
        timer.start()

    def _wait_ran_out(self, row_id):
        with self.hold_lock:
            if self.holds.pop(row_id, None) is None:
                return
        self._put_in(row_id, True)

    def release(self, row_id):
        """Its voices settled: put the line into her conversation, or once more if it is there already while still
        being transcribed."""
        with self.hold_lock:
            timer = self.holds.pop(row_id, None)
        if timer is not None:
            timer.cancel()
        self._put_in(row_id, False)

    def _put_in(self, row_id, released):
        project = _project
        if project is None:
            return
        try:
            project(row_id, released)
        except Exception:                   # noqa: BLE001 the line is durable; the next start projects it
            self._record('voice.project_failed', {'row_id': row_id, 'traceback': traceback.format_exc()[-800:]})

    def _record(self, kind, payload):
        if self.evidence is not None:
            try:
                self.evidence.record(kind, payload)
            except Exception:               # noqa: BLE001 evidence is best effort here
                pass

    def _run(self):
        try:
            checked = self.engine.check()
            if not checked['ok']:
                # Logged once: every voice then reads 「没转出文字：识别模型不在」.
                log.warning('voice model unavailable: %s', '; '.join(checked['problems']))
            self._record('voice.model_checked', checked)
        except Exception:                   # noqa: BLE001
            self._record('voice.model_check_failed', {'traceback': traceback.format_exc()[-800:]})
        self.checked.set()
        try:
            self._recover()
        except Exception:                   # noqa: BLE001
            self._record('voice.recover_failed', {'traceback': traceback.format_exc()[-800:]})
        while not self.stopping.is_set():
            try:
                job = self.jobs.get(timeout=1.0)
            except Empty:
                job = None
            if job is not None:
                self._transcribe(*job)
            self._give_way()

    def _recover(self):
        """At start: voices whose bytes came before the last stop and were not transcribed yet go back on the queue (their
        bytes go once they are); bytes of a voice that settled but were not deleted go now."""
        for row in self.store.db.messages.find({'voice.state': PENDING}, {'voice': 1}).sort('received_at', 1):
            for entry in entries_of(row):
                if entry.get('state') == PENDING and entry.get('artifact_id'):
                    self.enqueue(row['_id'], entry['index'])
        for artifact in self.store.db.artifacts.find({'kind': KIND}, {'source_ids': 1}):
            row_id, _, index = str(next(iter(artifact.get('source_ids') or ()), ''))[len(SOURCE):].rpartition(':')
            row = self.store.db.messages.find_one({'_id': row_id}, {'voice': 1}) if row_id else None
            entry = next((item for item in entries_of(row) if str(item.get('index')) == index), None)
            if entry and entry.get('state') == PENDING:
                continue
            if drop_audio(self.store, artifact['_id']) and entry:
                _change(self.store, row_id, entry['index'], {'artifact_id': None, 'audio_removed_at': now()})

    def _give_way(self):
        """The model gives way to other services when it sits idle, not only at a restart."""
        if self.last_voice is not None and self.jobs.empty() and getattr(self.engine, 'loaded', lambda: False)() \
                and time.monotonic() - self.last_voice >= self.idle_seconds:
            self.engine.release()
            self._record('voice.model_released', {'idle_seconds': self.idle_seconds})

    def _transcribe(self, row_id, index):
        started = time.monotonic()
        try:
            row = self.store.db.messages.find_one({'_id': row_id}, {'voice': 1, 'scope_key': 1})
            entry = next((item for item in entries_of(row) if item.get('index') == index), None)
            if not row or not entry or entry.get('state') != PENDING or not entry.get('artifact_id'):
                return
            fields = self._result(row, entry)
        except Exception as exc:            # noqa: BLE001 a program fault settles the voice, with its class
            fields = {'state': FAILED, 'reason': '识别程序出错（%s）' % type(exc).__name__}
            self._record('voice.fault', {'row_id': row_id, 'index': index, 'traceback': traceback.format_exc()[-800:]})
        finally:
            self.last_voice = time.monotonic()
        fields['finished_at'] = now()
        detail = {key: fields.pop(key) for key in ('speech_seconds', 'lang') if key in fields}
        # Whatever came of it, the bytes go now; the row keeps the record (owner, ADR-093).
        try:
            if drop_audio(self.store, entry['artifact_id']):
                fields.update(artifact_id=None, audio_removed_at=now())
        except Exception:                   # noqa: BLE001 left for the next start's recovery to try again
            self._record('voice.drop_failed', {'row_id': row_id, 'index': index,
                                               'traceback': traceback.format_exc()[-800:]})
        _change(self.store, row_id, index, fields)
        self._record('voice.settled', {'row_id': row_id, 'index': index, 'state': fields['state'],
                                       'seconds': fields.get('seconds'), 'chars': len(fields.get('text') or ''),
                                       **detail, 'engine': dict(getattr(self.engine, 'engine', ENGINE)),
                                       'took_seconds': round(time.monotonic() - started, 2)})
        _settle(self.store, row_id)

    def _result(self, row, entry):
        if not self.engine.ready():
            return {'state': FAILED, 'reason': MODEL_MISSING}
        from .blobs import BlobStore
        try:
            data = BlobStore(self.store).get(entry['artifact_id'], row['scope_key'], operator=True)
        except Exception as exc:            # noqa: BLE001 removed or damaged
            return {'state': FAILED, 'reason': '存着的音频读不出来（%s）' % ' '.join(str(exc).split())[:60]}
        try:
            samples = pcm16(data, sniff(data))
        except VoiceError as exc:
            return {'state': FAILED, 'reason': str(exc)}
        seconds = len(samples) / RATE
        if not len(samples):
            return {'state': FAILED, 'reason': '音频是空的', 'seconds': 0}
        result = self.engine.transcribe(samples.astype('float32') / 32768.0)
        return {**outcome(seconds, result), 'model': MODEL_ID}
