"""Voice messages arrive as text (ADR-093): the container is recognized by its first bytes, the audio normalized to
16 kHz mono PCM16, each state has its own words in her line (never empty), a turn waits 10 s in all, the bytes are
deleted as soon as the text is out (whatever came of it) while the row keeps its record, and a line whose voice is
still being transcribed waits out of her conversation.

Unit tests use a fake transcriber; one test runs the real model on the model repository's own sample clips when the
model files are present, and skips saying where it looked when they are not."""
import hashlib
import io
import json
import struct
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from asuna import capabilities, media_life, voice
from asuna.channels import Channels, ChannelServer
from asuna.config import DATA, ROOT
from asuna.ingress import persist_input
from asuna.people import People
from test_people import BOT, GROUP, SCENE, setup as people_setup

np = pytest.importorskip('numpy')
av = pytest.importorskip('av')

TOKEN = 'x' * 24
MEMBERS = {'20002': 'qq:20002', '20003': 'qq:20003'}


# ---- audio made here --------------------------------------------------------------------------------------------
def pcm(seconds, rate, tone=440.0, level=8000):
    t = np.arange(int(seconds * rate)) / rate
    return (np.sin(2 * np.pi * tone * t) * level).astype('<i2') if tone else np.zeros(int(seconds * rate), '<i2')


def wav(seconds=1.0, rate=24000, tone=440.0, list_chunk=True):
    """A RIFF/WAVE file as NapCat gave one: PCM16 mono with a LIST chunk after fmt, so data does not start at 44."""
    data = pcm(seconds, rate, tone).tobytes()
    fmt = struct.pack('<4sIHHIIHH', b'fmt ', 16, 1, 1, rate, rate * 2, 2, 16)
    info = b'INFO' + b'ISFT' + struct.pack('<I', 14) + b'Lavf61.7.100\x00\x00'
    listed = b'LIST' + struct.pack('<I', len(info)) + info if list_chunk else b''
    body = b'WAVE' + fmt + listed + b'data' + struct.pack('<I', len(data)) + data
    return b'RIFF' + struct.pack('<I', len(body)) + body


def mp3(seconds=1.0, rate=24000):
    out = io.BytesIO()
    with av.open(out, mode='w', format='mp3') as box:
        stream = box.add_stream('libmp3lame', rate=rate, layout='mono')
        samples = pcm(seconds, rate).reshape(1, -1)
        frame = av.AudioFrame.from_ndarray(samples, format='s16', layout='mono')
        frame.sample_rate = rate
        for packet in stream.encode(frame):
            box.mux(packet)
        for packet in stream.encode(None):
            box.mux(packet)
    return out.getvalue()


# ---- the container and the samples (no database) -----------------------------------------------------------------
def test_an_unknown_container_is_refused_with_words_before_any_field_is_read():
    for data in (b'#!AMR\n' + bytes(40), b'OggS' + bytes(40), b'#!SILK_V3' + bytes(40), bytes([0xFF, 0xF1, 0x50, 0x80]),
                 b'RIFF\x24\x00\x00\x00AVI ' + bytes(40), b''):
        assert voice.sniff(data) is None, data[:12]
    with pytest.raises(voice.VoiceError) as refused:
        voice.pcm16(b'OggS' + bytes(40), voice.sniff(b'OggS' + bytes(40)))
    assert str(refused.value) == voice.UNKNOWN_CONTAINER
    assert voice.words({'state': voice.FAILED, 'reason': voice.UNKNOWN_CONTAINER}) == \
        '[语音，没转出文字：不是认得的音频格式（按开头的字节看不是 WAV 或 MP3）]'


def test_a_wav_with_a_list_chunk_before_data_is_parsed_by_av_and_resampled_to_16k_pcm16():
    data = wav(seconds=1.5, rate=24000)
    assert data.find(b'data') > 36 + 8, 'the data chunk is not at byte 44 here'
    assert voice.sniff(data) == 'audio/wav'
    samples = voice.pcm16(data, 'audio/wav')
    assert samples.dtype == np.int16 and abs(len(samples) - 1.5 * voice.RATE) < 400
    assert int(np.abs(samples).max()) > 4000, 'the tone survived the resampling'
    stereo48 = voice.pcm16(wav(seconds=0.5, rate=48000, list_chunk=False), 'audio/wav')
    assert abs(len(stereo48) - 0.5 * voice.RATE) < 400, 'whatever rate arrives'


