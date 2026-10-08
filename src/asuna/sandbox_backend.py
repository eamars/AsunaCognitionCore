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


def environment(extra=None):
    """What a confined command inherits: enough for Windows and Python to start, no credentials."""
    import os
    keep = ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PATH', 'TEMP', 'TMP', 'SYSTEMDRIVE', 'PROGRAMDATA',
            'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'LANG', 'HOME', 'USERPROFILE')
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    env.update(extra or {})
    return env
