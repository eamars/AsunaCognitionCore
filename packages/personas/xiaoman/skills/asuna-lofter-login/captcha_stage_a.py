#!/usr/bin/env python3
"""LOFTER jigsaw 滑块 stage A：拿一张拼图 + 四把算法投票判缺口 xPos + 存状态（不发 check、不登录）。

坐标口径（照前端 captcha.js 读码，不是猜的）：bg 容器 `.common__captcha__img{width:320px}` 加
`.img__bg{width:100%}` ⇒ bg 显示宽 = natural 宽 ⇒ `xPos = offsetX * oriWidth / bgDisplayWidth` 就是 1:1；
`.img__front{height:100%}` ⇒ 拼图条按高等比（高相同则宽不变）。
**所以 xPos ＝ 拼图条左边缘在 bg 原图坐标里的 x**（拼图形状在条内哪几列由 alpha 量出来）。

四把一起投，单把不许发（实测眼读单把会错、模糊 NCC 单独看会离群）：
  1 edge  轮廓打分：front alpha 掩码的轮廓像素，在 bg 的梯度图上按平移位求均值，取峰
  2 dark  洞内暗度：掩码内灰度均值（洞里的底比周围暗），取最小
  3 ncc   归一化互相关：拼块高斯模糊后，与 bg 各平移位的对应窗口做掩码内 NCC，取峰
  4 seam  接缝色差：拼块贴到 x 处后，接缝内侧（拼块）与外侧（bg 残留）的 RGB 色差均值，取最小

投票：四把读数一起列出来，取 3 把以上互相落在 ±TOL 像素内的最大簇，报该簇中值；
凑不出 3 把一致就退出码 3（换一张图重投，别硬发）。

联网跑法（花一次 captcha 配额：写 <TAG>_state.json 与 <TAG>_bg.jpeg／_front.png／_grid.png／_comp_vote.png）：
    python3 captcha_stage_a.py                    # CAPTAG 环境变量换文件前缀，默认 capA
离线核口径跑法（不联网、不花配额，用已存下的图；默认什么都不写）：
    python3 captcha_stage_a.py --bg capA_bg.jpeg --front capA_front.png
"""
import argparse
import base64
import io
import json
import os
import random
import string
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

TOL = 5          # 一致判定：两把读数相差多少像素内算一致
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def load_pair(bg_path, front_path):
    bg = Image.open(bg_path); bg.load()
    fr = Image.open(front_path); fr.load()
    return bg.convert("RGB"), fr.convert("RGBA")


def geometry(fr):
    """(掩码, 形状行列范围, 掩码内像素, 接缝内像素, 接缝外像素, 轮廓像素)。列号是拼图条内坐标。"""
    mask = np.asarray(fr)[:, :, 3] > 10
    rows = np.where(mask.any(axis=1))[0]
    cols = np.where(mask.any(axis=0))[0]
    box = (int(rows.min()), int(rows.max()), int(cols.min()), int(cols.max()))
    m = mask.astype(np.uint8)
    inner, outer = [], []
    for (dr, dc) in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        sh = np.roll(np.roll(m, dr, axis=0), dc, axis=1)      # 把掩码往内挪一格
        ys, xs = np.where((sh == 1) & (m == 0))               # 外侧像素（掩码外、邻着掩码内）
        ir, ic = np.broadcast_arrays(
            np.clip(np.arange(m.shape[0])[:, None] + dr, 0, m.shape[0] - 1),
            np.clip(np.arange(m.shape[1])[None, :] + dc, 0, m.shape[1] - 1))
        outer.append(np.stack([ys, xs], 1))
        inner.append(np.stack([ir[ys, xs], ic[ys, xs]], 1))
    er = np.zeros_like(mask)
    er[1:, :] |= mask[:-1, :]; er[:-1, :] |= mask[1:, :]
    er[:, 1:] |= mask[:, :-1]; er[:, :-1] |= mask[:, 1:]
    return (mask, box, np.where(mask), np.concatenate(inner), np.concatenate(outer),
            np.where(er & ~mask))


def scores(bg, fr, geom):
    """四把在每个平移位 x 上的打分数组（长度 = bg 宽 - 条宽 + 1）与各自的读数。"""
    mask, box, inside, inner, outer, contour = geom
    r0, r1, c0, c1 = box
    g = np.asarray(bg.convert("L")).astype(np.float64)
    bgrgb = np.asarray(bg).astype(np.float64)
    frrgb = np.asarray(fr)[:, :, :3].astype(np.float64)
    grad = np.zeros_like(g)
    grad[1:-1, 1:-1] = (np.abs(np.gradient(g, axis=0)[1:-1, 1:-1])
                        + np.abs(np.gradient(g, axis=1)[1:-1, 1:-1]))
    oy, ox = outer[:, 0], outer[:, 1]
    iy, ix = inner[:, 0], inner[:, 1]
    cy, cx = contour
    ys, xs = inside
    blur = np.asarray(fr.filter(ImageFilter.GaussianBlur(2)).convert("L")).astype(np.float64)
    boxmask = mask[r0:r1 + 1, c0:c1 + 1]
    pt = blur[r0:r1 + 1, c0:c1 + 1][boxmask]
    pt = pt - pt.mean()
    pn = float(np.sqrt((pt * pt).sum())) or 1.0
    span = bg.width - fr.width
    edge = np.zeros(span + 1); dark = np.zeros(span + 1); ncc = np.zeros(span + 1); seam = np.zeros(span + 1)
    for x in range(span + 1):
        edge[x] = grad[cy, cx + x].mean()
        dark[x] = g[ys, xs + x].mean()
        win = g[r0:r1 + 1, c0 + x:c1 + 1 + x][boxmask]
        wm = win - win.mean()
        ncc[x] = float((wm * pt).sum() / ((float(np.sqrt((wm * wm).sum())) or 1.0) * pn))
        seam[x] = float(np.abs(bgrgb[oy, ox + x] - frrgb[iy, ix]).mean())
    readings = {"edge_peak": int(np.argmax(edge)), "dark_min": int(np.argmin(dark)),
                "ncc_peak": int(np.argmax(ncc)), "seam_min": int(np.argmin(seam))}
    return readings, {"edge": edge, "dark": dark, "ncc": ncc, "seam": seam}