def test_an_mp3_is_recognized_by_id3_or_frame_header_and_decoded():
    data = mp3(seconds=1.0)
    assert voice.sniff(data) == 'audio/mpeg'
    assert voice.sniff(bytes([0xFF, 0xFB, 0x90, 0x64]) + bytes(40)) == 'audio/mpeg'
    assert voice.sniff(b'ID3\x04' + bytes(40)) == 'audio/mpeg'
    assert abs(len(voice.pcm16(data, 'audio/mpeg')) - voice.RATE) < 2000


def test_a_decode_error_is_a_failed_voice_with_its_reason():
    broken = b'RIFF\x40\x00\x00\x00WAVE' + b'junk' * 30
    assert voice.sniff(broken) == 'audio/wav'
    with pytest.raises(voice.VoiceError) as failed:
        voice.pcm16(broken, 'audio/wav')
    assert str(failed.value).startswith('音频解不开（')


def test_every_state_has_its_own_words_and_none_is_empty():
    said = {
        voice.TRANSCRIBED: voice.words({'state': 'transcribed', 'seconds': 33.4, 'text': '今天 下雨'}),
        voice.PENDING: voice.words({'state': 'pending', 'seconds': 33.4}),
        voice.NO_VOICE: voice.words({'state': 'no_voice', 'seconds': 5}),
        voice.NO_WORDS: voice.words({'state': 'no_words', 'seconds': 12}),
        voice.FAILED: voice.words({'state': 'failed', 'seconds': 33, 'reason': voice.MODEL_MISSING}),
        voice.NOT_FETCHED: voice.words({'state': 'not_fetched', 'reason': '平台上已经没有这条语音了'}),
    }
    assert said == {
        'transcribed': '[语音 33 秒] 今天 下雨',
        'pending': '[语音 33 秒，正在转写，转完字会补在这一行]',
        'no_voice': '[语音 5 秒，里面没有人声]',
        'no_words': '[语音 12 秒，有人在说话，但听不出说的什么]',
        'failed': '[语音 33 秒，没转出文字：识别模型不在]',
        'not_fetched': '[语音，没拿到：平台上已经没有这条语音了]'}
    assert voice.words({'state': 'pending'}) == '[语音，正在转写，转完字会补在这一行]'
    assert all(voice.words({'state': state}) for state in (*voice.FINAL, voice.PENDING, None))


def test_no_voice_is_the_detectors_verdict_and_no_words_is_speech_without_a_letter():
    assert voice.outcome(5.0, {'speech_seconds': 0, 'pieces': []})['state'] == voice.NO_VOICE
    quiet = voice.outcome(12.0, {'speech_seconds': 3.1, 'pieces': [{'text': '。', 'lang': '<|zh|>',
                                                                     'event': '<|Speech|>'}]})
    assert quiet['state'] == voice.NO_WORDS and quiet['speech_seconds'] == 3.1 and quiet['events'] == []
    spoken = voice.outcome(7.2, {'speech_seconds': 6.0, 'pieces': [
        {'text': 'The tribal chieftain called', 'lang': '<|en|>', 'event': '<|Speech|>'},
        {'text': '开放时间早上9点', 'lang': '<|zh|>', 'event': '<|Speech|>'}]})
    assert spoken['state'] == voice.TRANSCRIBED and spoken['lang'] == 'en,zh'
    assert spoken['text'] == 'The tribal chieftain called 开放时间早上9点'
    assert voice.outcome(3.0, {'speech_seconds': 1.0, 'pieces': [{'text': '3'}]})['state'] == voice.TRANSCRIBED


