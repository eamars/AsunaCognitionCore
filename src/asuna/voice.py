"""Voice messages arrive as text (ADR-093): a channel adapter fetches each voice of a message before it submits the
line and posts the audio to `POST /v1/channels/<id>/voice`; the program turns it into text on this machine within that
request and answers with the outcome; the line, posted after, is stored with its voices already settled.

- `receive` is the endpoint: one voice segment of a line not yet posted, keyed by the channel's event id and the
  segment's index. The container is recognized by its first bytes (RIFF/WAVE, ID3 or an MPEG audio frame header)
  before anything else is read. The audio is never stored: it lives in memory for the request, and the outcome keeps
  its sha256, size, first 44 bytes and media type. The outcome waits in memory for its line (KEEP_SECONDS).
- `Transcriber` decodes with av, resamples to 16 kHz mono PCM16 and hands the model float samples: SenseVoice int8 with
  Silero voice detection through sherpa-onnx, one voice at a time, loaded when a voice comes and released after
  IDLE_SECONDS without one. The model files are checked against their pins (MODEL_FILES) once at the Host's start;
  missing or different, that is said in one Host log line, and every voice reads 「没转出文字：识别模型不在」.
- `entries_for` gives a line its voices when the channel event arrives (channels.py): the outcome posted for each
  segment, or the adapter's reason for not getting it (`REFUSED_KEY` on the segment's media item). They are stored
  with the line, in its event (`event.voice`, one entry per voice, ENTRY_FIELDS), and never change afterwards.
- `line_text` is a line as she reads it: each voice placeholder replaced, in order, by its voice's words (`words`);
  the stored text stays as it arrived.
"""
from __future__ import annotations

import hashlib
import io
import sys
import threading
import time
import traceback
import unicodedata
from pathlib import Path

from .config import DATA
from .state import now

VOICE_TYPES = ('record', 'audio')     # media item types that are a voice
PLACEHOLDER = '[语音（未解析）]'        # what the adapter writes in the line for a voice segment
REFUSED_KEY = 'voice_refused'         # on a voice's media item: why the adapter did not get its outcome

TRANSCRIBED, NO_VOICE, NO_WORDS, FAILED, NOT_FETCHED = 'transcribed', 'no_voice', 'no_words', 'failed', 'not_fetched'
STATES = (TRANSCRIBED, NO_VOICE, NO_WORDS, FAILED, NOT_FETCHED)
# One entry per voice of a line, in its event (`event.voice`); nothing else of the audio is kept:
ENTRY_FIELDS = {
    'index': 'its place among the line\'s voices (0 first)', 'state': 'one of STATES',
    'seconds': 'length of the audio', 'text': 'the words, as the model wrote them',
    'events': 'its event labels other than speech', 'reason': 'why it failed or was not fetched, in words',
    'sha256': 'of the bytes as they came', 'size': 'bytes', 'head': 'the first 44 bytes, hex',
    'media_type': 'what the adapter declared', 'model': 'MODEL_ID',
    'arrived_at': 'when the bytes came', 'finished_at': 'when its outcome was settled',
}

IDLE_SECONDS = 600                    # the model is released after this long with no voice
KEEP_SECONDS = 600                    # an outcome waits this long in memory for its line
MAX_INDEX = 63                        # a message's voices, counted from 0
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
# Why the adapter has no outcome for a voice, as her line says it: the adapter sends one of these reasons.
REFUSAL_WORDS = {'gone': '平台上已经没有这条语音了', 'refused': '平台没给出音频', 'timeout': '向平台取音频超时了',
                 'unreachable': '连不上平台', 'no_audio': '平台的回话里没有音频',
                 'host': '交给本机识别时出了错'}

TRANSCRIBER = None                    # the Host's Transcriber, while it runs
_outcomes = {}                        # (channel id, event key, index) -> (monotonic time, entry)
_outcomes_lock = threading.Lock()


class VoiceError(Exception):
    """A voice that cannot be transcribed, with the reason in words."""


# ---- reading ------------------------------------------------------------------------------------------------------
def media_items(raw):
    block = (raw or {}).get('asuna_media') if isinstance(raw, dict) else None
    items = block.get('items') if isinstance(block, dict) else None
    return [item for item in items or () if isinstance(item, dict)]


def entries_of(row):
    """A stored line's voices (`event.voice`)."""
    voices = (((row or {}).get('event') or {}).get('voice')) or ()
    return [entry for entry in voices if isinstance(entry, dict)]


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
    entry = entry or {}
    state, length = entry.get('state'), _seconds(entry)
    if state == TRANSCRIBED:
        return '[语音%s%s] %s' % (length, _heard(entry), ' '.join(str(entry.get('text') or '').split()))
    if state == NO_VOICE:
        return '[语音%s，里面没有人声]' % length
    if state == NO_WORDS:
        heard = _heard(entry)
        return ('[语音%s%s，听不出说的什么]' % (length, heard) if heard
                else '[语音%s，有人在说话，但听不出说的什么]' % length)
    if state == NOT_FETCHED:
        return '[语音，没拿到：%s]' % (entry.get('reason') or '原因没记下')
    return '[语音%s，没转出文字：%s]' % (length, entry.get('reason') or '原因没记下')


