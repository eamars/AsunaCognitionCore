"""Voice messages arrive as text (ADR-093): a voice is posted before its line and transcribed within that request; its
container is recognized by its first bytes and the audio normalized to 16 kHz mono PCM16; the audio is never stored;
the line is stored with its voices settled, and every reading of it shows the same words, never an empty string.

Unit tests use a fake transcriber; one test runs the real model on the model repository's own sample clips when the
model files are present, and skips saying where it looked when they are not."""
import hashlib
import io
import struct
from pathlib import Path

import pytest

from asuna import voice
from asuna.config import DATA, ROOT

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
    made = voice.Transcriber(None, engine or FakeEngine(), in_process=True, **kwargs).start()
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
        voice.FAILED: voice.words({'state': 'failed', 'seconds': 33, 'reason': voice.TIMED_OUT}),
        voice.NOT_FETCHED: voice.words({'state': 'not_fetched', 'reason': '平台上已经没有这条语音了'}),
        voice.NOT_TRANSCRIBED: voice.words({'state': 'not_transcribed', 'reason': voice.VOICE_OFF}),
    }
    assert said == {
        'transcribed': '[语音 33 秒] 今天 下雨',
        'no_voice': '[语音 5 秒，里面没有人声]',
        'no_words': '[语音 12 秒，有人在说话，但听不出说的什么]',
        'failed': '[语音 33 秒，没转出文字：识别超时了]',
        'not_fetched': '[语音，没拿到：平台上已经没有这条语音了]',
        'not_transcribed': '[语音，没转出文字：语音转写关着]'}
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
        entry = lost.transcribe(wav(seconds=2.0), 'audio/wav')
        # The machine's setup, not this voice: its own state, never a failure.
        assert entry['state'] == voice.NOT_TRANSCRIBED
        assert voice.words(entry) == '[语音，没转出文字：这台机器上的语音识别没装好]'
    assert 'ASUNA_VOICE_MODEL_UNAVAILABLE' not in capfd.readouterr().err, 'one line, at start'


def test_voice_to_text_off_loads_nothing_and_says_so():
    engine = FakeEngine()
    off = transcriber(engine, enabled=False)
    entry = off.transcribe(wav(), 'audio/wav')
    assert entry['state'] == voice.NOT_TRANSCRIBED and voice.words(entry) == '[语音，没转出文字：语音转写关着]'
    assert engine.calls == [] and off.child is None


class FakeChild:
    """SUBSTITUTE for media_children.Child: raises or answers what it is given, records each call."""

    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []

    def call(self, header, payload=b'', deadline=60, budget=None):
        self.calls.append((header, len(payload), deadline, budget))
        made = self.outcomes.pop(0)
        if isinstance(made, Exception):
            raise made
        return made, b''

    def close(self):
        pass


def test_the_childs_failures_have_their_own_words_and_states():
    from asuna import media_children
    answer = {'ok': True, 'samples': 32000, 'result': {'speech_seconds': 1.0, 'pieces': [{'text': '你好'}]},
              'stages': {'decode_s': 0.01, 'transcribe_s': 0.2}, 'times': {'waited_s': 0.0, 'started_s': 0.0, 'tries': 1}}
    cases = [(media_children.Timeout(), voice.FAILED, '[语音，没转出文字：识别超时了]'),
             (media_children.Died('exited'), voice.FAILED, '[语音，没转出文字：识别程序出错了]'),
             (media_children.StartFailed('x'), voice.NOT_TRANSCRIBED, '[语音，没转出文字：这台机器上的语音识别没能启动]'),
             (media_children.JobError('音频解不开（x）'), voice.FAILED, '[语音，没转出文字：音频解不开（x）]'),
             (media_children.JobError('识别程序出错（KeyError）', program=True, trace='Traceback'), voice.FAILED,
              '[语音，没转出文字：识别程序出错（KeyError）]'),
             (answer, voice.TRANSCRIBED, '[语音 2 秒] 你好')]
    for made, state, said in cases:
        worker = voice.Transcriber(None, FakeEngine(), child=FakeChild(made)).start()
        assert worker.checked.wait(5)
        entry = worker.transcribe(wav(seconds=2.0), 'audio/wav')
        assert (entry['state'], voice.words(entry)) == (state, said), made
        assert worker.child.calls[0][0] == {'container': 'audio/wav'}
        assert worker.child.calls[0][2:] == (media_children.VOICE_DEADLINE, media_children.VOICE_BUDGET)
        worker.close()


def test_two_voices_in_one_line_read_in_order():
    text = '[语音（未解析）]和[语音（未解析）]'
    entries = [{'index': 1, 'state': 'no_voice', 'seconds': 2},
               {'index': 0, 'state': 'transcribed', 'seconds': 3, 'text': '你好'}]
    assert voice.read_text(text, entries) == '[语音 3 秒] 你好和[语音 2 秒，里面没有人声]'
    assert voice.read_text(voice.PLACEHOLDER, []) == voice.PLACEHOLDER, 'no voice posted: the line as today'
    assert voice.read_text('只剩文字', [{'index': 0, 'state': 'no_voice', 'seconds': 2}]) == \
        '只剩文字 [语音 2 秒，里面没有人声]', 'a placeholder cut for length: the voice is added at the end'


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


def test_a_voice_cut_off_by_the_host_stopping_is_the_host_away_not_a_failure():
    from asuna import media_children
    worker = voice.Transcriber(None, FakeEngine(), child=FakeChild(media_children.Closed())).start()
    assert worker.checked.wait(5)
    fields = {'route_id': 'r1', 'event_id': 'e-stop', 'index': '0'}
    with pytest.raises(RuntimeError) as away:
        voice.receive('qq', fields, wav(), 'audio/wav', transcriber=worker)
    assert str(away.value) == 'HOST_STOPPING' and not voice._outcomes, 'no outcome kept: the voice is posted again'
    worker.close()