def test_a_label_other_than_speech_is_named_in_the_line():
    music = voice.outcome(20.0, {'speech_seconds': 9, 'pieces': [{'text': '啦啦啦', 'event': '<|BGM|>'},
                                                                  {'text': '好听', 'event': '<|Speech|>'}]})
    assert music['events'] == ['BGM']
    assert voice.words({**music, 'state': music['state']}) == '[语音 20 秒，听着像背景音乐] 啦啦啦好听'
    laugh = voice.outcome(4.0, {'speech_seconds': 2, 'pieces': [{'text': '', 'event': '<|Laughter|>'}]})
    assert voice.words(laugh) == '[语音 4 秒，听着像笑声，听不出说的什么]'
    odd = voice.outcome(4.0, {'speech_seconds': 2, 'pieces': [{'text': '嗯嗯', 'event': '<|Something_New|>'}]})
    assert voice.words(odd) == '[语音 4 秒，听着像别的声音] 嗯嗯'


def test_two_voices_in_one_line_read_in_order_and_the_stored_text_stays():
    row = {'text': '[语音（未解析）]和[语音（未解析）]',
           'voice': [{'index': 1, 'state': 'no_voice', 'seconds': 2}, {'index': 0, 'state': 'transcribed',
                                                                       'seconds': 3, 'text': '你好'}]}
    assert voice.line_text(row) == '[语音 3 秒] 你好和[语音 2 秒，里面没有人声]'
    assert row['text'] == '[语音（未解析）]和[语音（未解析）]'
    assert voice.line_text({'text': '[语音（未解析）]'}) == '[语音（未解析）]', 'no voice_in: the line as today'


def test_model_files_missing_or_different_are_named(tmp_path):
    missing = voice.SenseVoice(tmp_path / 'nothing').check()
    assert not missing['ok'] and {'model.int8.onnx 不在', 'tokens.txt 不在', 'silero_vad.onnx 不在'} <= set(missing['problems'])
    folder = tmp_path / 'wrong'
    folder.mkdir()
    (folder / 'model.int8.onnx').write_bytes(b'x' * 10)
    with open(folder / 'tokens.txt', 'wb') as handle:              # the right size, other bytes
        handle.truncate(voice.MODEL_FILES['tokens.txt'][0])
    problems = voice.SenseVoice(folder).check()['problems']
    assert any(p.startswith('model.int8.onnx 大小不对') for p in problems)
    assert 'tokens.txt 内容和登记的不一样' in problems and 'silero_vad.onnx 不在' in problems


# ---- the endpoint, the worker and her line (MongoDB) --------------------------------------------------------------
class FakeEngine:
    """SUBSTITUTE for SenseVoice: answers a canned transcription; `gate` holds it until set."""
    model_id = 'fake'
    engine = {'engine': 'fake'}

    def __init__(self, result=None, ok=True, gate=None):
        self.result = result or {'speech_seconds': 1.0, 'pieces': [{'text': '你好', 'lang': '<|zh|>',
                                                                     'event': '<|Speech|>'}]}
        self.ok, self.gate, self.calls, self.released, self.is_loaded = ok, gate, [], 0, False

    def check(self):
        return {'ok': self.ok, 'problems': [] if self.ok else ['model.int8.onnx 不在'], 'directory': 'fake'}

    def ready(self):
        return self.ok

    def loaded(self):
        return self.is_loaded

    def transcribe(self, samples):
        self.is_loaded = True
        self.calls.append(len(samples))
        if self.gate is not None:
            self.gate.wait(10)
        return self.result

    def release(self):
        self.released += 1
        self.is_loaded = False


@pytest.fixture
def services(store):
    made = []

    def start(engine=None, **kwargs):
        service = voice.Service(store, None, engine or FakeEngine(), **kwargs).start()
        made.append(service)
        assert service.checked.wait(5)
        return service
    yield start
    for service in made:
        service.close()
    voice.attach(None)