def line_text(row):
    """The line's text as she reads it: each voice placeholder, in order, replaced by its voice's words; a line
    without voices reads as it arrived."""
    text = str((row or {}).get('text') or '')
    said = {entry.get('index'): words(entry) for entry in entries_of(row)}
    if not said:
        return text
    pieces = text.split(PLACEHOLDER)
    out = [pieces[0]]
    for index, piece in enumerate(pieces[1:]):
        out.append(said.pop(index, PLACEHOLDER))
        out.append(piece)
    return ''.join(out) + ''.join(' ' + said[index] for index in sorted(said))


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
        raise VoiceError('音频解不开（%s）' % (' '.join(str(exc).split())[:80] or type(exc).__name__)) from exc
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
    no_words; else transcribed. Event labels other than speech are kept to be named. `speech_seconds` and `lang` are
    for the evidence, not the line."""
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
        """The three model files against their pins, and the package."""
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


class Transcriber:
    """The Host's one transcriber: checks the model files once when it starts (a missing or different file is one
    Host log line), transcribes one voice at a time, and releases the model after `idle_seconds` without a voice."""

    def __init__(self, evidence=None, engine=None, *, idle_seconds=IDLE_SECONDS):
        self.evidence = evidence
        self.engine = engine if engine is not None else SenseVoice()
        self.idle_seconds = idle_seconds
        self.lock = threading.Lock()
        self.checked = threading.Event()
        self.idle = None

    def start(self):
        global TRANSCRIBER
        TRANSCRIBER = self
        threading.Thread(target=self._check, name='asuna-voice-check', daemon=True).start()
        return self

    def close(self):
        global TRANSCRIBER
        if TRANSCRIBER is self:
            TRANSCRIBER = None
        with self.lock:
            if self.idle is not None:
                self.idle.cancel()
            self.engine.release()

    def _record(self, kind, payload):
        if self.evidence is not None:
            try:
                self.evidence.record(kind, payload)
            except Exception:               # noqa: BLE001 evidence is best effort here
                pass

    def _check(self):
        try:
            checked = self.engine.check()
        except Exception as exc:            # noqa: BLE001 a check that cannot run leaves the model unusable, said so
            checked = {'ok': False, 'problems': ['检查出错（%s）' % type(exc).__name__]}
        if not checked['ok']:
            # The one Host log line: every voice then reads 「没转出文字：识别模型不在」.
            print('ASUNA_VOICE_MODEL_UNAVAILABLE %s: %s; voices read 没转出文字：%s'
                  % (checked.get('directory') or model_dir(), '; '.join(checked['problems']), MODEL_MISSING),
                  file=sys.stderr, flush=True)
        self._record('voice.model_checked', checked)
        self.checked.set()

    def _idle(self):
        with self.lock:
            if self.engine.loaded():
                self.engine.release()
                self._record('voice.model_released', {'idle_seconds': self.idle_seconds})

    def transcribe(self, data, media_type=None):
        """One voice's bytes -> its entry (ENTRY_FIELDS without `index`); never raises."""
        started = time.monotonic()
        entry = {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data), 'head': data[:HEAD_BYTES].hex(),
                 'media_type': str(media_type or '')[:40], 'arrived_at': now()}
        detail = {}
        container = sniff(data)
        if container is None:
            entry.update(state=FAILED, reason=UNKNOWN_CONTAINER)
        else:
            self.checked.wait(120)
            if not self.engine.ready():
                entry.update(state=FAILED, reason=MODEL_MISSING)
            else:
                try:
                    samples = pcm16(data, container)
                    if not len(samples):
                        raise VoiceError('音频是空的')
                    with self.lock:
                        if self.idle is not None:
                            self.idle.cancel()
                        try:
                            result = self.engine.transcribe(samples.astype('float32') / 32768.0)
                        finally:
                            self.idle = threading.Timer(self.idle_seconds, self._idle)
                            self.idle.daemon = True
                            self.idle.start()
                    fields = outcome(len(samples) / RATE, result)
                    detail = {key: fields.pop(key) for key in ('speech_seconds', 'lang')}
                    entry.update(fields, model=MODEL_ID)
                except VoiceError as exc:
                    entry.update(state=FAILED, reason=str(exc))
                except Exception as exc:    # noqa: BLE001 a program fault is this voice's failure, with its class
                    entry.update(state=FAILED, reason='识别程序出错（%s）' % type(exc).__name__)
                    self._record('voice.fault', {'traceback': traceback.format_exc()[-800:]})
        entry['finished_at'] = now()
        self._record('voice.settled', {'state': entry['state'], 'seconds': entry.get('seconds'),
                                       'chars': len(entry.get('text') or ''), **detail,
                                       'engine': dict(getattr(self.engine, 'engine', ENGINE)),
                                       'took_seconds': round(time.monotonic() - started, 2)})
        return entry


