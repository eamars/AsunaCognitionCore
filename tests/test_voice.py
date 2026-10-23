"""Voice messages arrive as text (ADR-093): a voice is posted before its line and transcribed within that request; its
container is recognized by its first bytes and the audio normalized to 16 kHz mono PCM16; the audio is never stored;
the line is stored with its voices settled, and every reading of it shows the same words, never an empty string.

Unit tests use a fake transcriber; one test runs the real model on the model repository's own sample clips when the
model files are present, and skips saying where it looked when they are not."""
import hashlib
import io
import json
import struct
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from asuna import voice
from asuna.channels import Channels, ChannelServer
from asuna.config import DATA, ROOT
from asuna.ingress import persist_input
from asuna.people import People
from test_people import BOT, GROUP, SCENE, setup as people_setup
from test_native_product import envelope as auto_envelope, product  # noqa: F401  (fixture: automatic admission)

np = pytest.importorskip('numpy')
av = pytest.importorskip('av')

TOKEN = 'x' * 24
MEMBERS = {'20002': 'qq:20002', '20003': 'qq:20003'}
RECORD = {'index', 'state', 'seconds', 'text', 'events', 'reason', 'sha256', 'size', 'head', 'media_type', 'model',
          'arrived_at', 'finished_at'}


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
        frame = av.AudioFrame.from_ndarray(pcm(seconds, rate).reshape(1, -1), format='s16', layout='mono')
        frame.sample_rate = rate
        for packet in stream.encode(frame):
            box.mux(packet)
        for packet in stream.encode(None):
            box.mux(packet)
    return out.getvalue()


class FakeEngine:
    """SUBSTITUTE for SenseVoice: answers a canned transcription."""
    model_id = 'fake'
    engine = {'engine': 'fake'}

    def __init__(self, result=None, ok=True):
        self.result = result or {'speech_seconds': 1.0, 'pieces': [{'text': '你好', 'lang': '<|zh|>',
                                                                     'event': '<|Speech|>'}]}
        self.ok, self.calls, self.released, self.is_loaded = ok, [], 0, False

    def check(self):
        return {'ok': self.ok, 'problems': [] if self.ok else ['model.int8.onnx 不在'], 'directory': 'fake-models'}

    def ready(self):
        return self.ok

    def loaded(self):
        return self.is_loaded

    def transcribe(self, samples):
        self.is_loaded = True
        self.calls.append(len(samples))
        return self.result

    def release(self):
        self.released += 1
        self.is_loaded = False


def transcriber(engine=None, **kwargs):
    made = voice.Transcriber(None, engine or FakeEngine(), **kwargs).start()
    assert made.checked.wait(5)
    return made


@pytest.fixture(autouse=True)
def clean():
    voice._outcomes.clear()
    yield
    if voice.TRANSCRIBER is not None:
        voice.TRANSCRIBER.close()
    voice._outcomes.clear()


def recorded(entry, data):
    """What the outcome keeps of the audio: its record, nothing else."""
    assert set(entry) <= RECORD, set(entry) - RECORD
    assert entry['sha256'] == hashlib.sha256(data).hexdigest() and entry['size'] == len(data)
    assert entry['head'] == data[:44].hex() and entry['arrived_at'] and entry['finished_at']


# ---- the container and the samples (no database) -----------------------------------------------------------------
def test_an_unknown_container_is_refused_with_words_before_any_field_is_read():
    for data in (b'#!AMR\n' + bytes(40), b'OggS' + bytes(40), b'#!SILK_V3' + bytes(40), bytes([0xFF, 0xF1, 0x50, 0x80]),
                 b'RIFF\x24\x00\x00\x00AVI ' + bytes(40), b''):
        assert voice.sniff(data) is None, data[:12]
    with pytest.raises(voice.VoiceError) as refused:
        voice.pcm16(b'OggS' + bytes(40), None)
    assert str(refused.value) == voice.UNKNOWN_CONTAINER
    data = b'#!SILK_V3' + bytes(range(60))
    entry = transcriber().transcribe(data, 'audio/mpeg')
    recorded(entry, data)
    assert voice.words(entry) == '[语音，没转出文字：不是认得的音频格式（按开头的字节看不是 WAV 或 MP3）]'


