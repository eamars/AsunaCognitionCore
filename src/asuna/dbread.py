"""Reading the character's database from her task scripts: `from asuna import dbread`.

Read only by design: find, count, distinct and aggregate, nothing that writes. Every answer says what it asked
(database, collection, filter, the UTC window a local one became) and how many rows it found, and says 零行 when it
found none, so a report can be checked against its query and an empty answer is never mistaken for one not run.
The Host gives a home task's commands the database and her time zone (`environment`); a script needs no address.

    from asuna import dbread
    when = dbread.local_window('2026-10-12 21:00', '2026-10-12 22:00')      # her clock -> UTC bounds
    dbread.show(dbread.find('messages', {'scene_id': 'local-dm', 'received_at': when}, fields=['text', 'author']))
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

LIMIT = 50
MOST = 500
SAMPLE = 200
HIDDEN = ('embedding', 'event.raw')        # large, and never what a question is about
ENV = {'uri': 'ASUNA_MONGO_URI', 'database': 'ASUNA_DATABASE', 'zone': 'ASUNA_TIMEZONE'}
# Names people reach for that are not collections, and where that thing is kept.
ELSEWHERE = {
    'documents': '她的文档在 state_heads（_id 形如 doc:<主人>:<名字>，revision_id 指向当前版本）和 state_revisions'
                 '（content.sections 是正文）',
    'monologues': '心里话在 memory_units，kind 是 monologue',
    'summaries': '交流摘要在 memory_units，kind 是 dialogue_summary',
    'people': '群里的人在 scene_people（每个群里一人一条：person、handle、card、nickname）；账号在 identities',
    'archive': '群的旧历史在 messages 里：scene_id 是 archive:<scene_id>，direction 是 archived（见 history）',
}
WRITERS = ('$out', '$merge')


class Window(dict):
    """A filter value for a local-time window: {'$gte': utc, '$lt': utc}, remembering what it was asked as."""


def _zone(name):
    from zoneinfo import ZoneInfo
    try:
        return ZoneInfo(name or os.environ.get(ENV['zone']) or 'UTC')
    except Exception:
        return timezone.utc


def _local(text, zone):
    text = str(text).strip().replace('T', ' ')
    for shape in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(text, shape).replace(tzinfo=zone), shape == '%Y-%m-%d'
        except ValueError:
            continue
    raise ValueError('「%s」不是本地钟点：写成 2026-10-12 21:00 或 2026-10-12（整天）' % text[:40])


def local_window(start, end=None, zone=None):
    """Her local times -> UTC bounds for any *_at field. A date alone is that whole local day; no end is one hour.
    The bounds carry no zone suffix, so they compare right with both stored forms (…Z and …+00:00)."""
    tz = _zone(zone)
    begin, whole_day = _local(start, tz)
    finish = _local(end, tz)[0] if end else begin + (timedelta(days=1) if whole_day else timedelta(hours=1))
    if whole_day and end and _local(end, tz)[1]:
        finish += timedelta(days=1)                       # an end date includes that day
    utc = [moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S') for moment in (begin, finish)]
    window = Window({'$gte': utc[0], '$lt': utc[1]})
    window.asked = {'local': [str(start), str(end) if end else None], 'zone': getattr(tz, 'key', 'UTC'), 'utc': utc}
    return window


def now(zone=None):
    """Her clock now, as local_window takes it: '2026-10-13 12:05'."""
    return datetime.now(_zone(zone)).strftime('%Y-%m-%d %H:%M')


def recent(hours=24, zone=None):
    """The last `hours` up to now, as a local-time window."""
    tz = _zone(zone)
    end = datetime.now(tz)
    return local_window((end - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S'), end.strftime('%Y-%m-%d %H:%M:%S'),
                        zone)


def _plain(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


class Reader:
    def __init__(self, db, name):
        self.db, self.name = db, name
        self._fields = {}

    @classmethod
    def from_host(cls):
        """The database the Host named for this command, else the checkout's local config."""
        from pymongo import MongoClient
        uri, name = os.environ.get(ENV['uri']), os.environ.get(ENV['database'])
        if not (uri and name):
            from .config import ROOT, load
            config = load(ROOT / 'config' / 'local.json')
            uri, name = config['mongo_uri'], config['database']
        return cls(MongoClient(uri, serverSelectionTimeoutMS=5000)[name], name)

    def collection(self, name):
        real = sorted(self.db.list_collection_names())
        if name not in real:
            hint = ELSEWHERE.get(name) or ELSEWHERE.get(str(name).rstrip('s'))
            raise ValueError('没有叫「%s」的集合。%s有的集合：%s' % (name, (hint + '。') if hint else '', '、'.join(real)))
        return self.db[name]

    def fields(self, name):
        """Field names seen in a sample of the collection (top level and one level down)."""
        if name not in self._fields:
            seen = set()
            for doc in self.db[name].find({}, {'embedding': 0}).sort('_id', -1).limit(SAMPLE):
                for key, value in doc.items():
                    seen.add(key)
                    if isinstance(value, dict):
                        seen.update('%s.%s' % (key, sub) for sub in value)
            self._fields[name] = seen
        return self._fields[name]

    def _unknown(self, name, query):
        keys = set()

        def walk(part):
            if isinstance(part, dict):
                for key, value in part.items():
                    if key.startswith('$'):
                        walk(value)
                    else:
                        keys.add(key)
            elif isinstance(part, list):
                for item in part:
                    walk(item)
        walk(query or {})
        known = self.fields(name)
        return sorted(key for key in keys if key not in known and key.split('.')[0] not in known)

    def _answer(self, name, query, rows, **extra):
        windows = []

        def find_windows(part):
            if isinstance(part, Window):
                windows.append(part.asked)
            elif isinstance(part, dict):
                for value in part.values():
                    find_windows(value)
        find_windows(query)
        out = {'database': self.name, 'collection': name, 'filter': _plain(query or {}),
               **({'local_window': windows} if windows else {}), **extra,
               'found': len(rows) if isinstance(rows, list) else rows}
        unknown = self._unknown(name, query)
        if unknown:
            out['unseen_fields'] = ('这些字段在 %s 最近 %d 条里一次都没出现过：%s。先用 fields("%s") 看真名'
                                    % (name, SAMPLE, '、'.join(unknown), name))
        if not out['found']:
            out['said'] = '零行：查了，没有符合的'
        if isinstance(rows, list):
            out['rows'] = _plain(rows)
        return out

    def find(self, name, query=None, fields=None, sort=None, limit=LIMIT, skip=0):
        limit = max(1, min(int(limit or LIMIT), MOST))
        projection = ({field: 1 for field in fields} if fields else {field: 0 for field in HIDDEN})
        cursor = self.collection(name).find(query or {}, projection)
        if sort:
            cursor = cursor.sort(list(sort))
        rows = list(cursor.skip(int(skip or 0)).limit(limit + 1))
        more = len(rows) > limit
        return self._answer(name, query, rows[:limit], **({'sort': _plain(list(sort))} if sort else {}),
                            **({'skip': int(skip)} if skip else {}), limit=limit,
                            **({'more': '还有更多：缩小过滤，或按 scene_seq/时间分段，不要用大 skip'} if more else {}))

    def count(self, name, query=None):
        return self._answer(name, query, self.collection(name).count_documents(query or {}))

    def distinct(self, name, field, query=None):
        values = self.collection(name).distinct(field, query or {})
        return self._answer(name, query, values[:MOST], field=field)

    def aggregate(self, name, pipeline, limit=LIMIT):
        if any(stage in WRITERS for step in pipeline for stage in step):
            raise ValueError('aggregate 只读：$out 和 $merge 会写库，这里不做')
        limit = max(1, min(int(limit or LIMIT), MOST))
        rows = list(self.collection(name).aggregate(list(pipeline) + [{'$limit': limit}]))
        first = next((step['$match'] for step in pipeline if '$match' in step), {})
        return self._answer(name, first, rows, pipeline=_plain(pipeline), limit=limit)

    def place(self, code):
        """Which conversation a place code (g + six hex, as her notes and plans name places) stands for."""
        from .evidence import sha
        code = str(code).strip()
        found = [scene for scene in self.db.scenes.find({}, {'_id': 1, 'kind': 1})
                 if 'g' + sha(str(scene['_id']).encode())[:6] == code]
        return self._answer('scenes', {'place': code}, [{'place': code, 'scene_id': scene['_id'], 'kind': scene.get('kind')}
                                                         for scene in found])

    def history(self, scene_id, query=None, fields=None, limit=LIMIT):
        """A conversation's lines: the live ones and, for a group, the archived ones (scene_id archive:<id>)."""
        live = self.find('messages', {**(query or {}), 'scene_id': scene_id}, fields, [('scene_seq', -1)], limit)
        old = self.find('messages', {**(query or {}), 'scene_id': 'archive:' + scene_id}, fields,
                        [('occurred_at', -1)], limit)
        return {'live': live, 'archive': old}


_reader = None


def _default():
    global _reader
    if _reader is None:
        _reader = Reader.from_host()
    return _reader


def find(name, query=None, fields=None, sort=None, limit=LIMIT, skip=0):
    return _default().find(name, query, fields, sort, limit, skip)


def count(name, query=None):
    return _default().count(name, query)


def distinct(name, field, query=None):
    return _default().distinct(name, field, query)


def aggregate(name, pipeline, limit=LIMIT):
    return _default().aggregate(name, pipeline, limit)


def history(scene_id, query=None, fields=None, limit=LIMIT):
    return _default().history(scene_id, query, fields, limit)


def place(code):
    return _default().place(code)


def fields(name):
    reader = _default()
    reader.collection(name)
    return sorted(reader.fields(name))


def collections():
    return sorted(_default().db.list_collection_names())


def show(answer):
    """Print an answer whole, query first, as JSON."""
    print(json.dumps(answer, ensure_ascii=False, indent=1, default=str))


def environment(config, zone):
    """What the Host gives a home task's commands: the database and her time zone."""
    if not (config.get('mongo_uri') and config.get('database')):
        return {}
    return {ENV['uri']: config['mongo_uri'], ENV['database']: config['database'], **({ENV['zone']: zone} if zone else {})}