def world(store, declare=True):
    people_setup(store)
    store.db.scenes.update_one({'_id': SCENE}, {'$set': {'members': list(MEMBERS.values()), 'channel_id': 'qq'}})
    store.config['channels'] = {'qq': {'account_id': BOT, 'token': TOKEN, 'routes': {'g': {
        'scene_id': SCENE, 'target': {'type': 'group', 'id': GROUP},
        'members': {sender: {'person_id': person} for sender, person in MEMBERS.items()}}}}}
    if declare:
        capabilities.declared(store, 'qq', ['image', 'voice_in'])

    def receive(event):
        row, created = persist_input(store, event, managed=True)
        return {'status': 'accepted' if created else 'duplicate', 'episode_id': row['episode_id']}
    controller = SimpleNamespace(app=SimpleNamespace(store=store, config=store.config,
                                                     evidence=SimpleNamespace(record=lambda *args, **kwargs: None)),
                                 stopping=threading.Event(), reconfiguring=False, ingress_lock=threading.RLock(),
                                 receive=receive, emit=lambda text: None)
    return Channels(controller)


def line(channels, event_id, voices=1, text=None, sender='20002'):
    items = [{'type': 'record', 'placeholder': voice.PLACEHOLDER, 'file': 'v%d.amr' % n} for n in range(voices)]
    body = {'route_id': 'g', 'account_id': BOT, 'sender_id': sender, 'event_id': event_id,
            'text': text or '和'.join([voice.PLACEHOLDER] * voices), 'group_id': GROUP, 'mentioned_account_ids': [],
            'raw': {'asuna_media': {'count': voices, 'items': items}}, 'occurred_at': '2026-10-23T01:00:00Z'}
    assert channels.receive('qq', body)['status'] == 'accepted'
    row_id, _ = voice.row_id_of(channels.store, 'qq', 'g', event_id, body['occurred_at'])
    return row_id


