"""One-shot read-only scan (2026-10-19, task: old tool/param name rejection receipts).

Reads session.v4.jsonl.zstd under .runtime/adr008/home/sessions, cross-frame,
window 2026-10-12 21:21 local -> now. Only tool/result lines are quoted.
"""
import os, json, datetime, collections, zstandard

ROOT = r'C:\workspace\asuna_cognition_core_v2\.runtime\adr008\home\sessions'
T0 = datetime.datetime(2026, 10, 12, 21, 21)
START = T0.timestamp() * 1000
NOW = datetime.datetime.now().timestamp() * 1000
KEYS = ('已并入', '已经不用了', '现在叫')
OLD_TOOL_NAMES = ('message_action', 'read_report', 'note_idea', 'update_self')

files = []
for w in sorted(os.listdir(ROOT)):
    p = os.path.join(ROOT, w)
    if not os.path.isdir(p):
        continue
    for d in sorted(os.listdir(p)):
        f = os.path.join(p, d, 'session.v4.jsonl.zstd')
        if os.path.isfile(f):
            files.append((w, d, f, os.path.getmtime(f)))


def rows(f, bad, w, d):
    try:
        with open(f, 'rb') as fh:
            with zstandard.ZstdDecompressor().stream_reader(fh, read_across_frames=True) as sr:
                buf = b''
                while True:
                    c = sr.read(1 << 21)
                    if not c:
                        break
                    buf += c
                    while True:
                        i = buf.find(b'\n')
                        if i < 0:
                            break
                        ln = buf[:i]
                        buf = buf[i + 1:]
                        if ln.strip():
                            yield ln
                if buf.strip():
                    yield buf
    except Exception as e:
        bad.append((w, d, repr(e)[:160]))


scanned = 0
skipped = 0
bad = []
unparsable = 0
callrows = 0
resrows = 0
hits = []
combos = collections.Counter()
oldname = collections.Counter()
aux = collections.Counter()

for w, d, f, mt in files:
    if mt < T0.timestamp():
        skipped += 1
        continue
    scanned += 1
    for ln in rows(f, bad, w, d):
        try:
            o = json.loads(ln.decode('utf-8'))
        except Exception:
            unparsable += 1
            continue
        t = o.get('type')
        tm = o.get('time')
        if not isinstance(tm, (int, float)) or tm < START or tm > NOW:
            continue
        if t == 'tool/call':
            callrows += 1
            dd = o.get('data') or {}
            nm = dd.get('name')
            a = dd.get('arguments')
            if isinstance(a, str):
                try:
                    aj = json.loads(a)
                    keys = sorted(aj.keys()) if isinstance(aj, dict) else ['<' + type(aj).__name__ + '>']
                except Exception:
                    keys = ['<unparsable-args>']
            elif isinstance(a, dict):
                keys = sorted(a.keys())
            else:
                keys = ['<' + type(a).__name__ + '>']
            combos[(nm, tuple(keys))] += 1
            if nm in OLD_TOOL_NAMES:
                oldname[nm] += 1
        elif t == 'tool/result':
            resrows += 1
            m = (o.get('data') or {}).get('message')
            parts = []
            cid = None
            iserr = None
            if isinstance(m, dict):
                cid = m.get('toolCallId')
                iserr = m.get('isError')
                ct = m.get('content')
                if isinstance(ct, list):
                    for b in ct:
                        if isinstance(b, dict) and isinstance(b.get('text'), str):
                            parts.append(b['text'])
                elif isinstance(ct, str):
                    parts.append(ct)
            for txt in parts:
                for line in txt.split('\n'):
                    for k in KEYS:
                        if k in line:
                            hits.append((tm, w, d, cid, iserr, k, line.strip()[:600]))
                            break
        elif t in ('user/message', 'system/message', 'assistant/message'):
            s = json.dumps(o.get('data'), ensure_ascii=False)
            for k in KEYS:
                if k in s:
                    aux[(t, k)] += 1
                    break

print('WINDOW', T0.strftime('%Y-%m-%d %H:%M'), '->', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
print('ROOT', ROOT)
print('files on disk', len(files), '| scanned', scanned, '| skipped (mtime older than window)', skipped,
      '| unparsable lines', unparsable, '| bad files', len(bad))
for b in bad[:10]:
    print('BAD', b)
print('tool/call rows in window', callrows, '| tool/result rows in window', resrows)
print('HITS in tool/result', len(hits))
for h in hits:
    print('HIT', datetime.datetime.fromtimestamp(h[0] / 1000).strftime('%Y-%m-%d %H:%M:%S'),
          '|', h[1], '|', h[2], '| callId', h[3], '| isError', h[4], '| key', h[5])
    print('   LINE:', h[6])
print('AUX hits by other row types (counts only, no body printed)', dict(aux))
print('OLD TOOL NAMES used in window', dict(oldname))
print('distinct (tool name, arg keys) combos', len(combos))
for (nm, ks), c in combos.most_common(400):
    print('COMBO', nm, c, ks)
