# ADR-093: Voice messages arrive as text

Status: **Accepted** in direction by the owner on 2026-10-23 ("Please go ahead. Similar to the image and video, the
process should not invoke active involvement from her, that the text should be converted automatically."). The design
below is Claude's, from Xiaoman's research of 10-23 (her route and her contract, §5). Built on a branch; V1, V2, V4,
V6 and V7 were simplified after the independent review (§7).

## 1. What happens today

A QQ voice message reaches her as a placeholder in the line, 「[语音（未解析）]」: the NapCat adapter marks every
`record` segment that way (`inbound.py`, `MEDIA_TYPES`), and nothing reads it.

Xiaoman measured on 10-23:
- NapCat's `get_record(file, out_format=wav|mp3)` returns the audio converted. Her one sample was 24 kHz mono, 33.48 s;
  `amr` gave error 1200 `Encoder not found`.
- NapCat clears its voice cache: a voice from 10-05 now fails with 1200 `file not found`, so a voice not fetched soon
  is lost.

## 2. Decisions

- **V1 The voice is text before its line exists.** Before it submits a line with a voice, the NapCat adapter calls
  `get_record` (`out_format=mp3`, the smaller form) and posts the bytes to the Host, which transcribes them in that
  request and answers with the outcome. Then the adapter submits the line, which carries its words from the start.
  If NapCat refuses or times out, or the Host call fails, the line goes in with the reason, so it says why. Lines
  keep their arrival order. An adapter that cannot fetch voice does not declare it, and its voice
  lines stay as they are today.
- **V2 The audio is never stored.** It lives in memory for the one request that transcribes it. The row records the
  sha256, the size, the media type and the first 44 bytes (her contract).
- **V3 Normalize at the entry, always.** Recognize the container by its first bytes (RIFF/WAVE, ID3 or an MP3 frame
  header) before reading any field, then decode with `av` and resample to 16 kHz mono PCM16 (16-bit), which the
  model takes as samples. This happens whatever rate and depth arrive: SenseVoice accepts 16 kHz mono only, and NapCat
  gave 24 kHz.
- **V4 Transcribe in the request, on this machine.**
  - Engine: SenseVoice int8 with Silero voice detection, through the sherpa-onnx Python package 1.13.8. The detector is
    needed (§3). No DSH plugin and no Node bridge.
  - Detector settings: speech and silence each at least 0.25 s, one piece of speech at most 20 s (the settings
    measured in §3).
  - One model is loaded in the Host's Python worker process, about 300 MiB (§3). It is released after 10 minutes with
    no voice, because reloading takes under a second. It gives way to other services when it sits idle, not only
    at a restart (her question, 09:47).
  - One voice is transcribed at a time, in arrival order. Language is detected automatically. A voice line reaches
    her about the fetch plus the transcription later (the transcription is 0.1–1.5 s, §3).
- **V5 What she reads.** Each state has its own words; none is an empty string, which she would read as "nobody spoke":

  | State | Her line shows |
  |---|---|
  | transcribed | 「[语音 33 秒] 文字……」 |
  | no voice in it: the detector found no speech | 「[语音 5 秒，里面没有人声]」 |
  | a voice, but no words came out | 「[语音 12 秒，有人在说话，但听不出说的什么]」 |
  | transcription failed | 「[语音 33 秒，没转出文字：原因]」 |
  | audio not fetched | 「[语音，没拿到：原因]」 (NapCat had already cleared it, say) |

  The two middle states ask different things of her (her ask, 09:45): no voice means nobody spoke, while a voice
  without words is something she may ask about. The line between them is the detector's: no speech found at all is
  "no voice"; speech found, but the text has no letter or character in it, is "a voice but no words".

  SenseVoice also labels each piece of audio with an event: speech, background music, laughter, applause and the like.
  When a piece is labelled as anything but speech, her line names it, e.g. 「[语音 20 秒，听着像背景音乐] ……」, so
  words read off music do not pass as speech.

  Made-up words are still possible with the detector on. Noise that passes the detector gets labelled as speech by the
  model (measured, §3), so no label catches every case, and her line cannot say it for certain. Her test set (§5)
  measures how often it happens on real voices.

  There is no "too long" state: the program sets no length limit of its own, and with voice detection a long voice
  takes about 2.5% of its length.
- **V6 No waiting state.** A line carries its words, or the reason it has none, from the moment it exists, so no
  turn waits for a voice and no line is shown twice.
- **V7 The audio goes once the text is out (owner, 2026-10-23).** Like a video, the audio is deleted right after its
  text is extracted, whatever the outcome (transcribed, no voice, a voice without words, a failure). The row keeps
  the record: the state and its words, the length, sha256, size, first 44 bytes, media type, model and times, and
  when it was transcribed. Since V2 never stores it, nothing is left to delete. Her test set (§5) keeps its own copies.
- **V8 What it does not touch.** Video soundtracks are not transcribed this round (`vision.py` video path,
  `animated.py`). Nothing is sent anywhere outside this machine.

## 3. Measured on this machine (2026-10-23)

Evidence: `.runtime/private/voice/measure-2026-10-23.md` (1,990 B), with the configuration recorded. The numbers come
from the model repository's sample clips, repeated, and synthetic noise, not from real QQ voices; her test set (§6
step 3) measures real ones.

