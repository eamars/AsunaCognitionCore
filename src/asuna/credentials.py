"""Her credentials (owner 2026-10-07): secrets a home task may use without any brain holding the value.

A credential is a name, a note on what it is for, and a few environment variables (``ENLIGHTEN_PASSWORD``…). The
values live in DSH's credential store, one record per name (the Host's ``credentialRecords``); the worker asks the
Host for them through ``attach``.

- Filing one: at home, the character brain's ``credential`` tool, when someone hands her a password or token; or the
  owner. The value passes her model once, in that turn; she is told never to repeat it.
- Using one: only the action brain, only in a task that came from home, only inside one sandboxed command
  (``sandbox_run`` with ``credentials``): the variables are set for that process and nothing else. No prompt, brief
  or report carries a value: tool results, her briefs to the action brain and its reports are scrubbed of every
  stored value (``scrub``).
- What a turn sees: names, notes and variable names (``listing``), never a value.

A script that holds a value can still send it anywhere the network reaches; the protection is that no model holds it.
"""
from __future__ import annotations

import re
import threading
import time
from urllib.parse import quote, quote_plus

from .state import Denied

NAME = re.compile(r'[a-z][a-z0-9-]{1,31}')
ENV_NAME = re.compile(r'[A-Z][A-Z0-9_]{1,47}')
# What a sandboxed command needs to start (sandbox_backend.environment): a credential never replaces it.
RESERVED = ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PATH', 'TEMP', 'TMP', 'SYSTEMDRIVE', 'PROGRAMDATA',
            'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'LANG', 'HOME', 'USERPROFILE')
NOTE_CHARS = 80
MAX_VARIABLES = 6
VALUE_CHARS = 4096
HIDDEN = '[凭据已隐藏]'
CACHE_SECONDS = 60
CREDENTIALS_NOTE = ('这些是存在保险箱里的凭据（只有名字和用途，值谁都看不到，你和行动脑都看不到）。要用的时候交代行动脑：'
                    '让它 sandbox_run 时写 credentials（名字照抄），脚本从环境变量里读。交代里、话里都不写值。')

_host = None
_lock = threading.Lock()
_cache = {'at': 0.0, 'listing': [], 'values': set()}


def attach(call):
    """The Host's credential requests: call({'op': 'list'|'read'|'write'|'delete', ...})."""
    global _host
    _host = call
    _cache['at'] = 0.0


def available():
    return _host is not None


def _call(**args):
    if _host is None:
        raise Denied('CREDENTIALS_UNAVAILABLE: 宿主没有提供凭据存储（不是你的错）；重试也一样')
    return _host(args)


def _refresh(force=False):
    """Names, notes and the values to scrub, read again at most once a minute."""
    with _lock:
        if not force and time.monotonic() - _cache['at'] < CACHE_SECONDS:
            return
        listing = list(_call(op='list') or [])
        values = set()
        for item in listing:
            payload = _call(op='read', name=item['name']) or {}
            values.update(str(v) for v in (payload.get('env') or {}).values() if len(str(v)) >= 4)
        _cache.update(at=time.monotonic(), listing=listing, values=values)


def listing():
    """What a home turn or task may see: [{name, note, env: [variable names]}]."""
    if _host is None:
        return []
    try:
        _refresh()
    except Exception:
        return []
    return [{'name': item['name'], 'note': item.get('note') or '', 'env': sorted(item.get('env') or [])}
            for item in _cache['listing']]


