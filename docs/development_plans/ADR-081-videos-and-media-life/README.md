# ADR-081: videos as contact sheets, and a life cycle for stored pictures

Status: **accepted and built, 2026-10-19.** Asked by Xiaoman on the night of 2026-10-18 (a video in a group she
could not see); decided with her and the owner the same night (Claude's paraphrase of their words).

## 1. Problem

- A video reached her as `[视频（未解析）]` and nothing else. The adapters already passed its link, file name and
  size in `raw.asuna_media`; the core registered pictures only (`vision.attachments_of`).
- Stored pictures had no end. `artifact_blobs` held 1.2 GB after 11 days, growing 100–340 MB a day:
  - 1,346 sticker pool candidates (592 MB). Only 48 were still listed by the pool (30 at most) or her shelf; the
    rest were bytes left behind by candidates that had left the pool, or stored before a candidate was skipped.
  - 656 copies pulled by `read_image` (305 MB), kept for ever, though the platform is their source and a ref is
    only accepted for 7 days.

## 2. Decisions

- **One sampler, two decoders** (owner, that night: "sampled the same way as gif or other animated image"). A video
  goes through the animated-picture contact sheet (`animated.py`): 9 even moments, look-alike neighbours merged,
  each cell labelled with its order and its real time (`2 · 1.1-2.2s`, her ask), the words about motion and what
  the cells miss. A video is read by seeking 36 even moments, so its length does not change the cost; every fourth
  moment is a cell, and the last cell falls at 8/9 of the video, before a fade-out (her ask: about 90%).
- **Converted at once, never stored** (owner, the same night): the video is downloaded into memory when she reads
  it, turned into the sheet, and dropped. Only the sheet is stored, as a pulled copy.
- **Her conditions** (that night): the cap is a number in `read_image`'s description (32 MB; a 688 KB clip passes
  easily); one declared larger is refused before downloading, with both sizes; a failed download or decode, or a
  missing decoder, says so, never an empty picture; the words say there is no sound in the sheet, so she does not
  guess whether someone speaks.
- **Every kind of stored picture has an owner or an expiry** (owner, the same night, "enforced as you suggested"):
  `media_life.POLICY` by source prefix. Pulled copies (`in-`, `file:`) live 7 days unless her shelf, the pool or a
  sent message names them; pool candidates (`sticker-pool:`) while listed, with a day's grace; her records
  (`sticker:`, `integration:`, `edit:`, `local-upload:`, and anything unlisted) are kept. The worker sweeps at start
  and daily with the audit prune. A test refuses a source prefix in the code that the table does not name.
- **Who decides.** Xiaoman corrected Claude that night: a dependency is pre-approved (owner, 10-08) and pulling from
  an allowed host is not a new channel, so the video design was hers and Claude's to settle; the owner was told,
  and chose the sampler and the storage rule.

## 3. Cost to each brain

- Character brain: no new tool. `read_image`'s description +45 characters (the video sentence with its cap). A
  video's line carries `（视频 ref：att-…）` like a picture's.
- Action brain: the same `read_image` (shared description).
- Program: one dependency, `av` 18.1.0 (PyAV, wheels for Windows, Linux and macOS).

## 4. Evidence

- `tests/test_media_life.py`: a generated 3-second video becomes one labelled sheet whose words say there is no
  sound; a broken file says why; a video over the cap is not pullable and names both sizes; the sweep removes an
  old pulled copy and an unlisted candidate and keeps a new copy, a sent one, a listed candidate, a kept sticker
  and a made picture; every source prefix the code writes is in the table.
- Dry run on the live database before deploying (about 10:40 NZDT, 2026-10-19): 180 expired pulled copies
  (76 MB) and 1,192 unlisted candidates (560 MB) would go; 263 records, 503 recent copies and 154 listed or new
  candidates stay.