def post(port, event_id, index=0, data=None, refused=None):
    query = 'route_id=g&event_id=%s&index=%d&occurred_at=2026-10-23T01%%3A00%%3A00Z' % (event_id, index)
    if data is not None:
        request = urllib.request.Request('http://127.0.0.1:%d/v1/channels/qq/voice?%s' % (port, query), data=data,
                                         method='POST', headers={'Authorization': 'Bearer ' + TOKEN,
                                                                 'Content-Type': 'audio/mpeg'})
    else:
        body = json.dumps({'route_id': 'g', 'event_id': event_id, 'index': index, 'refused': refused,
                           'occurred_at': '2026-10-23T01:00:00Z'}).encode()
        request = urllib.request.Request('http://127.0.0.1:%d/v1/channels/qq/voice' % port, data=body, method='POST',
                                         headers={'Authorization': 'Bearer ' + TOKEN,
                                                  'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=10) as answer:
            return answer.status, json.loads(answer.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture
def server():
    made = []

    def start(channels):
        made.append(ChannelServer(channels, 0))
        return made[-1].server.server_port
    yield start
    for one in made:
        one.close()


RECORD = {'index', 'state', 'seconds', 'text', 'events', 'reason', 'sha256', 'size', 'head', 'media_type', 'model',
          'arrived_at', 'finished_at', 'audio_removed_at', 'shown_pending'}


def gone(store, entry, data):
    """The bytes are deleted and the row keeps only its record of them."""
    assert store.db.artifacts.count_documents({'kind': voice.KIND}) == 0
    assert store.db['artifact_blobs.files'].count_documents({'metadata.kind': voice.KIND}) == 0
    assert set(entry) <= RECORD, set(entry) - RECORD
    assert entry['sha256'] == hashlib.sha256(data).hexdigest() and entry['size'] == len(data)
    assert entry['head'] == data[:44].hex() and entry['finished_at'] and entry['arrived_at']


def settle(store, row_id, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = store.db.messages.find_one({'_id': row_id})
        if row.get('voice') and not voice.unsettled(store, row):
            return row
        time.sleep(0.05)
    raise AssertionError('voice did not settle: %s' % store.db.messages.find_one({'_id': row_id}).get('voice'))


def test_a_napcat_refusal_is_shown_in_the_line_and_nothing_is_stored(store, server, services):
    channels = world(store)
    port = server(channels)
    row_id = line(channels, '5301')
    status, answer = post(port, '5301', refused={'reason': 'gone', 'retcode': 1200, 'message': 'file not found'})
    assert status == 200 and answer == {'status': 'kept', 'state': 'not_fetched'}
    row = store.db.messages.find_one({'_id': row_id})
    assert voice.line_text(row) == '[语音，没拿到：平台上已经没有这条语音了（retcode 1200：file not found）]'
    assert row['text'] == voice.PLACEHOLDER and set(row['voice'][0]) <= RECORD
    assert store.db.artifacts.count_documents({'kind': voice.KIND}) == 0
    assert post(port, '5301', data=mp3())[1] == {'status': 'duplicate', 'state': 'not_fetched'}


def test_unknown_bytes_are_refused_with_words_and_never_stored_but_their_record_is_kept(store, server, services):
    channels = world(store)
    port = server(channels)
    row_id = line(channels, '5302')
    data = b'#!SILK_V3' + bytes(range(60))
    status, answer = post(port, '5302', data=data)
    assert status == 200 and answer['state'] == 'failed'
    [entry] = store.db.messages.find_one({'_id': row_id})['voice']
    gone(store, entry, data)
    assert entry['media_type'] == 'audio/mpeg' and 'audio_removed_at' not in entry, 'never stored, so never removed'
    assert store.db.artifacts.count_documents({}) == store.db.artifacts.count_documents({'kind': {'$ne': 'audio'}})
    assert voice.line_text(store.db.messages.find_one({'_id': row_id})) == \
        '[语音，没转出文字：不是认得的音频格式（按开头的字节看不是 WAV 或 MP3）]'


def test_model_files_missing_make_the_line_say_so(store, server, services):
    services(FakeEngine(ok=False))
    channels = world(store)
    port = server(channels)
    row_id = line(channels, '5303')
    data = wav(seconds=2.0)
    assert post(port, '5303', data=data)[1]['state'] == 'pending'
    row = settle(store, row_id)
    assert voice.line_text(row) == '[语音 2 秒，没转出文字：识别模型不在]'
    gone(store, row['voice'][0], data)


@pytest.mark.parametrize('result, said', [
    ({'speech_seconds': 0, 'pieces': []}, '[语音 2 秒，里面没有人声]'),
    ({'speech_seconds': 1.2, 'pieces': [{'text': '……', 'event': '<|Speech|>'}]}, '[语音 2 秒，有人在说话，但听不出说的什么]'),
    ({'speech_seconds': 1.8, 'pieces': [{'text': 'la la', 'event': '<|BGM|>'}]}, '[语音 2 秒，听着像背景音乐] la la'),
    ({'speech_seconds': 1.8, 'pieces': [{'text': '明天见。', 'lang': '<|zh|>', 'event': '<|Speech|>'}]},
     '[语音 2 秒] 明天见。'),
])
def test_each_transcription_state_reaches_the_line(store, server, services, result, said):
    engine = FakeEngine(result)
    services(engine)
    channels = world(store)
    port = server(channels)
    row_id = line(channels, '5304')
    data = mp3(seconds=2.0)
    post(port, '5304', data=data)
    row = settle(store, row_id)
    assert voice.line_text(row) == said
    [entry] = row['voice']
    assert entry['model'] == voice.MODEL_ID and entry['finished_at'] and entry['seconds'] == pytest.approx(2.0, abs=0.2)
    gone(store, entry, data)
    assert entry['audio_removed_at'] >= entry['finished_at'][:19] and entry['media_type'] == 'audio/mpeg'
    assert engine.calls and abs(engine.calls[0] - 2 * voice.RATE) < 2000, 'the model got 16 kHz samples'


def test_a_decode_error_reaches_the_line(store, server, services):
    services()
    channels = world(store)
    port = server(channels)
    row_id = line(channels, '5305')
    data = b'RIFF\x40\x00\x00\x00WAVE' + b'junk' * 30
    post(port, '5305', data=data)
    row = settle(store, row_id)
    assert voice.line_text(row).startswith('[语音，没转出文字：音频解不开（')
    gone(store, row['voice'][0], data)


def test_two_voices_in_one_line_each_settle_with_their_own_index(store, server, services):
    services(FakeEngine({'speech_seconds': 1, 'pieces': [{'text': '一句'}]}))
    channels = world(store)
    port = server(channels)
    row_id = line(channels, '5306', voices=2)
    post(port, '5306', index=1, refused={'reason': 'gone', 'retcode': 1200, 'message': 'file not found'})
    assert voice.unsettled(store, store.db.messages.find_one({'_id': row_id})), 'the first one is still pending'
    post(port, '5306', index=0, data=wav(seconds=1.0))
    row = settle(store, row_id)
    assert [entry['index'] for entry in row['voice']] == [0, 1]
    assert voice.line_text(row) == '[语音 1 秒] 一句和[语音，没拿到：平台上已经没有这条语音了（retcode 1200：file not found）]'
    assert post(port, '5306', index=2, data=wav())[0] == 400


def test_the_turn_waits_ten_seconds_in_all_shows_pending_then_the_words(store, server, services, monkeypatch):
    gate = threading.Event()
    services(FakeEngine(gate=gate))
    channels = world(store)
    port = server(channels)
    first, second = line(channels, '5307'), line(channels, '5308')
    post(port, '5307', data=wav(seconds=1.0))
    post(port, '5308', data=wav(seconds=1.0))
    event = store.db.messages.find_one({'_id': second})['event']
    started = time.monotonic()
    waited, still = voice.await_turn(store, event, timeout=0.6)
    took = time.monotonic() - started
    assert 0.55 <= took < 1.1, 'one wait for the whole turn, not one per voice: %.2f s' % took
    assert set(still) == {first, second}
    row = store.db.messages.find_one({'_id': first})
    assert voice.line_text(row) == '[语音 1 秒，正在转写，转完字会补在这一行]'
    assert '正在转写' in People(store).transcript(store.db.scenes.find_one({'_id': SCENE}), row)
    gate.set()
    waited, still = voice.await_turn(store, event, timeout=5)
    assert still == [] and waited < 4
    assert voice.line_text(store.db.messages.find_one({'_id': first})) == '[语音 1 秒] 你好'


def test_a_voice_line_waits_out_of_her_conversation_and_enters_with_its_words(store, server, services):
    gate = threading.Event()
    service = services(FakeEngine(gate=gate), wait_seconds=0.4)
    projected = []
    voice.attach(lambda row_id, released: projected.append((row_id, released)))
    channels = world(store)
    port = server(channels)
    held = line(channels, '5309')
    assert voice.holds_projection(store, store.db.messages.find_one({'_id': held})), 'expected before any post'
    service.hold(held)
    post(port, '5309', data=wav())
    deadline = time.monotonic() + 3
    while not projected and time.monotonic() < deadline:
        time.sleep(0.05)
    assert projected == [(held, True)], 'the wait ran out: it enters with whatever state it has'
    voice.mark_shown(store, held)
    gate.set()
    row = settle(store, held)
    assert voice.shown_pending(row)
    deadline = time.monotonic() + 3
    while len(projected) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert projected[1] == (held, False), 'settled: it comes once more with its words'
    assert not voice.holds_projection(store, row)


def test_the_bytes_stay_while_pending_and_no_sweep_takes_them_then_go_once_the_text_is_out(store, server, services):
    gate = threading.Event()
    services(FakeEngine(gate=gate))
    channels = world(store)
    port = server(channels)
    row_id = line(channels, '5310')
    data = wav()
    post(port, '5310', data=data)
    [entry] = store.db.messages.find_one({'_id': row_id})['voice']
    assert entry['state'] == 'pending' and store.db.artifacts.find_one({'_id': entry['artifact_id'], 'kind': 'audio'})
    later = datetime.now(timezone.utc) + timedelta(days=30)
    assert media_life.sweep(store, now=later)['bytes'] == 0, 'a pending voice keeps its bytes, however old'
    assert store.db.artifacts.find_one({'_id': entry['artifact_id']})
    gate.set()
    row = settle(store, row_id)
    gone(store, row['voice'][0], data)
    assert voice.line_text(row) == '[语音 1 秒] 你好'


def test_a_restart_queues_the_voices_whose_bytes_came_and_were_not_transcribed(store, server, services):
    channels = world(store)
    row_id = line(channels, '5311')
    voice.receive(store, 'qq', {'route_id': 'g', 'event_id': '5311', 'index': 0,
                                'occurred_at': '2026-10-23T01:00:00Z'}, wav(), 'audio/wav', service=None)
    assert store.db.messages.find_one({'_id': row_id})['voice'][0]['state'] == 'pending'
    services()
    row = settle(store, row_id)
    assert voice.line_text(row) == '[语音 1 秒] 你好'
    gone(store, row['voice'][0], wav())


def test_a_start_deletes_bytes_left_behind_by_a_settled_voice(store, services):
    channels = world(store)
    row_id = line(channels, '5314')
    voice.receive(store, 'qq', {'route_id': 'g', 'event_id': '5314', 'index': 0,
                                'occurred_at': '2026-10-23T01:00:00Z'}, wav(), 'audio/wav', service=None)
    voice._change(store, row_id, 0, {'state': voice.TRANSCRIBED, 'text': '早', 'finished_at': voice.now()})
    assert store.db.artifacts.count_documents({'kind': voice.KIND}) == 1
    services()
    deadline = time.monotonic() + 5
    while store.db.artifacts.count_documents({'kind': voice.KIND}) and time.monotonic() < deadline:
        time.sleep(0.05)
    [entry] = store.db.messages.find_one({'_id': row_id})['voice']
    assert store.db.artifacts.count_documents({'kind': voice.KIND}) == 0
    assert entry['audio_removed_at'] and 'artifact_id' not in entry and entry['text'] == '早'


def test_the_model_gives_way_when_idle(store, services):
    world(store)
    engine = FakeEngine()
    service = services(engine, idle_seconds=0.2)
    engine.is_loaded, service.last_voice = True, time.monotonic()
    deadline = time.monotonic() + 8
    while engine.is_loaded and time.monotonic() < deadline:
        time.sleep(0.1)
    assert engine.released >= 1 and not engine.is_loaded


def test_her_readings_of_the_line_show_the_words(store, server, services):
    services(FakeEngine({'speech_seconds': 1, 'pieces': [{'text': '下周去爬山'}]}))
    channels = world(store)
    port = server(channels)
    row_id = line(channels, '5312')
    from asuna.memory import MemoryService
    MemoryService(store).chunk(SCENE)
    assert not store.db.memory_units.find_one({'source_event_ids': row_id}), 'not chunked while still on its way'
    post(port, '5312', data=wav())
    row = settle(store, row_id)
    scene = store.db.scenes.find_one({'_id': SCENE})
    assert '[语音 1 秒] 下周去爬山' in People(store).transcript(scene, row)
    MemoryService(store).chunk(SCENE)
    chunk = store.db.memory_units.find_one({'source_event_ids': row_id})
    assert chunk and chunk['body_markdown'] == '[语音 1 秒] 下周去爬山', 'recall reads the words'
    from asuna.history_query import search_messages
    hits = search_messages(store, {**scene, 'scene_id': SCENE}, '爬山')['hits']
    assert [hit['text'] for hit in hits] == ['[语音 1 秒] 下周去爬山']
    from asuna.vision import media_note
    assert media_note(row, store.config) is None, 'a voice read as words is no placeholder in the media note'


def test_voice_lines_from_an_adapter_without_voice_in_read_as_today(store):
    channels = world(store, declare=False)
    row_id = line(channels, '5313')
    row = store.db.messages.find_one({'_id': row_id})
    assert not voice.unsettled(store, row) and voice.line_text(row, store) == voice.PLACEHOLDER


# ---- the real model ---------------------------------------------------------------------------------------------
def _model_folder():
    """The deployment's model folder; a worktree under a checkout's .runtime also looks in that .runtime."""
    for base in (DATA, *([ROOT.parent] if ROOT.parent.name == '.runtime' else [])):
        folder = Path(base) / 'models' / voice.MODEL_ID
        if all((folder / name).is_file() for name in voice.MODEL_FILES):
            return folder
    return None


def test_the_real_model_transcribes_its_own_sample_clips_and_finds_no_voice_in_near_silence():
    folder = _model_folder()
    clips = folder / 'test_wavs' if folder else None
    if not folder or not (clips / 'zh.wav').is_file() or not (clips / 'en.wav').is_file():
        pytest.skip('UNCHECKED, not passed: no SenseVoice model with its test_wavs/zh.wav and en.wav under %s'
                    % (DATA / 'models' / voice.MODEL_ID))
    pytest.importorskip('sherpa_onnx')
    engine = voice.SenseVoice(folder)
    assert engine.check() == {'ok': True, 'problems': [], 'directory': str(folder)}
    try:
        def run(data):
            samples = voice.pcm16(data, voice.sniff(data))
            return voice.outcome(len(samples) / voice.RATE, engine.transcribe(samples.astype('float32') / 32768.0))
        zh = run((clips / 'zh.wav').read_bytes())
        assert zh['state'] == voice.TRANSCRIBED and 'zh' in zh['lang'] and len(zh['text']) >= 10
        assert any('一' <= ch <= '鿿' for ch in zh['text'])
        en = run((clips / 'en.wav').read_bytes())
        assert en['state'] == voice.TRANSCRIBED and 'en' in en['lang'] and sum(ch.isascii() and ch.isalpha()
                                                                              for ch in en['text']) >= 20
        rng = np.random.default_rng(0)
        noise = (rng.standard_normal(5 * voice.RATE) * 0.002 * 32768).astype('<i2')
        quiet = voice.outcome(5.0, engine.transcribe(noise.astype('float32') / 32768.0))
        assert quiet['state'] == voice.NO_VOICE and voice.words(quiet) == '[语音 5 秒，里面没有人声]'
    finally:
        engine.release()


def test_the_worker_holds_a_voice_line_then_projects_it_with_its_words_and_once_more_if_shown_pending(store, server,
                                                                                                       services):
    from asuna.native_worker import BusinessWorker
    gate = threading.Event()
    services(FakeEngine({'speech_seconds': 1, 'pieces': [{'text': '到了'}]}, gate=gate), wait_seconds=5)
    channels = world(store)
    port = server(channels)
    worker = BusinessWorker()
    worker.app = SimpleNamespace(store=store, config=store.config)
    worker.navigation_ready.set()
    emitted = []
    worker.emit = emitted.append
    worker.channel_input = lambda row: {'session_id': 's', 'binding': {}, 'input': {
        'id': row['_id'], 'text': People(store).transcript(store.db.scenes.find_one({'_id': SCENE}), row)}}
    voice.attach(worker.voice_ready)
    row_id = line(channels, '5320')
    worker.project_input(store.db.messages.find_one({'_id': row_id}))
    assert emitted == [] and row_id in voice.SERVICE.holds, 'held out of her conversation'
    post(port, '5320', data=wav())
    gate.set()
    settle(store, row_id)
    deadline = time.monotonic() + 3
    while not emitted and time.monotonic() < deadline:
        time.sleep(0.05)
    [first] = emitted
    assert first['input']['id'] == row_id and '[语音 1 秒] 到了' in first['input']['text']
    # a line that entered while still being transcribed comes once more, under its own receipt
    other = line(channels, '5321')
    gate.clear()
    post(port, '5321', data=wav())
    worker.project_input(store.db.messages.find_one({'_id': other}), waited=True)
    voice.mark_shown(store, other)
    assert '正在转写' in emitted[-1]['input']['text']
    gate.set()
    settle(store, other)
    deadline = time.monotonic() + 3
    while emitted[-1]['input']['id'] != other + voice.FOLLOW_UP and time.monotonic() < deadline:
        time.sleep(0.05)
    assert emitted[-1]['input']['id'] == other + voice.FOLLOW_UP and '[语音 1 秒] 到了' in emitted[-1]['input']['text']
    assert worker.dispatch('channel_input.ack', {'input_id': other + voice.FOLLOW_UP, 'session_id': 's'}) == \
        {'recorded': True}
    assert store.db.sink_receipts.find_one({'_id': 'native-input:' + other + voice.FOLLOW_UP})['input_id'] == other