def keep(name, note, env):
    """File a credential (a new one, or new values for a name already filed)."""
    name = str(name or '').strip()
    if not NAME.fullmatch(name):
        raise Denied('CREDENTIAL_NAME_INVALID: ' + ('没写 name' if not name else 'name %d 个字符，不合规则' % len(name)))
    note = ' '.join(str(note or '').split())
    if not 1 <= len(note) <= NOTE_CHARS:
        raise Denied('CREDENTIAL_NOTE_INVALID: ' + ('没写 note' if not note else 'note %d 字' % len(note)))
    if not isinstance(env, dict) or not 1 <= len(env) <= MAX_VARIABLES:
        raise Denied('CREDENTIAL_ENV_INVALID: ' + ('env 有 %d 个变量' % len(env) if isinstance(env, dict)
                                                   else 'env 要是一个对象：{"变量名": "值"}'))
    clean = {}
    for key, value in env.items():
        key = str(key).strip()
        if not ENV_NAME.fullmatch(key) or key in RESERVED or key.startswith('PYTHON'):
            raise Denied('CREDENTIAL_ENV_INVALID: 变量名「%s」%s' % (key[:48], '是系统要用的，换一个名字'
                         if key in RESERVED or key.startswith('PYTHON') else '要大写字母开头，只含大写字母、数字、下划线，2–48 个'))
        if not isinstance(value, str) or not value or len(value) > VALUE_CHARS:
            raise Denied('CREDENTIAL_ENV_INVALID: %s 的值要是 1–%d 字的字符串' % (key, VALUE_CHARS))
        clean[key] = value
    _call(op='write', name=name, note=note, env=clean)
    _refresh(force=True)
    return {'kept': name, 'env': sorted(clean), 'note': '收进保险箱了。值不会再出现在任何地方；用的时候只写名字。'}


def _names_hint(names):
    """The vault's names (never values), for a refusal."""
    return '有的是：%s，照抄其中一个' % '、'.join(names) if names else '保险箱是空的'


def drop(name):
    name = str(name or '').strip()
    names = sorted(item['name'] for item in listing())
    if name not in names:
        raise Denied('CREDENTIAL_NOT_FOUND: 保险箱里没有「%s」；%s' % (name[:40], _names_hint(names)))
    _call(op='delete', name=name)
    _refresh(force=True)
    return {'dropped': name}


def environment(names):
    """The variables of these credentials, for one sandboxed command."""
    if isinstance(names, str):
        names = [part.strip() for part in names.split(',') if part.strip()]
    if not isinstance(names, list) or not names or len(names) > 4:
        raise Denied('CREDENTIALS_INVALID: credentials 写 1–4 个凭据名（列表，或逗号分隔）；照抄程序附注 credentials 里的 name')
    env = {}
    for name in names:
        payload = _call(op='read', name=str(name)) if NAME.fullmatch(str(name)) else None
        if not payload or not payload.get('env'):
            raise Denied('CREDENTIAL_NOT_FOUND: 保险箱里没有「%s」；%s'
                         % (str(name)[:40], _names_hint(sorted(item['name'] for item in listing()))))
        env.update({str(k): str(v) for k, v in payload['env'].items()})
        with _lock:
            _cache['values'].update(str(v) for v in payload['env'].values() if len(str(v)) >= 4)
    return env


def scrub(value):
    """The same value with every stored credential value replaced by HIDDEN (strings, lists and dicts)."""
    if _host is None:
        return value
    try:
        _refresh()
    except Exception:
        pass
    secrets = sorted(_cache['values'], key=len, reverse=True)
    if not secrets:
        return value
    variants = {}
    for secret in secrets:
        for form in (secret, quote(secret, safe=''), quote_plus(secret)):
            variants.setdefault(form, HIDDEN)

    def clean(item):
        if isinstance(item, str):
            for form in sorted(variants, key=len, reverse=True):
                if form in item:
                    item = item.replace(form, HIDDEN)
            return item
        if isinstance(item, list):
            return [clean(x) for x in item]
        if isinstance(item, tuple):
            return tuple(clean(x) for x in item)
        if isinstance(item, dict):
            return {k: clean(v) for k, v in item.items()}
        return item
    return clean(value)


def home_task(store, task):
    """Whether this task came from home (credentials are for home tasks only)."""
    from . import visibility
    scene = store.db.scenes.find_one({'_id': task['scene_id']}) or {'_id': task['scene_id']}
    return visibility.session_class(store.config, store.db, scene, task['requester_id']) == visibility.OWNER_PRIVATE
