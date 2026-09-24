#!/usr/bin/env python3
"""生成 P2 第二片审阅用 patch：旧内容一律取自 /task/p2-pre-slice2 那份快照，不靠回忆拼。

那份快照 = P1-c 交付状态 + 第一片 patch 的真实产物（tests/tools 都在里面），
再把 context.py 换成部署侧那份（多一段与本片无关的 group_discussion 能力说明，
本片三个 hunk 都不碰它，宿主上有没有都能打）。快照里没有的文件按新建给整篇。
"""
import difflib
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get('P2_BASELINE', '/task/p2-pre-slice2')
PATHS = ('src/asuna/memory.py', 'src/asuna/context.py', 'src/asuna/dialogue_summary.py',
         'src/asuna/memory_indexer.py', 'src/asuna/host.py',
         'tests/p2_summary_loop_cases.py', 'tests/test_p2_summary_loop.py',
         'src/asuna/summary_trigger.py', 'src/asuna/summary_attribution.py',
         'tools/p2b_probe_loop.py', 'tools/p2b_edge_probe.py', 'tools/p2_offline_check.py',
         'tools/p2b_make_patch.py', 'P2_SUMMARY_LOOP_2_USAGE.md')


def read(path):
    return io.open(path, encoding='utf-8').read().splitlines(True)


def main():
    out, created, changed = [], [], []
    for name in PATHS:
        before_path = os.path.join(BASE, name)
        before = read(before_path) if os.path.exists(before_path) else []
        after = read(os.path.join(ROOT, name))
        if before == after:
            continue
        (created if not before else changed).append(name)
        out.append(''.join(difflib.unified_diff(
            before, after, fromfile=('/dev/null' if not before else 'a/%s\t(p2-pre-slice2)' % name),
            tofile='b/%s' % name, lineterm='\n')))
    body = ''.join(out)
    target = sys.argv[1] if len(sys.argv) > 1 else '/task/P2_SUMMARY_LOOP_2.patch'
    io.open(target, 'w', encoding='utf-8').write(body)
    print('%s：%d 行；改 %d 个%s' % (
        target, len(body.splitlines()), len(changed),
        '' if not created else '，新建 %d 个' % len(created)))


if __name__ == '__main__':
    main()