def test_a_wav_with_a_list_chunk_before_data_is_parsed_by_av_and_resampled_to_16k_pcm16():
    data = wav(seconds=1.5, rate=24000)
    assert data.find(b'data') > 36 + 8, 'the data chunk is not at byte 44 here'
    assert voice.sniff(data) == 'audio/wav'
    samples = voice.pcm16(data, 'audio/wav')
    assert samples.dtype == np.int16 and abs(len(samples) - 1.5 * voice.RATE) < 400
    assert int(np.abs(samples).max()) > 4000, 'the tone survived the resampling'
    assert abs(len(voice.pcm16(wav(seconds=0.5, rate=48000, list_chunk=False), 'audio/wav')) - 0.5 * voice.RATE) < 400


def test_an_mp3_is_recognized_by_id3_or_frame_header_and_decoded():
    data = mp3(seconds=1.0)
    assert voice.sniff(data) == 'audio/mpeg'
    assert voice.sniff(bytes([0xFF, 0xFB, 0x90, 0x64]) + bytes(40)) == 'audio/mpeg'
    assert voice.sniff(b'ID3\x04' + bytes(40)) == 'audio/mpeg'
    assert abs(len(voice.pcm16(data, 'audio/mpeg')) - voice.RATE) < 2000


def test_a_decode_error_is_a_failed_voice_with_its_reason():
    broken = b'RIFF\x40\x00\x00\x00WAVE' + b'junk' * 30
    entry = transcriber().transcribe(broken, 'audio/wav')
    recorded(entry, broken)
    assert entry['state'] == voice.FAILED and voice.words(entry).startswith('[语音，没转出文字：音频解不开（')


def test_every_state_has_its_own_words_and_none_is_empty():
    said = {
        voice.TRANSCRIBED: voice.words({'state': 'transcribed', 'seconds': 33.4, 'text': '今天 下雨'}),
        voice.NO_VOICE: voice.words({'state': 'no_voice', 'seconds': 5}),
        voice.NO_WORDS: voice.words({'state': 'no_words', 'seconds': 12}),
        voice.FAILED: voice.words({'state': 'failed', 'seconds': 33, 'reason': voice.MODEL_MISSING}),
        voice.NOT_FETCHED: voice.words({'state': 'not_fetched', 'reason': '平台上已经没有这条语音了'}),
    }
    assert said == {
        'transcribed': '[语音 33 秒] 今天 下雨',
        'no_voice': '[语音 5 秒，里面没有人声]',
        'no_words': '[语音 12 秒，有人在说话，但听不出说的什么]',
        'failed': '[语音 33 秒，没转出文字：识别模型不在]',
        'not_fetched': '[语音，没拿到：平台上已经没有这条语音了]'}
    assert all(voice.words({'state': state}) for state in (*voice.STATES, None))
    assert not any('正在转写' in text for text in said.values())


def test_no_voice_is_the_detectors_verdict_and_no_words_is_speech_without_a_letter():
    assert voice.outcome(5.0, {'speech_seconds': 0, 'pieces': []})['state'] == voice.NO_VOICE
    quiet = voice.outcome(12.0, {'speech_seconds': 3.1, 'pieces': [{'text': '。', 'event': '<|Speech|>'}]})
    assert quiet['state'] == voice.NO_WORDS and quiet['events'] == []
    spoken = voice.outcome(7.2, {'speech_seconds': 6.0, 'pieces': [
        {'text': 'The tribal chieftain called', 'lang': '<|en|>', 'event': '<|Speech|>'},
        {'text': '开放时间早上9点', 'lang': '<|zh|>', 'event': '<|Speech|>'}]})
    assert spoken['state'] == voice.TRANSCRIBED and spoken['text'] == 'The tribal chieftain called 开放时间早上9点'
    assert voice.outcome(3.0, {'speech_seconds': 1.0, 'pieces': [{'text': '3'}]})['state'] == voice.TRANSCRIBED


def test_a_label_other_than_speech_is_named_in_the_line():
    music = voice.outcome(20.0, {'speech_seconds': 9, 'pieces': [{'text': '啦啦啦', 'event': '<|BGM|>'},
                                                                  {'text': '好听', 'event': '<|Speech|>'}]})
    assert music['events'] == ['BGM'] and voice.words(music) == '[语音 20 秒，听着像背景音乐] 啦啦啦好听'
    laugh = voice.outcome(4.0, {'speech_seconds': 2, 'pieces': [{'text': '', 'event': '<|Laughter|>'}]})
    assert voice.words(laugh) == '[语音 4 秒，听着像笑声，听不出说的什么]'
    odd = voice.outcome(4.0, {'speech_seconds': 2, 'pieces': [{'text': '嗯嗯', 'event': '<|Something_New|>'}]})
    assert voice.words(odd) == '[语音 4 秒，听着像别的声音] 嗯嗯'