def vote(readings):
    """四把读数里找 3 把以上互相落在 ±TOL 的最大簇；返回 (簇中值或 None, 一句说明)。"""
    pts = sorted(readings.items())
    best = []
    for _, v in pts:
        members = [(n, w) for n, w in pts if abs(w - v) <= TOL]
        if len(members) > len(best):
            best = members
    if len(best) < 3:
        return None, "四把凑不出 3 把一致（±%d px）→ 换一张图重投，不硬发" % TOL
    vals = sorted(w for _, w in best)
    med = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2.0
    return float(med), "一致 %d 把：%s，区间 %d-%d" % (
        len(best), "、".join("%s=%d" % (n, w) for n, w in best), vals[0], vals[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bg"); ap.add_argument("--front")
    ap.add_argument("--save", action="store_true", help="离线模式也写对照图")
    a = ap.parse_args()
    tag = os.environ.get("CAPTAG", "capA")
    cookies, cid, ctype, offline = [], None, "jigsaw", bool(a.bg and a.front)

    if offline:
        bg, fr = load_pair(a.bg, a.front)
        print("离线核口径：bg=%s front=%s（不联网、不花 captcha 配额）" % (a.bg, a.front))
    else:
        import httpx
        c = httpx.Client(headers={"user-agent": UA, "referer": "https://www.lofter.com/front/login"},
                         timeout=25, follow_redirects=True)
        r = c.get("https://captcha.lofter.com/captcha/get", params={"type": "jigsaw"})
        j = r.json()
        print("GET /captcha/get status=%s code=%s msg=%r" % (r.status_code, j.get("code"), j.get("msg")))
        d = j["data"]
        cid, ctype = d["id"], d["type"]
        for h in r.headers.get_list("set-cookie"):
            cookies.append(h.split(";")[0])
        open("%s_bg.jpeg" % tag, "wb").write(base64.b64decode(d["bg"]))
        open("%s_front.png" % tag, "wb").write(base64.b64decode(d["front"]))
        bg, fr = load_pair("%s_bg.jpeg" % tag, "%s_front.png" % tag)

    geom = geometry(fr)
    mask, box, inside, inner, outer, contour = geom
    print("bg %dx%d  front %dx%d  拼图在条内 rows %d..%d cols %d..%d  拼图像素 %d 轮廓 %d 接缝对 %d"
          % (bg.width, bg.height, fr.width, fr.height, box[0], box[1], box[2], box[3],
             len(inside[0]), len(contour[0]), len(inner)))
    readings, curves = scores(bg, fr, geom)
    print("四把读数（平移位 x，就是 xPos 口径）:", json.dumps(readings))
    for k in ("edge", "dark", "ncc", "seam"):
        top = (np.argsort(curves[k])[-3:][::-1] if k in ("edge", "ncc") else np.argsort(curves[k])[:3])
        print("  %s 前三位: %s" % (k, [(int(i), round(float(curves[k][i]), 3)) for i in top]))
    x, why = vote(readings)
    print("投票:", why, "| xPos =", x)
    if x is None:
        return 3

    if not offline:
        def rkey16():
            return "".join(str(random.randint(0, 8)) if random.random() < 0.5
                           else string.ascii_lowercase[random.randint(0, 24)] for _ in range(16))
        state = {"id": cid, "type": ctype, "aes_key": rkey16(), "aes_iv": rkey16(), "cookies": cookies,
                 "readings": readings, "xPos": x, "bg_w": bg.width, "bg_h": bg.height, "front_w": fr.width}
        json.dump(state, open("%s_state.json" % tag, "w"), ensure_ascii=False, indent=1)
        print("state -> %s_state.json（含临时 AES key/iv，不外传；那个 id 用一次就废）" % tag)
    if a.save or not offline:
        S = 3
        comp = bg.convert("RGBA"); comp.paste(fr, (int(x), 0), fr)
        comp.convert("RGB").resize((bg.width * S, bg.height * S), Image.NEAREST).save("%s_comp_vote.png" % tag)
        big = bg.resize((bg.width * S, bg.height * S), Image.NEAREST).convert("RGB")
        dr = ImageDraw.Draw(big)
        for col in range(0, bg.width + 1, 20):
            dr.line([(col * S, 0), (col * S, bg.height * S)], fill=(60, 60, 60), width=1)
            dr.text((col * S + 2, 2), str(col), fill=(255, 255, 0))
        dr.rectangle([int(x) * S, 0, (int(x) + fr.width) * S, bg.height * S], outline=(0, 255, 0), width=3)
        big.save("%s_grid.png" % tag)
        print("对照图 -> %s_comp_vote.png / %s_grid.png" % (tag, tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
