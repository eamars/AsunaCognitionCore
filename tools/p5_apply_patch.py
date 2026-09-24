#!/usr/bin/env python3
"""把 P5 的 patch 打在一份工作树上，并回报是不是每处上下文都对得上（不依赖 patch(1)）。

用法：
  python3 tools/p5_apply_patch.py /task/P5_TOPIC_PROACTIVE.patch --root /task/p5-apply-check \\
      --verify-against /task/asuna-host-p1b

先 dry-run 全部 hunk，任一处对不上就一个字节都不写；--verify-against 再逐字节比一遍
打完的结果与交付工作树，防的是"patch 能过但内容不是那份"。
"""
import io
import os
import sys


def parse(text):
    files, current = [], None
    for line in text.splitlines(True):
        if line.startswith('--- '):
            if current:
                files.append(current)
            current = {'before': line[4:].split('\t')[0].strip(), 'hunks': []}
            continue
        if line.startswith('+++ b/') and current is not None:
            current['after'] = line[6:].split('\t')[0].strip()
            continue
        if current is not None and (line.startswith('@@') or current['hunks']):
            if line.startswith('@@'):
                current['hunks'].append([])
            elif current['hunks']:
                current['hunks'][-1].append(line)
    if current:
        files.append(current)
    return [item for item in files if item.get('after')]


def apply_file(spec, root):
    target = os.path.join(root, spec['after'])
    existed = os.path.exists(target)
    lines = io.open(target, encoding='utf-8').read().splitlines(True) if existed else []
    if not spec['hunks']:
        return None
    out, cursor = [], 0
    for hunk in spec['hunks']:
        old = [row[1:] for row in hunk if row.startswith(('-', ' '))]
        new = [row[1:] for row in hunk if row.startswith(('+', ' '))]
        if not existed and not old:
            out.extend(new)
            continue
        index = next((pos for pos in range(cursor, len(lines) - len(old) + 1)
                      if lines[pos:pos + len(old)] == old), None)
        if index is None:
            raise SystemExit('上下文对不上：%s（第 %d 个 hunk）' % (spec['after'], len(out) and 1 or 1))
        out.extend(lines[cursor:index])
        out.extend(new)
        cursor = index + len(old)
    out.extend(lines[cursor:])
    return ''.join(out)


def main():
    argv = sys.argv[1:]
    patch_path = argv[0]
    root = argv[argv.index('--root') + 1] if '--root' in argv else os.getcwd()
    verify = argv[argv.index('--verify-against') + 1] if '--verify-against' in argv else None
    specs = parse(io.open(patch_path, encoding='utf-8').read())
    results = []
    for spec in specs:
        results.append((spec['after'], apply_file(spec, root)))
    written = 0
    for name, body in results:
        if body is None:
            continue
        target = os.path.join(root, name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        io.open(target, 'w', encoding='utf-8').write(body)
        written += 1
    print('%s：已打 %d 个文件（共 %d 处）' % (patch_path, written, len(results)))
    if not verify:
        return 0
    bad = []
    for name, body in results:
        source = os.path.join(verify, name)
        want = io.open(source, encoding='utf-8').read() if os.path.exists(source) else None
        if want != body:
            bad.append(name)
    print('逐字节比对：%s' % ('全部一致' if not bad else '不一致 → ' + ', '.join(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
