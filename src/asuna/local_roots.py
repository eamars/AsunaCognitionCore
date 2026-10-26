"""No local root of this computer reaches her character brain (ADR-098): the root table and its two directions.

The table is built at every worker start from the settings and the machine (`machine`, `build`) and handed to the Host
plugin with the worker's `initialize` answer (`Table.wire`): the plugin rewrites every request of her lanes with it
(packages/cognition-core/src/roots.js), so both sides apply one table. A known root becomes `${ASUNA_<NAME>}` and the
rest of the path stays as it was:

- `WORKSPACE` the checkout, `DATA` the worker's data folder, `DSH_HOME` DSH's home and `TEMP` the temporary folder (each
  of the last two only when not under another root), `HOME` the user's home; the deepest root wins;
- `PROGRAMS` the program folders (Windows: Program Files, ProgramData, the system folder; POSIX: `/usr`, `/opt`, ...),
  their own folder name kept (`${ASUNA_PROGRAMS}\\Program Files\\...`, `${ASUNA_PROGRAMS}/usr/...`);
- `DRIVE_<X>` any other path on drive X (Windows, and WSL's `/mnt/x`); on POSIX each mount point by letter or index;
- `FS` any other path of this machine's own tree on POSIX (`/` itself, the tail kept);
- `LOCAL_PATH` a network share, or another account's home beside the user's (`Public`, `Default`, `Default User`,
  `All Users` and `Shared` are nobody's and stay paths), nothing of it kept;
- `USER` the OS account name, exactly that string, as a whole word (not a generic account such as `root`).

Each root matches in every spelling: as configured and resolved, its 8.3 alias, either slash kind at each step, doubled
backslashes (JSON), percent-encoded, WSL's `/mnt/x/...` and MSYS's `/x/...`, after `/`, `(`, a quote or `file:///`,
case-insensitive on Windows, with or without a tail. `/task/...` (the action brain's sandbox path) is not a root.

Toward the action brain (`outbound`): a placeholder the place may hand over expands to the real path (public: only
WORKSPACE and DATA; home: all but LOCAL_PATH); one it may not hand over stays as written; refused, with the reason:
a raw root (with the whole string rewritten), an `${ASUNA_...}` name not in the table, a `..` segment in a path
anchored at a root or placeholder, and in a public place a bare relative path that climbs. Every other `${...}` is
text. The case file `tests/fixtures/path_placeholders.json` runs in pytest and `node --test` alike.
"""
from __future__ import annotations

import getpass
import glob
import os
import re
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import quote

VERSION = 1
PREFIX = 'ASUNA_'
WORKSPACE, DATA, DSH_HOME, HOME, TEMP = 'WORKSPACE', 'DATA', 'DSH_HOME', 'HOME', 'TEMP'
PROGRAMS, FS, LOCAL_PATH, USER, DRIVE = 'PROGRAMS', 'FS', 'LOCAL_PATH', 'USER', 'DRIVE_'
PUBLIC_HANDS = (WORKSPACE, DATA)               # what a public place may hand to the action brain
NEVER_HANDS = (LOCAL_PATH,)
SANDBOX = 'task'                               # /task/... is the action brain's own folder, never a root
# Accounts whose name identifies nobody: replacing them would rewrite ordinary words (root, node, the image's user).
GENERIC_ACCOUNTS = frozenset(('root', 'admin', 'administrator', 'user', 'guest', 'nobody', 'ubuntu', 'debian',
                              'node', 'app', 'runner', 'vagrant', 'asuna', 'default', 'system'))
USER_MIN = 3
POSIX_PROGRAMS = ('usr', 'opt', 'etc', 'bin', 'sbin', 'lib', 'lib32', 'lib64', 'libx32', 'snap', 'nix',
                  'Applications', 'Library', 'System')
WINDOWS_PROGRAMS = ('ProgramFiles', 'ProgramFiles(x86)', 'ProgramW6432', 'ProgramData', 'SystemRoot')
MOUNT_GLOBS = ('/mnt/*', '/media/*/*', '/run/media/*/*', '/Volumes/*')
# Audit events: the plugin's counts of her rewritten requests, its refusal for want of a table, her speech replaced.
TALLY, REFUSED_EVENT, SPEECH_EVENT = 'roots.tally', 'roots.refused', 'roots.speech_replaced'

