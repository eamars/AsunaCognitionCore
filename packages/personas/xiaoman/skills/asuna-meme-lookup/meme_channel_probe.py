#!/usr/bin/env python3
"""梗指南频道「梗科普图文版」的零依赖探针（技能 asuna-meme-lookup 内置）。

为什么要这支探针：2026-10-26 实测，这个站的正文用 web_fetch 类提取器读不出来
（HTTP 200 只回导航壳），内容其实在服务端渲染的可见层里——自己抓原始 HTML、
剥掉 <script>/<style> 再剥标签才看得见。不写盘、不重试、不用 HTML 库，
网络优先 httpx、缺了就退标准库 urllib。

用法（要网络；在行动脑沙箱里跑）：
    python3 meme_channel_probe.py                      # 频道最新列表（每行：链接 | 标题+概述+日期）
    python3 meme_channel_probe.py 词1 [词2 ...]        # 再抓 archive，按标题子串过滤全库（不分大小写）
    python3 meme_channel_probe.py --post <id或链接>    # 单帖可见正文（前 6000 字）
退出码：0 正常；2 站点不通或抓取失败（这时退技能的路线 b web_search）；3 参数不成形。
"""
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")   # Windows cp1252 控制台直接 print 中文会崩

BASE = "https://neodrop.ai"
CHANNEL = BASE + "/channel/YZNqEhR2owd"
UA = {"User-Agent": "Mozilla/5.0"}


def get(url):
    try:
        import httpx
        return httpx.get(url, timeout=25, follow_redirects=True, headers=UA).text
    except ImportError:
        from urllib.request import Request, urlopen
        with urlopen(Request(url, headers=UA), timeout=25) as resp:
            return resp.read().decode("utf-8", "replace")


def visible(html):
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"\s+", " ", txt).strip()


def cards(html):
    """/post/ 链接配对：返回 [(绝对链接, 标题+概述+日期 压成一行)]，按页面原顺序。"""
    out = []
    for href, inner in re.findall(r'href="(/post/[A-Za-z0-9_-]+)"[^>]*>(.*?)</a>',
                                  html, flags=re.S):
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip()
        out.append((BASE + href, title[:300]))
    return out


def main():
    args = sys.argv[1:]
    if args and args[0] == "--post":
        if len(args) != 2:
            print("用法：meme_channel_probe.py --post <帖子 id 或 /post/ 链接>", file=sys.stderr)
            return 3
        pid = args[1].strip().split("/post/")[-1].strip("/ ")
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,}", pid):
            print("不像帖子 id：%s" % args[1], file=sys.stderr)
            return 3
        try:
            html = get(BASE + "/post/" + pid)
        except Exception as exc:  # noqa: BLE001 站点失败要原样报，不许装读到
            print("取帖子失败：%s: %s —— 退路线 b" % (type(exc).__name__, exc), file=sys.stderr)
            return 2
        text = visible(html)
        print(text[:6000])
        if len(text) > 6000:
            print("……（可见文本共 %d 字，截到这里）" % len(text))
        return 0

    try:
        html = get(CHANNEL)
    except Exception as exc:  # noqa: BLE001
        print("频道不通：%s: %s —— 直接退路线 b web_search" % (type(exc).__name__, exc), file=sys.stderr)
        return 2
    latest = cards(html)
    print("== 频道最新列表（%d 条）==" % len(latest))
    for link, title in latest:
        print(link, "|", title)

    if args:
        try:
            archive = cards(get(CHANNEL + "/archive/1"))
        except Exception as exc:  # noqa: BLE001
            print("archive 不通：%s: %s" % (type(exc).__name__, exc), file=sys.stderr)
            return 2
        print("== archive 全库（%d 条）按关键词过滤 ==" % len(archive))
        hits = 0
        for link, title in archive:
            low = title.lower()
            if any(word.lower() in low for word in args):
                hits += 1
                print(link, "|", title)
        if not hits:
            print("没命中：archive 全部 %d 条标题都不含这些词——别硬配，退路线 b" % len(archive))
    return 0


if __name__ == "__main__":
    sys.exit(main())