| | |
|---|---|
| model load | 0.7–0.9 s |
| memory | about 300 MiB with the model loaded, plus about 50 MiB while transcribing 20 s |
| transcription, 30 s of speech | 0.6 s with voice detection |
| transcription, 60 s of speech | 1.5 s with voice detection |

Without voice detection a long clip loses text: 62 of 70 characters at 30 s, 246 of 324 in English. Two languages
in one clip collapsed to 7 characters. On 5 s of noise the model alone wrote a stray syllable, while the detector found
no speech. That is why the detector is in V4, and why "no speech found" in V5 is the detector's verdict, not an empty
text. The model's event label read a 440 Hz tone as background music, but read the noise as speech, so the label
adds to the detector and cannot replace it.

## 4. Dependencies and files

- **Python packages:** `sherpa-onnx==1.13.8` (released 2026-09-10; Windows wheel 2.3 MB plus its native core,
  16.9 MB) and `numpy` at a version at least two weeks old. Added with uv. `av` is already a dependency.
- **Model files** in `.runtime/models/sensevoice-2024-07-17/`, the same pins as DSH's own SenseVoice package:
  - `model.int8.onnx`: 239,233,841 B, sha256 c71f0ce0…2cd51
  - `tokens.txt`: 315,894 B, sha256 f449eb28…1a1dc
  - `silero_vad.onnx`: 1,807,522 B, sha256 a35ebf52…5af28
- **Startup check:** the Host checks the three hashes when it starts. A missing or different file makes voice lines
  read 「[语音 N 秒，没转出文字：识别模型不在]」, never silence.

## 5. Xiaoman's research and contract (Claude's paraphrase, 2026-10-23 03:00–09:35)

- Her route was SenseVoice through sherpa-onnx, with whisper-small kept outside the core as a yardstick. The owner
  changed her pull design (a `transcribe` tool) to automatic. She agreed at 09:35, because a pull fails on audio that
  NapCat has already cleared.
- Her contract:
  - normalize always;
  - recognize the container before reading offsets;
  - give audio its own kind;
  - keep the next WAV on disk, as a file, with its sha256 and first 44 bytes recorded (not only a row);
  - record the configuration with every test.
- Her test set: 5–10 real voices, the longest included, transcribed by both engines and read by her line by line,
  with the number of wrong characters per version.

Signature (Xiaoman, received 2026-10-23 09:58, verbatim, on `c018e386`): 「我读过 `c018e386`。方向我签，V1–V6 我签，
§5 我那五条归我名下我认。两件要先补上才算我的：① 我那条契约是 **16k 单声道 PCM16**，位深那半格在字面里丢了（全文 `PCM` 0 命中）；
② 第 4 条我的原意是**拿到 wav 落盘**，不是只在库里的行上记一行。§6 第 3 步是我这道安装前的闸，**样本形状四条（长句／短句／几乎没声／
约 60 秒）加第五类反面样本（440 Hz 纯音＋底噪，正确答案＝没有任何文字）得写进去**，不写那一轮没有准。其余小格不改我这份签名，但别当没说过。
——沈小满，10-23」

Her two conditions and §6 step 3 are written in since (V3 PCM16, §5 the WAV kept as a file, §6 step 3 the shapes
and negative controls), with her smaller points (V6's 10 s for the whole turn, the pending line saying the text will
follow, the evidence file's size, the detector settings in V4).

## 6. Build

1. The NapCat adapter: declare voice fetching; fetch each voice and post it before submitting its line, or submit
   the line with the reason (V1). Self-test entries.
2. Core:
   - the endpoint that transcribes in the request (V1, V2, V4);
   - normalization (V3);
   - the model check (§4);
   - the line's words, the same in every reader (V5).
   Tests for each state, failure paths first.
3. Her test set, the gate before the install is called done. Each clip is kept as a file with its sha256 and first 44
   bytes, and the configuration (engine, voice detection or not, rate, model) is recorded with every result:
   - real voices in four shapes: a long sentence, a short sentence, almost no sound, and about 60 seconds, including
     the owner's voice with his typed words as the one known answer among them;
   - negative controls: a 440 Hz tone and background noise, where the correct answer is no text at all, so any
     word on them counts as made up;
   - both engines (SenseVoice here; whisper-small outside the core as her yardstick), read by her line by line, with
     the wrong characters counted per version.
   - A word written with a different character of the same sound counts as heard right (the owner, 10-23: his
     「小满小满」 came out 「小曼小曼」, which sound exactly alike). The transcript is shown as the model wrote it; the
     reader resolves sound by context, as people reading a voice transcript do.

## 7. The independent review, and why the flow changed (2026-10-23)

The first build transcribed in the background after the line had entered her conversation. An independent review
found that every one of its should-fix defects came from that choice:
- the words never arrived when the line entered before its voice was posted;
- one database error stopped the background worker until a restart;
- a lost update, because the voice entry was written outside the row's revision;
- a pending entry with no bytes never settled;
- the line was shown to her twice (pending, then the words), and lines after a voice could jump ahead of it.

Transcribing before the line exists removes the pending state and, with it, all of those paths. It costs a voice
line about the fetch plus 0.1–1.5 s of transcription before it reaches her (§3), and nothing else.