@pytest.mark.parametrize('result, said', [
    ({'speech_seconds': 0, 'pieces': []}, '[语音 2 秒，里面没有人声]'),
    ({'speech_seconds': 1.2, 'pieces': [{'text': '……', 'event': '<|Speech|>'}]}, '[语音 2 秒，有人在说话，但听不出说的什么]'),
    ({'speech_seconds': 1.8, 'pieces': [{'text': 'la la', 'event': '<|BGM|>'}]}, '[语音 2 秒，听着像背景音乐] la la'),
    ({'speech_seconds': 1.8, 'pieces': [{'text': '明天见。', 'lang': '<|zh|>', 'event': '<|Speech|>'}]},
     '[语音 2 秒] 明天见。'),
])
def test_each_outcome_keeps_only_its_record(result, said):
    engine = FakeEngine(result)
    data = mp3(seconds=2.0)
    entry = transcriber(engine).transcribe(data, 'audio/mpeg')
    recorded(entry, data)
    assert voice.words(entry) == said and entry['model'] == voice.MODEL_ID
    assert entry['seconds'] == pytest.approx(2.0, abs=0.2) and abs(engine.calls[0] - 2 * voice.RATE) < 2000


def test_model_files_missing_or_different_are_named_once_in_the_host_log_and_in_every_voice(tmp_path, capfd):
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
    capfd.readouterr()
    lost = transcriber(FakeEngine(ok=False))
    log = capfd.readouterr().err
    assert log.count('ASUNA_VOICE_MODEL_UNAVAILABLE') == 1 and 'model.int8.onnx 不在' in log
    for _ in range(2):
        assert voice.words(lost.transcribe(wav(seconds=2.0), 'audio/wav')) == '[语音，没转出文字：识别模型不在]'
    assert 'ASUNA_VOICE_MODEL_UNAVAILABLE' not in capfd.readouterr().err, 'one line, at start'


def test_the_model_gives_way_when_idle():
    engine = FakeEngine()
    worker = transcriber(engine, idle_seconds=0.2)
    worker.transcribe(wav(), 'audio/wav')
    assert engine.is_loaded
    deadline = time.monotonic() + 5
    while engine.is_loaded and time.monotonic() < deadline:
        time.sleep(0.05)
    assert engine.released >= 1 and not engine.is_loaded


def test_two_voices_in_one_line_read_in_order():
    text = '[语音（未解析）]和[语音（未解析）]'
    entries = [{'index': 1, 'state': 'no_voice', 'seconds': 2},
               {'index': 0, 'state': 'transcribed', 'seconds': 3, 'text': '你好'}]
    assert voice.read_text(text, entries) == '[语音 3 秒] 你好和[语音 2 秒，里面没有人声]'
    assert voice.read_text(voice.PLACEHOLDER, []) == voice.PLACEHOLDER, 'no voice posted: the line as today'
    assert voice.read_text('只剩文字', [{'index': 0, 'state': 'no_voice', 'seconds': 2}]) == \
        '只剩文字 [语音 2 秒，里面没有人声]', 'a placeholder cut for length: the voice is added at the end'


# ---- the endpoint, the line and her readings (MongoDB) ------------------------------------------------------------
def world(store):
    people_setup(store)
    store.db.scenes.update_one({'_id': SCENE}, {'$set': {'members': list(MEMBERS.values()), 'channel_id': 'qq'}})
    store.config['channels'] = {'qq': {'account_id': BOT, 'token': TOKEN, 'routes': {'g': {
        'scene_id': SCENE, 'target': {'type': 'group', 'id': GROUP},
        'members': {sender: {'person_id': person} for sender, person in MEMBERS.items()}}}}}
    handed = []

    def receive(event):
        handed.append(event)
        row, created = persist_input(store, event, managed=True)
        return {'status': 'accepted' if created else 'duplicate', 'episode_id': row['episode_id']}
    controller = SimpleNamespace(app=SimpleNamespace(store=store, config=store.config,
                                                     evidence=SimpleNamespace(record=lambda *args, **kwargs: None)),
                                 stopping=threading.Event(), reconfiguring=False, ingress_lock=threading.RLock(),
                                 receive=receive, emit=lambda text: None)
    channels = Channels(controller)
    channels.handed = handed                     # the events handed to her queue, as her turn reads them
    return channels