TOKEN = re.compile(r'\$\{ASUNA_([^{}\s]*)\}')
TOKEN_TAIL = re.compile(r'\$\{ASUNA_([^{}\s]*)\}([^\s"\'<>|*?`()（）「」『』【】，。；：、！？,;]*)')
# The pieces both engines compile (Python re and JavaScript RegExp read these the same way).
_BEFORE_WIN = r'(?<![A-Za-z0-9_])'
_BEFORE_POSIX = r'(?:(?<=file://)|(?<![A-Za-z0-9_.~\-/\\}]))'
_SEP_WIN = r'(?:\\+|/|%5[Cc]|%2[Ff])'
_SEP_POSIX = r'(?:/|%2[Ff])'
_COLON = r'(?::|%3[Aa])'
_AFTER = r'(?![A-Za-z0-9_~$-]|\.[A-Za-z0-9_]|%(?!5[Cc]|2[Ff]))'
_TAIL = r'[^\s"\'<>|*?`()（）「」『』【】，。；：、！？,;]*'         # the rest of a path that is replaced whole
_SHARE = (r'(?<![A-Za-z0-9_:/\\}])((?:\\{2,8}[^\s\\/"\'<>|*?`]{2,}(?:\\+|/)|//[A-Za-z0-9_$-]{2,}/)'
          r'[^\s\\/"\'<>|*?`]+' + _TAIL + r'|smb://[^\s"\'<>]+)')
# Profile folders beside the home that belong to no one (Windows and macOS): they stay paths with their tails.
SHARED_PROFILES = ('Public', 'Default', 'Default User', 'All Users', 'Shared')
_CLIMB_BARE = re.compile(r'(?:^|(?<=[\s"\'`(=]))\.\.(?=[\\/]|\s|$|["\'`)])', re.MULTILINE)
_SPECIAL = set('\\^$.|?*+()[]{}')


class TableRefused(ValueError):
    """A root the table cannot hold (a filesystem or drive root): her lanes do not start on it."""


class PathRefused(ValueError):
    """A path she wrote toward the action brain that cannot go as it is: `CODE: words`."""


def _lit(text, fold=False):
    """A literal for both engines; `fold` spells each letter in both cases (Windows paths), so no flag is needed and
    the account name stays exact."""
    out = []
    for c in text:
        if c in _SPECIAL:
            out.append('\\' + c)
        elif fold and c.lower() != c.upper() and len(c.lower()) == len(c.upper()) == 1:
            out.append('[%s%s]' % (c.lower(), c.upper()))
        else:
            out.append(c)
    return ''.join(out)


def _segment(seg, fold):
    forms = list(dict.fromkeys((seg, quote(seg, safe=''))))
    return _lit(forms[0], fold) if len(forms) == 1 else '(?:%s)' % '|'.join(_lit(f, fold) for f in forms)


def _pure(windows, path):
    return PureWindowsPath(path) if windows else PurePosixPath(path)


def _is_fs_root(windows, path):
    pure = _pure(windows, path)
    return pure == pure.parent or (windows and not pure.drive[1:2] == ':') or not pure.is_absolute()


def _under(windows, path, other):
    a, b = _pure(windows, path), _pure(windows, other)
    if windows:
        a, b = PureWindowsPath(str(a).lower()), PureWindowsPath(str(b).lower())
    return a == b or b in a.parents