# ---- the endpoint and the line ------------------------------------------------------------------------------------
def event_key(store, channel_id, route_id, event_id, occurred_at=None):
    """The event id Channels.receive gives a channel event (`channel-…`), from what the adapter posts."""
    from .evidence import canonical, sha
    channel = (store.config.get('channels') or {}).get(channel_id) or {}
    route = (channel.get('routes') or {}).get(route_id)
    if not route:
        raise ValueError('VOICE_ROUTE_UNKNOWN: 这个通道没有路由 %s' % str(route_id)[:40])
    identity = [channel_id, channel['account_id'], route['scene_id'], event_id] + ([occurred_at] if occurred_at else [])
    return 'channel-' + sha(canonical(identity)), route


def _keep(key, entry):
    moment = time.monotonic()
    with _outcomes_lock:
        for old in [old for old, (at, _) in _outcomes.items() if moment - at > KEEP_SECONDS]:
            del _outcomes[old]
        _outcomes[key] = (moment, entry)


def _kept(key):
    with _outcomes_lock:
        found = _outcomes.get(key)
    return dict(found[1]) if found and time.monotonic() - found[0] <= KEEP_SECONDS else None


FIELDS = ('route_id', 'event_id', 'occurred_at', 'index')


def receive(store, channel_id, fields, data, media_type=None, transcriber=None):
    """One voice of a line about to be posted, as its bytes: transcribed now, its outcome kept for the line and
    answered. The same voice posted again answers what was settled the first time."""
    unknown = set(fields) - set(FIELDS)
    if unknown:
        raise ValueError('VOICE_FIELD_DENIED: 不认识的字段 %s' % '、'.join(sorted(unknown)))
    event_id, occurred_at = fields.get('event_id'), fields.get('occurred_at')
    if not isinstance(event_id, str) or not 1 <= len(event_id) <= 200:
        raise ValueError('VOICE_EVENT_ID_INVALID: event_id 要是 1–200 字的字符串，和事件里的一样')
    if occurred_at is not None and not isinstance(occurred_at, str):
        raise ValueError('VOICE_OCCURRED_AT_INVALID: occurred_at 要是字符串，和事件里的一样')
    try:
        index = int(fields.get('index'))
    except (TypeError, ValueError):
        index = -1
    if not 0 <= index <= MAX_INDEX:
        raise ValueError('VOICE_INDEX_INVALID: index 是这条消息里第几段语音（0–%d）' % MAX_INDEX)
    if not data:
        raise ValueError('VOICE_BODY_INVALID: 请求体要是这段语音的字节，给的是空的')
    key, _ = event_key(store, channel_id, fields.get('route_id'), event_id, occurred_at)
    kept = _kept((channel_id, key, index))
    if kept:
        return {'status': 'duplicate', 'state': kept['state']}
    transcriber = transcriber or TRANSCRIBER
    if transcriber is None:
        raise RuntimeError('VOICE_TRANSCRIBER_NOT_RUNNING')
    entry = transcriber.transcribe(data, media_type)
    _keep((channel_id, key, index), entry)
    return {'status': 'settled', 'state': entry['state'], **({'seconds': entry['seconds']} if 'seconds' in entry else {})}


def _reason(refused):
    why = REFUSAL_WORDS.get(str(refused.get('reason') or ''), REFUSAL_WORDS['refused'])
    detail = []
    if isinstance(refused.get('retcode'), int) and not isinstance(refused.get('retcode'), bool):
        detail.append('retcode %d' % refused['retcode'])
    message = ' '.join(str(refused.get('message') or '').split())[:120]
    if message:
        detail.append(message)
    return why + ('（%s）' % '：'.join(detail) if detail else '')


def entries_for(channel_id, key, raw):
    """A channel line's voices as it is stored (`event.voice`): for each voice segment, the outcome posted for it, else
    the adapter's reason for not having one; a segment with neither has no entry and reads as its placeholder."""
    out = []
    voices = [item for item in media_items(raw) if item.get('type') in VOICE_TYPES]
    for index, item in enumerate(voices):
        entry = _kept((channel_id, key, index))
        refused = item.get(REFUSED_KEY)
        if entry is None and isinstance(refused, dict):
            entry = {'state': NOT_FETCHED, 'reason': _reason(refused), 'finished_at': now()}
        if entry is not None:
            out.append({**entry, 'index': index})
    return out