OCCURRED = '2026-10-23T01:00:00Z'


def line(channels, event_id, voices=1, text=None, refused=None, sender='20002', status='accepted'):
    """Post the line after its voices, as the adapter does; `refused`: index -> the adapter's reason."""
    items = [{'type': 'record', 'placeholder': voice.PLACEHOLDER, 'file': 'v%d.amr' % n} for n in range(voices)]
    for index, reason in (refused or {}).items():
        items[index][voice.REFUSED_KEY] = reason
    body = {'route_id': 'g', 'account_id': BOT, 'sender_id': sender, 'event_id': event_id,
            'text': text or '和'.join([voice.PLACEHOLDER] * voices), 'group_id': GROUP, 'mentioned_account_ids': [],
            'raw': {'asuna_media': {'count': voices, 'items': items}} if voices else {}, 'occurred_at': OCCURRED}
    assert channels.receive('qq', body)['status'] == status
    return channels.store.db.messages.find_one({'scene_id': SCENE, 'event.channel.platform_event_id': event_id})


def post(port, event_id, data, index=0, query=None):
    query = query or 'route_id=g&event_id=%s&index=%d&occurred_at=2026-10-23T01%%3A00%%3A00Z' % (event_id, index)
    request = urllib.request.Request('http://127.0.0.1:%d/v1/channels/qq/voice?%s' % (port, query), data=data,
                                     method='POST', headers={'Authorization': 'Bearer ' + TOKEN,
                                                             'Content-Type': 'audio/mpeg'})
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:
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


def test_a_voice_is_settled_in_its_request_and_its_line_is_stored_as_it_reads_with_no_audio(store, server):
    engine = FakeEngine({'speech_seconds': 1, 'pieces': [{'text': '下周去爬山'}]})
    transcriber(engine)
    channels = world(store)
    port = server(channels)
    data = wav()
    blobs = store.db['artifact_blobs.files'].count_documents({})
    assert post(port, '5301', data) == (200, {'status': 'settled', 'state': 'transcribed', 'seconds': 1.0})
    assert post(port, '5301', data) == (200, {'status': 'duplicate', 'state': 'transcribed'})
    assert len(engine.calls) == 1, 'the same voice posted again is not transcribed again'
    row = line(channels, '5301')
    [entry] = row['event']['voice']
    recorded(entry, data)
    said = '[语音 1 秒] 下周去爬山'
    assert entry['index'] == 0 and row['text'] == said and row['event']['received_text'] == voice.PLACEHOLDER
    assert channels.handed[-1]['text'] == said, 'her turn reads the words'
    assert store.db.artifacts.count_documents({'kind': 'audio'}) == 0
    assert store.db['artifact_blobs.files'].count_documents({}) == blobs, 'the audio is never stored'
    assert store.db.audit_events.find_one({'payload.document._id': row['_id'], 'type': 'state.commit',
                                           'payload.document.text': said,
                                           'payload.document.event.voice.0.state': 'transcribed'}), \
        'the words are in the row as it was committed'


def test_a_line_posted_again_is_the_same_line_whatever_its_voice_settles_to(store, server):
    transcriber(FakeEngine({'speech_seconds': 1, 'pieces': [{'text': '第一次'}]}))
    channels = world(store)
    post(server(channels), '5308', wav())
    first = line(channels, '5308')
    voice._outcomes.clear()                       # the outcome expired, or the worker restarted, before the re-post
    again = line(channels, '5308', refused={0: {'reason': 'gone', 'retcode': 1200, 'message': 'file not found'}},
                 status='duplicate')
    assert again['_id'] == first['_id'] and again['text'] == '[语音 1 秒] 第一次', 'the first stored reading stands'