def machine(checkout=None, dsh_home=None):
    """This machine's facts for `build`: the configured roots, their other spellings, program folders, drives or
    mounts and the account name. `checkout` is the Host's repository root (the installed package's root without one),
    `dsh_home` DSH's home."""
    from .config import DATA as data_root, ROOT
    windows = os.name == 'nt'
    try:
        user = getpass.getuser()
    except Exception:
        user = None
    facts = {'os': 'windows' if windows else 'posix', 'workspace': str(Path(checkout).resolve() if checkout else ROOT),
             'data': str(data_root), 'dsh_home': str(Path(dsh_home).resolve()) if dsh_home else
             (str(Path(os.environ['DSH_HOME']).resolve()) if os.environ.get('DSH_HOME') else None),
             'home': str(Path.home()), 'temp': tempfile.gettempdir(), 'user': user, 'aliases': {}}
    if windows:
        facts['programs'] = list(dict.fromkeys(os.environ[k] for k in WINDOWS_PROGRAMS if os.environ.get(k)))
        drives = getattr(os, 'listdrives', None)
        letters = [d[0] for d in drives()] if drives else [c for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
                                                            if os.path.exists(c + ':\\')]
        facts['drives'] = sorted({c.upper() for c in letters if c.isalpha()})
    else:
        facts['programs'] = ['/' + name for name in POSIX_PROGRAMS if os.path.isdir('/' + name)
                             and not os.path.islink('/' + name)]
        facts['mounts'] = sorted(p for pattern in MOUNT_GLOBS for p in glob.glob(pattern)
                                 if os.path.isdir(p) and os.path.realpath(p) != '/')
        try:
            facts['top'] = sorted(n for n in os.listdir('/') if os.path.isdir('/' + n) and n != SANDBOX)
        except OSError:
            facts['top'] = []
    for key in ('workspace', 'data', 'dsh_home', 'home', 'temp'):
        path = facts.get(key)
        if not path:
            continue
        forms = [os.path.realpath(path)]
        if windows:
            forms.append(_short_name(path))
        facts['aliases'][path] = [f for f in dict.fromkeys(forms) if f and f != path]
    return facts


def _short_name(path):
    """The 8.3 alias of a Windows path, or None."""
    try:
        import ctypes
        buffer = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 1024)
        return buffer.value if 0 < n < 1024 else None
    except Exception:
        return None


