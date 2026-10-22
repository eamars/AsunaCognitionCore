# ADR-093: Voice messages arrive as text

Status: **Accepted** in direction by the owner on 2026-10-23 ("Please go ahead. Similar to the image and video, the
process should not invoke active involvement from her, that the text should be converted automatically."). The design
below is Claude's, from Xiaoman's research of 10-23 (her route and her contract, §5). To her for reading. Not built.

## 1. What happens today

A QQ voice message reaches her as a placeholder in the line, 「[语音（未解析）]」: the NapCat adapter marks every
`record` segment that way (`inbound.py`, `MEDIA_TYPES`), and nothing reads it.

Xiaoman measured on 10-23:
- NapCat's `get_record(file, out_format=wav|mp3)` returns the audio converted. Her one sample was 24 kHz mono, 33.48 s;
  `amr` gave error 1200 `Encoder not found`.
- NapCat clears its voice cache: a voice from 10-05 now fails with 1200 `file not found`, so a voice not fetched soon
  is lost.

## 2. Decisions

- **V1 The adapter fetches each voice when it arrives.** Right after it submits the line, the NapCat adapter calls
  `get_record` (`out_format=mp3`, the smaller form) and posts the bytes to the Host for that line. If NapCat refuses, it
  posts the refusal instead, so the line says why. An adapter that cannot fetch voice does not declare it, and its voice
  lines stay as they are today.
- **V2 The Host keeps the audio under a new kind.** The bytes go to GridFS as kind `audio` in the conversation's scope,
  never `image`. The row records the sha256, the size and the first 44 bytes (her contract).
- **V3 Normalize at the entry, always.** Recognize the container by its first bytes (RIFF/WAVE, ID3 or an MP3 frame
  header) before reading any field, then decode with `av` and resample to 16 kHz mono. This happens whatever rate
  arrives: SenseVoice accepts 16 kHz mono only, and NapCat gave 24 kHz.
- **V4 Transcribe in the background, on this machine.**
  - Engine: SenseVoice int8 with Silero voice detection, through the sherpa-onnx Python package 1.13.8. The detector is
    needed (§3). No DSH plugin and no Node bridge.
  - One model is loaded in the Host's Python worker process, about 300 MiB (§3). It is released after 10 minutes with
    no voice, because reloading takes under a second. It gives way to other services when it sits idle, not only
    at a restart (her question, 09:47).
  - One voice is transcribed at a time, in arrival order. Language is detected automatically.
- **V5 What she reads.** Each state has its own words; none is an empty string, which she would read as "nobody spoke":

  | State | Her line shows |
  |---|---|
  | transcribed | 「[语音 33 秒] 文字……」 |
  | still being transcribed | 「[语音 33 秒，正在转写]」 |
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
- **V6 A turn waits briefly for its own voice.** When a turn is about to start and a line in it is still being
  transcribed, the turn waits up to 10 seconds, then starts with whatever state the line has. A 60-second voice takes
  about 1.5 s here (§3), so this wait is rarely reached. If it is, that turn reads 「正在转写」; nothing interrupts a
  running turn. When the text is ready it goes onto the line, and every later reading of that line (her next turn,
  `recall`) shows the text.
- **V7 The audio does not stay forever.** Audio bytes leave GridFS 7 days after they arrive, and the transcript stays
  on the line. Her test set (§5) keeps its own copies.
- **V8 What it does not touch.** Video soundtracks are not transcribed this round (`vision.py` video path,
  `animated.py`). Nothing is sent anywhere outside this machine.

## 3. Measured on this machine (2026-10-23)

Evidence: `.runtime/private/voice/measure-2026-10-23.md` (3 KB), with the configuration recorded.

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
  - keep the next WAV with its sha256 and first 44 bytes;
  - record the configuration with every test.
- Her test set: 5–10 real voices, the longest included, transcribed by both engines and read by her line by line,
  with the number of wrong characters per version.

Signature: ____

## 6. Build

1. The NapCat adapter: declare voice fetching, call `get_record` on arrival, post the bytes or the refusal (V1).
   Self-test entries.
2. Core:
   - the receiving endpoint and the `audio` kind (V2);
   - normalization (V3);
   - the transcriber with the model check (V4, §4);
   - the line's words (V5);
   - the turn's wait (V6);
   - the 7-day sweep (V7).
   Tests for each state, failure paths first.
3. Her test set, read by her (§5), before the install is called done.