def test_the_adapters_reason_is_shown_in_words_and_its_own_answer_kept_for_the_record(store):
    channels = world(store)
    answer = {'reason': 'gone', 'retcode': 1200, 'message': 'file not found'}
    row = line(channels, '5302', refused={0: answer})
    assert row['text'] == '[语音，没拿到：平台上已经没有这条语音了]'
    assert row['event']['raw']['asuna_media']['items'][0][voice.REFUSED_KEY] == answer
    row = line(channels, '5303', refused={0: {'reason': 'host', 'message': '503 HOST_TEMPORARILY_UNAVAILABLE'}})
    assert row['text'] == '[语音，没转出文字：交给本机识别时出了错]', 'the audio was fetched: not "没拿到"'
    assert row['event']['voice'][0]['state'] == voice.FAILED
    row = line(channels, '5309', refused={0: {'reason': 'timeout', 'message': 'get_record gave no answer in 10 s'}})
    assert row['text'] == '[语音，没拿到：向平台取音频超时了]'


def test_two_voices_in_one_line_each_carry_their_own_outcome(store, server):
    transcriber(FakeEngine({'speech_seconds': 1, 'pieces': [{'text': '一句'}]}))
    channels = world(store)
    port = server(channels)
    assert post(port, '5304', wav(), index=0)[1]['state'] == 'transcribed'
    row = line(channels, '5304', voices=2, refused={1: {'reason': 'timeout', 'message': 'get_record gave no answer'}})
    assert [entry['index'] for entry in row['event']['voice']] == [0, 1]
    assert row['text'] == '[语音 1 秒] 一句和[语音，没拿到：向平台取音频超时了]'


def test_the_endpoint_refuses_what_is_out_of_shape(store, server):
    transcriber()
    port = server(world(store))
    assert post(port, '5305', b'')[0] == 400
    assert post(port, '5305', wav(), index=99)[1]['error'].startswith('VOICE_INDEX_INVALID')
    assert post(port, '5305', wav(), query='event_id=1&index=0')[1]['error'].startswith('VOICE_ROUTE_ID_INVALID')
    assert post(port, '5305', wav(), query='route_id=g&event_id=1&index=0&x=1')[1]['error'].startswith(
        'VOICE_FIELD_DENIED')


def test_a_refused_post_is_answered_and_its_audio_never_used(store, server):
    """Who may post a voice and what it is about are settled before its audio is used; a refused post's body is read
    and dropped, so the client gets the refusal, not a reset connection."""
    channels = world(store)
    port = server(channels)
    engine = FakeEngine()
    transcriber(engine)
    big = wav() + bytes(8 * 1024 * 1024)
    for _ in range(3):
        status, answer = post(port, '5307', big, index=99)
        assert status == 400 and answer['error'].startswith('VOICE_INDEX_INVALID')
    channels.authenticate = lambda channel_id, authorization: (None, 'g')      # as a route key of route g
    status, answer = post(port, '5307', big)
    assert (status, answer['error']) == (403, 'ROUTE_KEY_ENDPOINT_DENIED')
    assert engine.calls == [] and voice._outcomes == {}


def test_a_line_from_a_channel_without_voice_in_reads_as_today(store):
    row = line(world(store), '5306')
    assert 'voice' not in row['event'] and 'received_text' not in row['event'] and row['text'] == voice.PLACEHOLDER


def test_a_voice_in_channel_never_shows_the_bare_placeholder(store):
    from asuna import capabilities
    capabilities.declared(store, 'qq', ['image', voice.CAPABILITY])
    row = line(world(store), '5310', voices=2)
    assert row['text'] == '[语音，没拿到：这段语音没随消息一起送来]和[语音，没拿到：这段语音没随消息一起送来]'
    assert [entry['state'] for entry in row['event']['voice']] == [voice.NOT_FETCHED] * 2


def test_a_voice_on_a_route_its_own_line_admits(product):
    """Automatic admission: the route of a new chat exists only once its first line arrives; a voice posted before it
    is still found by what the adapter posted."""
    running = transcriber(FakeEngine({'speech_seconds': 1, 'pieces': [{'text': '你好呀'}]}))
    asked = {'route_id': 'auto-dm-11110000', 'event_id': 'v-1', 'index': '0'}
    assert 'auto-dm-11110000' not in product.config['channels']['qq']['routes']
    assert voice.receive('qq', asked, wav(), 'audio/wav', running)['state'] == 'transcribed'
    product.channel.receive('qq', auto_envelope(mid='v-1', text=voice.PLACEHOLDER, raw={'asuna_media': {
        'count': 1, 'items': [{'type': 'record', 'placeholder': voice.PLACEHOLDER, 'file': 'v.amr'}]}}))
    row = product.store.db.messages.find_one({'event.channel.platform_event_id': 'v-1'})
    assert row['text'] == '[语音 1 秒] 你好呀' and row['event']['received_text'] == voice.PLACEHOLDER