class Table:
    """One machine's roots: `contract` (toward her), `outbound` (toward the action brain), `wire` (for the plugin)."""

    def __init__(self, facts):
        self.windows = facts['os'] == 'windows'
        w = self.windows
        roots, values = [], {}
        given = [(WORKSPACE, facts.get('workspace')), (DATA, facts.get('data'))]
        for name, path in given:
            if not path:
                raise TableRefused('ROOT_TABLE_REFUSED: 没有 %s 的路径' % name)
            if _is_fs_root(w, path):
                raise TableRefused('ROOT_TABLE_REFUSED: %s 是文件系统或盘符的根（%s），不能当作一个根' % (name, path))
            roots.append((name, path))
        home = facts.get('home')
        dsh = facts.get('dsh_home')
        if dsh:
            if _is_fs_root(w, dsh):
                raise TableRefused('ROOT_TABLE_REFUSED: DSH_HOME 是文件系统或盘符的根（%s），不能当作一个根' % dsh)
            if not any(_under(w, dsh, p) for _, p in roots + ([(HOME, home)] if home else [])):
                roots.append((DSH_HOME, dsh))
        if home and not _is_fs_root(w, home):
            roots.append((HOME, home))
        temp = facts.get('temp')
        if temp and not _is_fs_root(w, temp) and not any(_under(w, temp, p) for _, p in roots):
            roots.append((TEMP, temp))
        values.update({name: path for name, path in roots})
        aliases = facts.get('aliases') or {}
        named = []                                   # (length, name, spelling)
        for name, path in roots:
            for form in [path, *aliases.get(path, ())]:
                if form and not _is_fs_root(w, form):
                    named.append((len(form.rstrip('\\/')), name, form))
        self.drives = sorted(facts.get('drives') or ())
        self.mounts = {}
        if not w:
            index = 0
            for path in facts.get('mounts') or ():
                last = PurePosixPath(path).name
                if PurePosixPath(path).parent == PurePosixPath('/mnt') and len(last) == 1 and last.isalpha():
                    name = DRIVE + last.upper()
                else:
                    index += 1
                    name = DRIVE + str(index)
                self.mounts[name] = path
                named.append((len(path), name, path))
        values.update(self.mounts)
        if w:
            values.update({DRIVE + d: d + ':' for d in self.drives})
        programs = [p for p in facts.get('programs') or () if not _is_fs_root(w, p)]
        if programs:
            values[PROGRAMS] = PureWindowsPath(programs[0]).drive if w else ''
        if not w:
            values[FS] = ''
        user = facts.get('user')
        self.user = user if user and len(user) >= USER_MIN and user.lower() not in GENERIC_ACCOUNTS else None
        if self.user:
            values[USER] = self.user
        self.values = values                         # name -> what it expands to
        self.roots = roots
        self.names = sorted(set(values) | {LOCAL_PATH})
        # The alternatives, in order: named roots deepest first, program folders, drives, shares, the tree, the user.
        parts, groups = [], []
        seen = set()
        for _, name, form in sorted(named, key=lambda item: -item[0]):
            key = form.lower() if w else form
            if key in seen:
                continue
            seen.add(key)
            parts.append(self._root_pattern(form))
            groups.append(name)
        for path in programs:
            parts.append(self._program_pattern(path))
            groups.append(PROGRAMS)
        # Another account's home beside the user's (C:\Users\<other>, /home/<other>): a person's folder name, so the
        # whole path is LOCAL_PATH with nothing kept; the home itself and the shared ones are not.
        if home and not _is_fs_root(w, home):
            parents = {}
            for form in [home, *aliases.get(home, ())]:
                parent = str(_pure(w, form).parent)
                if form and not _is_fs_root(w, parent):
                    parents.setdefault(parent.lower() if w else parent, (parent, _pure(w, form).name))
            for parent, own in parents.values():
                parts.append(self._sibling_pattern(parent, own))
                groups.append(LOCAL_PATH)
        if w:
            parts.append(_BEFORE_WIN + '([A-Za-z]' + _COLON + ')(?=' + _SEP_WIN + ')')
            groups.append(DRIVE)
            parts.append(_BEFORE_POSIX + '((?:/|%2[Ff])' + _lit('mnt', True) + _SEP_POSIX + '[A-Za-z])' + _AFTER)
            groups.append(DRIVE)
        parts.append(_SHARE)
        groups.append(LOCAL_PATH)
        if not w and facts.get('top'):
            tops = [t for t in facts['top'] if t != SANDBOX]
            if tops:
                parts.append(_BEFORE_POSIX + '()(?=' + _SEP_POSIX + '(?:' + '|'.join(_lit(t) for t in tops) + ')'
                             + _AFTER + ')')
                groups.append(FS)
        if self.user:
            parts.append(r'(?<![A-Za-z0-9_])(' + _lit(self.user) + r')(?![A-Za-z0-9_])')
            groups.append(USER)
        self.source = '|'.join(parts)
        self.groups = groups
        self.pattern = re.compile(self.source)

    def _root_pattern(self, form):
        if self.windows:
            pure = PureWindowsPath(form)
            letter = _lit(pure.drive[0], True)
            head = ('(?:' + letter + _COLON + '|(?:/|%2[Ff])' + _lit('mnt', True) + _SEP_POSIX + letter + '|/'
                    + letter + ')')
            return (_BEFORE_WIN + '(' + head + ''.join(_SEP_WIN + _segment(s, True) for s in pure.parts[1:]) + ')'
                    + _AFTER)
        pure = PurePosixPath(form)
        return _BEFORE_POSIX + '(' + ''.join(_SEP_POSIX + _segment(s, False) for s in pure.parts[1:]) + ')' + _AFTER

    def _sibling_pattern(self, parent, own):
        """A folder beside the home under its parent, not the home and not a shared one, with all that follows."""
        w = self.windows
        sep = _SEP_WIN if w else _SEP_POSIX
        skip = '|'.join(_lit(name, w) for name in (own, *SHARED_PROFILES))
        if w:
            pure = PureWindowsPath(parent)
            letter = _lit(pure.drive[0], True)
            before = _BEFORE_WIN
            head = ('(?:' + letter + _COLON + '|(?:/|%2[Ff])' + _lit('mnt', True) + _SEP_POSIX + letter + '|/' + letter
                    + ')' + ''.join(_SEP_WIN + _segment(s, True) for s in pure.parts[1:]))
            name = r'[^\s\\/"\'<>|*?`%]+'
        else:
            before = _BEFORE_POSIX
            head = ''.join(_SEP_POSIX + _segment(s, False) for s in PurePosixPath(parent).parts[1:])
            name = r'[^\s/"\'<>|*?`%]+'
        return before + '(' + head + sep + '(?!(?:' + skip + ')' + _AFTER + ')' + name + _TAIL + ')'

    def _program_pattern(self, path):
        if self.windows:
            pure = PureWindowsPath(path)
            return (_BEFORE_WIN + '(' + _lit(pure.drive[0], True) + _COLON + ')(?='
                    + ''.join(_SEP_WIN + _segment(s, True) for s in pure.parts[1:]) + _AFTER + ')')
        pure = PurePosixPath(path)
        return (_BEFORE_POSIX + '()(?=' + ''.join(_SEP_POSIX + _segment(s, False) for s in pure.parts[1:]) + _AFTER
                + ')')

    def _name(self, match):
        index = match.lastindex
        name = self.groups[index - 1]
        if name == DRIVE:
            name = DRIVE + match.group(index)[-1 if match.group(index).lower().startswith(('/', '%2f')) else 0].upper()
        return name

    def contract_text(self, text):
        """(the text with every root of this machine written as its placeholder, how many were replaced)."""
        count = 0

        def one(match):
            nonlocal count
            count += 1
            return '${' + PREFIX + self._name(match) + '}'
        return self.pattern.sub(one, text), count

    def contract(self, value):
        """The same value with every string in it contracted (dicts and lists walked; keys kept)."""
        if isinstance(value, str):
            return self.contract_text(value)[0]
        if isinstance(value, dict):
            return {key: self.contract(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.contract(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.contract(item) for item in value)
        return value

    def hands(self, name, home):
        """Whether a place (home or public) hands this placeholder over as its real path."""
        if name in NEVER_HANDS or name not in self.values:
            return False
        return home or name in PUBLIC_HANDS

    def problems(self, text, home):
        """What keeps a text she wrote toward the action brain from going as it is: [(code, words)]."""
        out = []
        unknown = sorted({m.group(1) for m in TOKEN.finditer(text) if m.group(1) not in self.names})
        if unknown:
            out.append(('PATH_NAME_UNKNOWN', '%s 不是程序的名字；程序的名字只有这些：%s，照抄其中一个' % (
                '、'.join('${%s%s}' % (PREFIX, n) for n in unknown),
                '、'.join('${%s%s}' % (PREFIX, n) for n in self.names))))
        anchored = [m.group(0) for m in TOKEN_TAIL.finditer(text) if _climbs(m.group(2))]
        contracted, _ = self.contract_text(text)
        # A raw root is a path; the account name alone is not one (the action brain may read it as she wrote it).
        raw = sum(1 for m in self.pattern.finditer(text) if self._name(m) != USER)
        anchored += [m.group(0) for m in TOKEN_TAIL.finditer(contracted) if _climbs(m.group(2))
                     and m.group(0) not in text]
        if anchored:
            out.append(('PATH_CLIMBS', '路径里有 ..（「%s」）：挂在根上的路径不往上爬，直接写到要去的那一层'
                        % '」「'.join(dict.fromkeys(anchored))))
        if not home and _CLIMB_BARE.search(TOKEN_TAIL.sub('', contracted)):
            out.append(('PATH_CLIMBS_HERE', '这条线从严：相对路径里的 ..（往上一层）在这里不交出去；换成挂在 '
                        '${ASUNA_WORKSPACE} 上的写法，或者从家里派'))
        if raw:
            if out:
                out.append(('PATH_RAW_ROOT', '还写了本机的真实路径：路径写成挂在 ${ASUNA_…} 上的样子'))
            else:
                out.append(('PATH_RAW_ROOT', '写了本机的真实路径：路径写成挂在 ${ASUNA_…} 上的样子；'
                            '改成这样就能交：\n' + contracted))
        return out

    def expand(self, text, home):
        """Every placeholder this place hands over written as its real path, the tail's separators the host's own;
        the others as written."""
        sep = '\\' if self.windows else '/'

        def one(match):
            name, tail = match.group(1), match.group(2)
            if not self.hands(name, home):
                return match.group(0)
            return self.values[name] + re.sub(r'[\\/]+', lambda _: sep, tail)
        return TOKEN_TAIL.sub(one, text)

    def outbound(self, text, home):
        """A text she wrote toward the action brain, ready to go: expanded, or PathRefused with the reasons."""
        found = self.problems(text, home)
        if found:
            raise PathRefused('%s: %s' % (found[0][0], '；'.join(words for _, words in found)))
        return self.expand(text, home)

    def wire(self):
        """What the plugin needs to rewrite her requests: the pattern's source (no flags) and each group's name."""
        return {'version': VERSION, 'os': 'windows' if self.windows else 'posix', 'source': self.source,
                'groups': self.groups, 'roots': len(self.roots) + len(self.mounts),
                'names': self.names}


def _climbs(tail):
    return any(part == '..' for part in re.split(r'[\\/]+|%5[Cc]|%2[Ff]', tail or ''))


def build(facts):
    """The table of these facts (TableRefused for a filesystem or drive root as a named root)."""
    return Table(facts)


TABLE = None                                     # this worker's table (`attach`); None until it starts
REFUSED = None                                   # why it has none, when the build refused


def attach(checkout=None, dsh_home=None, facts=None):
    """Build this worker's table from the machine (or the given facts); its wire, or None with REFUSED set."""
    global TABLE, REFUSED
    try:
        TABLE, REFUSED = build(facts or machine(checkout, dsh_home)), None
    except TableRefused as exc:
        TABLE, REFUSED = None, str(exc)
    return TABLE.wire() if TABLE else None


def current():
    """This worker's table; a process that never attached one (a tool, a test) builds it from the machine once. A
    worker whose build refused has none."""
    if TABLE is None and REFUSED is None:
        attach()
    return TABLE


def contract(value):
    """`Table.contract` with this worker's table (the value as it is without one)."""
    table = current()
    return table.contract(value) if table else value


def contract_text(text):
    table = current()
    return table.contract_text(text) if table else (text, 0)


def speech(store, ep, text):
    """Her words about to leave, with a raw root written as its placeholder (D5). A replacement is a fault to look at
    (the rewrite at the model failed, or a model invented a root): each is counted, never its text."""
    out, count = contract_text(text)
    if count:
        store.audit(ep['_id'], SPEECH_EVENT, {'count': count, 'scene_id': ep.get('scene_id')}, ep['scope_key'])
    return out


def outbound(text, home):
    """`Table.outbound` with this worker's table; without one, any placeholder is refused."""
    if current() is None:
        if TOKEN.search(text or ''):
            raise PathRefused('PATH_TABLE_MISSING: 程序这次没有建好路径表（不是你的错），占位名交不出去；重试也一样，'
                              '先别写路径')
        return text
    return TABLE.outbound(text, home)


def context_line(home):
    """Her program context's line on the placeholders: names and meanings, never values."""
    hands = '家里能交给行动脑的是除 ${ASUNA_LOCAL_PATH} 外的全部' if home else \
        '这里（对外的对话）能交给行动脑的只有 ${ASUNA_WORKSPACE} 和 ${ASUNA_DATA}；别的可以照样提一句，原样过去，行动脑在这里打不开'
    return ('路径里的 ${ASUNA_…} 是程序替你藏起本机真实根目录的名字（只有 ${ASUNA_ 开头的才是程序的，别的 ${…} 是普通文字）：'
            'WORKSPACE 程序的源码目录，DATA 程序的数据目录，DSH_HOME 宿主 DSH 的目录，HOME 用户目录，TEMP 临时目录，'
            'PROGRAMS 装程序的目录，DRIVE_X 某个盘，FS 这台机器的文件树，LOCAL_PATH 网络共享或别的账号的目录（什么都不留），USER 本机账号名。'
            '交给行动脑时照这样写，程序替你换成真路径；%s。旧报告里的〔本机路径〕和从源码目录算起的相对路径也是藏起来的路径。'
            % hands)
