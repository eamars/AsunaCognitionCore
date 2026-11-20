import hashlib
import os
import sys


def sha(p):
    b = open(p, 'rb').read()
    return hashlib.sha256(b).hexdigest(), len(b)


def tree(base):
    out = {}
    for r, d, fs in os.walk(base):
        d[:] = [x for x in d if x not in ('.git', '__pycache__', 'node_modules', '.runtime', 'dist', 'build')]
        for f in fs:
            p = os.path.join(r, f)
            out[os.path.relpath(p, base).replace(os.sep, '/')] = sha(p)
    return out


cand_root, pkg_sub, installed, skill_name = sys.argv[1:5]
cand_pkg = os.path.join(cand_root, pkg_sub)

print('== changed flags (candidate, all files) ==')
flags = {}
for r, d, fs in os.walk(cand_root):
    d[:] = [x for x in d if x not in ('.git', 'node_modules', '.runtime')]
    for f in fs:
        p = os.path.join(r, f)
        rel = os.path.relpath(p, cand_root).replace(os.sep, '/')
        flags[rel] = True
print('candidate files walked:', len(flags))

print('== tree diff: candidate packages/cognition-core vs installed packageRoot ==')
a, b = tree(cand_pkg), tree(installed)
print('files: candidate', len(a), 'installed', len(b))
print('ONLY_CANDIDATE', sorted(set(a) - set(b)))
print('ONLY_INSTALLED', sorted(set(b) - set(a)))
diff = sorted(k for k in a if k in b and a[k] != b[k])
print('DIFFER', diff)
for k in diff:
    print('   ', k, 'cand', a[k], 'installed', b[k])

print('== skill dir listing (candidate) ==')
sk_c = os.path.join(cand_pkg, 'skills', skill_name)
for f in sorted(os.listdir(sk_c)):
    p = os.path.join(sk_c, f)
    if os.path.isfile(p):
        h, n = sha(p)
        print('  CAND', f, n, h[:12])
sk_i = os.path.join(installed, 'skills', skill_name)
print('== skill dir listing (installed/ACTIVE) ==')
for f in sorted(os.listdir(sk_i)):
    p = os.path.join(sk_i, f)
    if os.path.isfile(p):
        h, n = sha(p)
        print('  INST', f, n, h[:12])

print('== headings in candidate SKILL.md ==')
cand_skill = os.path.join(sk_c, 'SKILL.md')
lines = open(cand_skill, encoding='utf-8').read().split('\n')
for i, ln in enumerate(lines, 1):
    if ln.startswith('#'):
        print('  %4d %s' % (i, ln))

print('== lines containing --all ==')
for i, ln in enumerate(lines, 1):
    if '--all' in ln:
        print('  %4d %s' % (i, ln))

print('== CR check / line count ==')
raw = open(cand_skill, 'rb').read()
print('  bytes', len(raw), 'CR', raw.count(b'\r'), 'LF', raw.count(b'\n'), 'lines', len(lines))