def test_a_voice_that_says_her_name_calls_her_as_typed_words_do(store, server):
    channels = world(store)
    name = next(name for name in People(store).self_names if len(name) >= 2)
    transcriber(FakeEngine({'speech_seconds': 1, 'pieces': [{'text': name + '你在吗'}]}))
    post(server(channels), '5311', wav())
    spoken = line(channels, '5311')['event']['group_context']
    typed = line(channels, '5312', voices=0, text=name + '你在吗')['event']['group_context']
    assert (typed.get('wake_reason') or typed.get('resting')) == 'name_called'
    assert (spoken.get('wake_reason') or spoken.get('resting')) == 'name_called'


def test_the_copied_words_check_sees_a_voices_words(store, server):
    from datetime import datetime, timezone
    from asuna import notes
    channels = world(store)
    said = '我们下周六早上八点在山脚下的停车场集合然后一起去爬山记得带水'
    transcriber(FakeEngine({'speech_seconds': 1, 'pieces': [{'text': said}]}))
    post(server(channels), '5313', wav())
    line(channels, '5313')
    match = notes.borrowed(store, SCENE, said, datetime.now(timezone.utc))
    assert match and match['author'] == 'qq:20002'


def test_every_reading_of_the_line_shows_the_same_words(store, server):
    transcriber(FakeEngine({'speech_seconds': 1, 'pieces': [{'text': '下周去爬山'}]}))
    channels = world(store)
    port = server(channels)
    post(port, '5307', wav())
    row = line(channels, '5307')
    said = '[语音 1 秒] 下周去爬山'
    scene = store.db.scenes.find_one({'_id': SCENE})
    people = People(store)
    assert '  ' + said in people.transcript(scene, row).split('\n')
    assert people.line_of(scene, 'ep-none', '9999')[1].endswith(said), 'quotes and the recent lines'
    from asuna import notices
    text, _, _ = notices.fill(store, scene, {'line': {'message_id': '5307'}}, '回应了{line}')
    assert said in text
    from asuna.memory import MemoryService
    MemoryService(store).chunk(SCENE)
    assert store.db.memory_units.find_one({'source_event_ids': row['_id']})['body_markdown'] == said, 'recall'
    from asuna.history_query import search_messages
    hits = search_messages(store, {**scene, 'scene_id': SCENE}, '爬山')['hits']
    assert [hit['text'] for hit in hits] == [said]
    from asuna.vision import media_note
    assert media_note(row, store.config) is None, 'a voice read as words is no placeholder in the media note'
    from asuna.attend import recent
    assert any(said in text for text in recent(store, scene, row['scene_seq'])[0]), 'the relevance gate'


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
    worker = transcriber(engine)
    assert engine.ready()
    zh = worker.transcribe((clips / 'zh.wav').read_bytes(), 'audio/wav')
    assert zh['state'] == voice.TRANSCRIBED and len(zh['text']) >= 10
    assert any('一' <= ch <= '鿿' for ch in zh['text'])
    en = worker.transcribe((clips / 'en.wav').read_bytes(), 'audio/wav')
    assert en['state'] == voice.TRANSCRIBED and sum(ch.isascii() and ch.isalpha() for ch in en['text']) >= 20
    rng = np.random.default_rng(0)
    noise = (rng.standard_normal(5 * voice.RATE) * 0.002 * 32768).astype('<i2')
    buffer = io.BytesIO()
    with av.open(buffer, mode='w', format='wav') as box:
        stream = box.add_stream('pcm_s16le', rate=voice.RATE, layout='mono')
        frame = av.AudioFrame.from_ndarray(noise.reshape(1, -1), format='s16', layout='mono')
        frame.sample_rate = voice.RATE
        for packet in stream.encode(frame):
            box.mux(packet)
        for packet in stream.encode(None):
            box.mux(packet)
    quiet = worker.transcribe(buffer.getvalue(), 'audio/wav')
    assert quiet['state'] == voice.NO_VOICE and voice.words(quiet) == '[语音 5 秒，里面没有人声]'
