"""Animated pictures as something a still-image model can see: one labelled contact sheet plus words.

A model route takes still images only (DSH normalises every attachment to one frame: the first). An animated GIF,
WebP or APNG is therefore turned, deterministically, into a PNG grid of frames taken at even moments across one
loop: a frame held long fills several moments (merged into one cell), a frame shown for a blink usually fills
none. Each cell is labelled with its order and its time in the animation. The words say what the sheet is and
what it cannot show: how many frames, how long one loop is, how much the picture moves, how many frames that
differ visibly from every cell were left out, and whether there is fast back-and-forth flicker that a viewer sees
as blinking or two layers at once and that no single frame contains.

The stored bytes stay the original; only what reaches the model is the sheet.
"""
from __future__ import annotations

import io
import math

CELLS = 9                                 # moments taken across one loop
CELL_EDGE = 240                           # long edge of a cell, pixels
GUTTER = 6
LABEL_HEIGHT = 22
CELL_BACKGROUND = (221, 221, 221, 255)    # what shows through transparent pixels
MAX_FRAMES = 1500
MAX_DECODED_PIXELS = 300_000_000          # frames × width × height decoded for one picture
GIF_MIN_DELAY_MS = 20                     # browsers play a shorter GIF delay (0 or 10 ms) as 100 ms
DEFAULT_DELAY_MS = 100
THUMB = 32                                # frames are compared as THUMB × THUMB greyscale
SAME = 3.0                                # mean difference (0–255) at or below which two frames look the same
CHANGE = 8.0                              # above this the picture visibly changed
APART = 20.0                              # a left-out frame this far from its nearest cell is a loss worth naming
FLICKER_FRAME_MS = 60                     # back-and-forth frames at most this long are seen as flicker
HOLD_SHARE = 0.5                          # one frame held for at least this share of a loop of at least
HOLD_MIN_MS = 1000                        # this long is named

LOSS_NOTE = ('这是程序从动画里按时间截出的静止格子，不是动画本身：格与格之间的动作、一闪而过的帧、'
             '只有连着播才看得出的效果（闪烁、两层叠在一起的残影）都可能没截到。')
CELLS_NOTE = ('图里是按时间均匀取的 %d 个时刻，相邻看起来一样的已合成一格，共 %d 格；从左到右、从上到下，'
              '每格下面标着第几格和它在动画里的时刻（秒）。')
MOTION = ((0, '画面几乎不动'), (3, '画面有一两次明显变化'), (9, '画面有好几次明显变化'), (math.inf, '画面一直在动'))
MISSED = ((0, '没截到的帧都跟相邻的格子差不多'),          # share of frames left out that differ from their nearest cell
          (0.1, '有少数几帧跟格子里的画面明显不同（多半是很快的动作或一闪而过的帧），没截到'),
          (0.4, '有不少帧跟格子里的画面明显不同（动作快，格子之间缺了过程），没截到'),
          (1, '大部分帧都跟格子里的画面明显不同（动作很快，格子只是其中几个瞬间），没截到'))
FLICKER_WORDS = ('没有快速来回切换的段落',
                 '有 %d 段快速来回切换（每帧不到 %d 毫秒）：连着播时人眼看到的是闪烁或两层叠在一起，格子里只能看到其中一边')
TOO_BIG = 'ANIMATION_NOT_SPLIT: 这张动图太大（%s），程序没拆帧，只送了第一帧；动画里后面的内容看不到'
UNREADABLE = 'ANIMATION_NOT_SPLIT: 这张动图拆帧失败（%s），只送了第一帧；动画里后面的内容看不到'


def _seconds(ms):
    return ('%.1f' % (ms / 1000)).rstrip('0').rstrip('.') if ms % 1000 else '%d' % (ms // 1000)


def _loops(info):
    if 'loop' not in info:
        return '只播一遍'
    return '一直循环' if info['loop'] == 0 else '重复 %d 次' % info['loop']


def _diff(a, b):
    from PIL import ImageChops, ImageStat
    return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]


def _frame(image, index):
    """One frame fully composited, as a viewer sees it."""
    image.seek(index)
    return image.convert('RGBA')


def _timeline(image):
    """([effective ms per frame], [THUMB × THUMB greyscale per frame]); frames are not kept."""
    gif = image.format == 'GIF'
    delays, thumbs = [], []
    for index in range(image.n_frames):
        frame = _frame(image, index)
        delay = image.info.get('duration') or 0
        delays.append(DEFAULT_DELAY_MS if not delay or gif and delay < GIF_MIN_DELAY_MS else int(delay))
        thumbs.append(frame.convert('L').resize((THUMB, THUMB)))
    return delays, thumbs


def _flicker_runs(thumbs, delays):
    """Stretches where short frames alternate A, B, A, B: each counted once."""
    runs, length = 0, 0
    for i in range(len(thumbs) - 2):
        alternates = (max(delays[i:i + 3]) <= FLICKER_FRAME_MS and _diff(thumbs[i], thumbs[i + 1]) > 2 * CHANGE
                      and _diff(thumbs[i], thumbs[i + 2]) <= 2 * SAME)
        length = length + 1 if alternates else 0
        if length == 2:                    # A B A B: two overlapping triples
            runs += 1
    return runs


