"""Where commands the worker does not write itself run: DSH's own sandbox (owner 2026-10-06).

The Host wraps a command with `ctx.sandbox.confine` (dsh-sandbox-local: a restricted token on Windows, bubblewrap or
Landlock on Linux, Seatbelt on macOS) and the worker runs the wrapped argv. DSH confines writes to one folder; reads
and the network are not restricted, by the owner's choice: which sessions may run commands at all is decided by the
tools a task is given (coordinator._grants). Backends:
- `dsh`: the Host said at initialize that its sandbox can confine, and the worker asks it per command.
- `none`: no Host sandbox, or turned off in the settings (`sandbox.backend: none`). Everything that runs commands is
  off — sandbox_run, managed integration, persona jobs and self-development — and her context says so.
"""
from __future__ import annotations

from pathlib import Path
import sys

BACKENDS = ('auto', 'none')
_CONFINE = {'call': None}


def attach(confine):
    """The worker's way to ask the Host: confine(argv, root) -> wrapped argv. None detaches (tests, shutdown)."""
    _CONFINE['call'] = confine


def validate(setting):
    if setting is None:
        return
    if not isinstance(setting, dict) or set(setting) - {'backend'}:
        raise ValueError('INVALID_SANDBOX_SETTING: sandbox takes backend')
    if setting.get('backend', 'auto') not in BACKENDS:
        raise ValueError('INVALID_SANDBOX_SETTING: backend is one of ' + ', '.join(BACKENDS))


def chosen(config):
    """{'backend', 'reason', 'reason_code'} for this worker: a reason the program words has a code the settings card
    shows in the viewer's language; the Host's own reason is passed as it is."""
    setting = config.get('sandbox') or {}
    validate(setting)
    if setting.get('backend') == 'none':
        return {'backend': 'none', 'reason': 'turned off in the settings', 'reason_code': 'off'}
    host = config.get('_host_sandbox') or {}
    if _CONFINE['call'] is None or not host.get('available'):
        return {'backend': 'none', 'reason': host.get('reason') or 'the Host has no sandbox',
                **({} if host.get('reason') else {'reason_code': 'no_host'})}
    return {'backend': 'dsh', 'reason': None, 'enforcement': host.get('enforcement')}


def available(config):
    return chosen(config)['backend'] != 'none'


def require(config):
    sandbox = chosen(config)
    if sandbox['backend'] == 'none':
        raise PermissionError('SANDBOX_UNAVAILABLE: 这台宿主没有可用的沙箱（%s），命令跑不了；重试也一样：'
                              '不跑命令能做的先做，要跑命令的那一步写进报告' % sandbox['reason'])
    return sandbox


def confine(config, argv, root):
    """The Host's wrapped argv that runs `argv` with writes confined to `root`."""
    require(config)
    wrapped = _CONFINE['call'](list(argv), str(root))
    if not isinstance(wrapped, list) or not wrapped or not all(isinstance(arg, str) for arg in wrapped):
        raise RuntimeError('SANDBOX_CONFINE_FAILED: 宿主没能给这个命令套上沙箱，命令没有运行；不是参数的问题，'
                           '重试也一样：要跑命令的那一步写进报告')
    return wrapped


SITE = Path(__file__).with_name('sandbox_site')   # sitecustomize for the Pythons a confined command starts
TEMP_FOLDER = '.tmp'                             # inside the command's own folder: the only place it may write
# Windows gives a restricted token no SSPI credentials, so Schannel (Git for Windows' default TLS) fails there with
# SEC_E_NO_CREDENTIALS: git uses its bundled OpenSSL and CA file instead. Its credential helpers start through sh.exe,
# which cannot start there either: the list is emptied (her commands log in through git_login). Elsewhere git may
# have only one TLS backend and would refuse the setting (ADR-065).
GIT_CONFIG = ({'GIT_CONFIG_COUNT': '2', 'GIT_CONFIG_KEY_0': 'http.sslBackend', 'GIT_CONFIG_VALUE_0': 'openssl',
               'GIT_CONFIG_KEY_1': 'credential.helper', 'GIT_CONFIG_VALUE_1': ''} if sys.platform == 'win32' else {})


def environment(extra=None, cwd=None):
    """What a confined command inherits: enough for Windows and Python to start, no credentials. Its temporary folder
    is one inside its own folder (the system's is not writable there), and its Pythons make folders it can use."""
    import os
    keep = ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PATH', 'TEMP', 'TMP', 'SYSTEMDRIVE', 'PROGRAMDATA',
            'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'LANG', 'HOME', 'USERPROFILE')
    env = {key: os.environ[key] for key in keep if key in os.environ}
    # A nested `python3` falls through PATH to the Windows Python install manager, which would install a whole
    # Python into the working folder (it has no LOCALAPPDATA here); it answers "no runtimes" instead.
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
               PYTHON_MANAGER_AUTOMATIC_INSTALL='false',
               # Nobody can answer a prompt here: git fails at once instead of waiting out the command's time.
               GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never', PYTHONPATH=str(SITE), **GIT_CONFIG)
    if cwd is not None:
        temp = Path(cwd) / TEMP_FOLDER
        temp.mkdir(parents=True, exist_ok=True)
        env.update(TEMP=str(temp), TMP=str(temp), TMPDIR=str(temp))
    env.update(extra or {})
    return env


def git_login():
    """How git in her own commands (sandbox_run) logs in to an HTTPS remote: with the Host user's login (owner
    2026-10-13). On Windows git starts the askpass program in sandbox_site directly, which asks the credential manager;
    elsewhere git's own credential helpers work in the sandbox."""
    if sys.platform != 'win32':
        return {}
    return {'GIT_ASKPASS': str(SITE / 'git-askpass.cmd'), 'ASUNA_PYTHON': sys.executable}


def git_identity(config):
    """The character's own name on what her commands commit (`character_git` {name, email} in local config), or {}.
    Pushing (git_login) and ssh use the Host user's logins; only the name on her commits is hers."""
    who = (config or {}).get('character_git') or {}
    name, email = str(who.get('name') or '').strip(), str(who.get('email') or '').strip()
    if not (name and email):
        return {}
    return {'GIT_AUTHOR_NAME': name, 'GIT_AUTHOR_EMAIL': email, 'GIT_COMMITTER_NAME': name, 'GIT_COMMITTER_EMAIL': email}
