"""Merged forwards in her conversations (QQ 合并转发): what a forward carried, kept on the line that brought it.

The adapter reads a forward's messages into raw.asuna_forward and shows the line as `[合并转发｜N 条｜ref]` with the
first few messages. She reads one in full with `recall` (doc `forward`, sid the ref, a page after a colon), only in
the conversation it arrived in; the action brain's history query searches its messages with the line.
"""
from __future__ import annotations

import re

KEY = 'asuna_forward'
DOC = 'forward'
REF = re.compile(r'^f[0-9a-f]{8}$')
MAX_FORWARDS, MAX_NODES, MAX_NODE_CHARS = 3, 100, 500
PAGE_CHARS = 4000
NODE_TEXT = 'event.raw.%s.nodes.text' % KEY          # what the history query searches beside the line


def _text(value, limit):
    return ' '.join(str(value).split())[:limit] if isinstance(value, (str, int)) and not isinstance(value, bool) else ''


def kept(raw):
    """The forward blocks an adapter sent, checked and bounded; None when there are none."""
    blocks = []
    for block in (raw.get(KEY) if isinstance(raw.get(KEY), list) else [])[:MAX_FORWARDS]:
        if not isinstance(block, dict) or not REF.match(str(block.get('ref') or '')):
            continue
        nodes = []
        for node in (block.get('nodes') if isinstance(block.get('nodes'), list) else [])[:MAX_NODES]:
            if not isinstance(node, dict):
                continue
            when = node.get('time')
            nodes.append({'name': _text(node.get('name'), 42), 'user_id': _text(node.get('user_id'), 64),
                          'time': when if isinstance(when, (int, float)) and not isinstance(when, bool) else None,
                          'text': str(node.get('text') or '')[:MAX_NODE_CHARS]})
        blocks.append({'ref': block['ref'], 'count': len(nodes), 'nodes': nodes,
                       'source': _text(block.get('source'), 12)})
    return blocks or None


def lines(block, zone):
    """Each forwarded message as one line for her: who, when (her clock), what."""
    from datetime import datetime, timezone
    from .schedule_rules import line_stamp
    out = []
    for node in block['nodes']:
        when = (line_stamp(zone, datetime.fromtimestamp(node['time'], timezone.utc).isoformat())
                if node.get('time') else '')
        out.append('%s%s：%s' % (node['name'] or '某人', '（%s）' % when if when else '', node['text'] or '（空）'))
    return out


def read(store, scene_id, sid):
    """A forward in this conversation as a section {doc, sid, heading, body, next?}, or the words why not."""
    from .schedule_rules import scene_timezone
    ref, _, page = str(sid).partition(':')
    page = int(page) if page.isdigit() and int(page) > 0 else 1
    if not REF.match(ref):
        return None, 'forward#%s：sid 照抄那行合并转发里的 ref（f 开头九位）' % sid
    row = store.db.messages.find_one({'scene_id': scene_id, 'direction': 'inbound', 'event.raw.%s.ref' % KEY: ref},
                                     sort=[('received_at', -1)])
    block = next((b for b in ((row or {}).get('event', {}).get('raw', {}).get(KEY) or []) if b.get('ref') == ref), None)
    if not block:
        return None, 'forward#%s：这里没有这条合并转发（只能在它发来的那个对话里读）' % sid
    scene = store.db.scenes.find_one({'_id': scene_id}) or {'_id': scene_id}
    pages, current = [], []
    for line in lines(block, scene_timezone(store.config, scene)):
        if current and sum(len(x) + 1 for x in current) + len(line) > PAGE_CHARS:
            pages.append(current)
            current = []
        current.append(line)
    pages.append(current)
    if page > len(pages):
        return None, 'forward#%s：只有 %d 页' % (sid, len(pages))
    section = {'doc': DOC, 'sid': sid, 'heading': '合并转发，%d 条，第 %d/%d 页' % (block['count'], page, len(pages)),
               'body': '\n'.join(pages[page - 1])}
    if page < len(pages):
        section['next'] = '%s:%d' % (ref, page + 1)
    return section, None


def search_text(doc, limit=2000):
    """The forwarded messages of a stored line, for a history hit ('' when it carried none)."""
    blocks = ((doc.get('event') or {}).get('raw') or {}).get(KEY) or []
    text = '\n'.join('%s：%s' % (node.get('name') or '某人', node.get('text') or '')
                     for block in blocks for node in block.get('nodes') or [])
    return text[:limit]