def _sheet(cells):
    from PIL import Image, ImageDraw, ImageFont
    columns = 1 if len(cells) == 1 else 2 if len(cells) in (2, 4) else 3
    rows = math.ceil(len(cells) / columns)
    width = columns * CELL_EDGE + (columns + 1) * GUTTER
    height = rows * (CELL_EDGE + LABEL_HEIGHT) + (rows + 1) * GUTTER
    sheet = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=15)
    for n, (frame, label) in enumerate(cells):
        column, row = n % columns, n // columns
        x = GUTTER + column * (CELL_EDGE + GUTTER)
        y = GUTTER + row * (CELL_EDGE + LABEL_HEIGHT + GUTTER)
        cell = Image.new('RGBA', (CELL_EDGE, CELL_EDGE), CELL_BACKGROUND)
        shown = frame.copy()
        shown.thumbnail((CELL_EDGE, CELL_EDGE))
        cell.alpha_composite(shown, ((CELL_EDGE - shown.width) // 2, (CELL_EDGE - shown.height) // 2))
        sheet.paste(cell.convert('RGB'), (x, y))
        draw.text((x + 4, y + CELL_EDGE + 3), label, fill=(0, 0, 0), font=font)
    out = io.BytesIO()
    sheet.save(out, format='PNG', optimize=True)
    return out.getvalue()


def snapshot(data):
    """(png bytes, words) for an animated picture; (None, words) when it could not be split; None when still."""
    from PIL import Image
    try:
        image = Image.open(io.BytesIO(data))
        count = getattr(image, 'n_frames', 1)
    except Exception:                      # noqa: BLE001 not ours to judge here: the normal path reports bad bytes
        return None
    if count <= 1:
        return None
    if count > MAX_FRAMES or count * image.width * image.height > MAX_DECODED_PIXELS:
        return None, {'error': TOO_BIG % ('%d 帧，每帧 %d×%d' % (count, image.width, image.height))}
    try:
        delays, thumbs = _timeline(image)
    except Exception as exc:               # noqa: BLE001 a truncated or odd file: say so, the first frame still goes
        return None, {'error': UNREADABLE % type(exc).__name__}
    total = sum(delays)
    starts = [sum(delays[:i]) for i in range(len(delays))]

    def at(moment):
        return max(i for i, start in enumerate(starts) if start <= moment)

    picks = []                             # [(frame index, first moment, last moment)]
    for k in range(CELLS):
        moment = total * k // CELLS
        index = at(moment)
        if picks and (picks[-1][0] == index or _diff(thumbs[picks[-1][0]], thumbs[index]) <= SAME):
            picks[-1] = (picks[-1][0], picks[-1][1], moment)
        else:
            picks.append((index, moment, moment))
    chosen = [index for index, _, _ in picks]
    labels = ['%d · %ss' % (n + 1, _seconds(first)) if first == last else
              '%d · %s-%ss' % (n + 1, _seconds(first), _seconds(last)) for n, (_, first, last) in enumerate(picks)]

    changes, anchor = 0, thumbs[0]
    for thumb in thumbs[1:]:
        if _diff(anchor, thumb) > CHANGE:
            changes, anchor = changes + 1, thumb
    missed = 0
    for i in range(len(delays)):
        if i not in chosen:
            nearest = min(chosen, key=lambda c: abs(starts[c] - starts[i]))
            missed += _diff(thumbs[i], thumbs[nearest]) > APART
    flicker = _flicker_runs(thumbs, delays)

    words = {'kind': '动图快照',
             'what': '共 %d 帧，播一遍约 %s 秒，%s' % (len(delays), _seconds(total), _loops(image.info)),
             'cells': CELLS_NOTE % (CELLS, len(picks)),
             'motion': next(text for limit, text in MOTION if changes <= limit),
             'missed': next(text for limit, text in MISSED if missed / len(delays) <= limit),
             'flicker': FLICKER_WORDS[1] % (flicker, FLICKER_FRAME_MS) if flicker else FLICKER_WORDS[0]}
    longest = max(range(len(delays)), key=lambda i: delays[i])
    if total >= HOLD_MIN_MS and delays[longest] >= HOLD_SHARE * total and longest in chosen:
        words['hold'] = '大部分时间（约 %s 秒）停在第 %d 格的画面' % (_seconds(delays[longest]), chosen.index(longest) + 1)
    words['note'] = LOSS_NOTE
    try:
        sheet = _sheet([(_frame(image, index), label) for index, label in zip(chosen, labels)])
    except Exception as exc:               # noqa: BLE001
        return None, {'error': UNREADABLE % type(exc).__name__}
    return sheet, words


def seen(data, media_type):
    """What the model is given for these bytes: ({'media_type', 'data'}, words or None)."""
    import base64
    made = snapshot(data) if media_type in ('image/gif', 'image/webp', 'image/png') else None
    if made and made[0]:
        return {'media_type': 'image/png', 'data': base64.b64encode(made[0]).decode()}, made[1]
    return {'media_type': media_type, 'data': base64.b64encode(data).decode()}, (made[1] if made else None)
