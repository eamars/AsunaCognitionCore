"""Where code the worker does not trust runs (ADR-010 D5): one choice per worker, read by every sandboxed path.

Backends:
- `wsl-bwrap`: Windows, bubblewrap inside a WSL distro (`sandbox.wsl_distro`, default Ubuntu). This is what the
  action brain's sandbox_run, the managed integration process and persona jobs have always used.
- `none`: no sandbox on this machine, or turned off in the settings. Everything that needs one is off — sandbox_run,
  managed integration, persona jobs and self-development — and her context says so instead of offering them.

The setting `sandbox.backend` is `auto` (default), `wsl-bwrap` or `none`. `auto` takes wsl-bwrap when its probe
passes and `none` otherwise, with the probe's reason. A Linux `bwrap` backend is the next one (ADR-010 M3 starts
with these two).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

BACKENDS = ('auto', 'wsl-bwrap', 'none')
DEFAULT_DISTRO = 'Ubuntu'
_PROBES: dict = {}


def _probe_wsl(distro):
    """(ok, reason) for bubblewrap, python3 and prlimit inside the distro; probed once per process."""
    if distro in _PROBES:
        return _PROBES[distro]
    if os.name != 'nt':
        result = (False, 'wsl-bwrap needs Windows with WSL')
    else:
        try:
            probe = subprocess.run(['wsl', '-d', distro, '--exec', 'sh', '-c',
                                    'command -v bwrap && command -v python3 && command -v prlimit'],
                                   stdin=subprocess.DEVNULL, capture_output=True, timeout=60)   # never the worker's pipe
            result = (True, None) if probe.returncode == 0 else (
                False, 'WSL distro %s lacks bubblewrap, python3 or prlimit (exit %d)' % (distro, probe.returncode))
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = (False, 'WSL is not available: ' + type(exc).__name__)
    _PROBES[distro] = result
    return result


def validate(setting):
    if setting is None:
        return
    if not isinstance(setting, dict) or set(setting) - {'backend', 'wsl_distro'}:
        raise ValueError('INVALID_SANDBOX_SETTING: sandbox takes backend and wsl_distro')
    if setting.get('backend', 'auto') not in BACKENDS:
        raise ValueError('INVALID_SANDBOX_SETTING: backend is one of ' + ', '.join(BACKENDS))
    distro = setting.get('wsl_distro', DEFAULT_DISTRO)
    if not isinstance(distro, str) or not distro or not distro.replace('-', '').replace('.', '').replace('_', '').isalnum():
        raise ValueError('INVALID_SANDBOX_SETTING: wsl_distro')


def chosen(config):
    """{'backend', 'reason', 'distro'} for this worker, decided once and kept in the config."""
    if isinstance(config.get('_sandbox'), dict):
        return config['_sandbox']
    setting = config.get('sandbox') or {}
    validate(setting)
    want, distro = setting.get('backend', 'auto'), setting.get('wsl_distro', DEFAULT_DISTRO)
    if want == 'none':
        value = {'backend': 'none', 'reason': 'turned off in the settings', 'distro': None}
    else:
        ok, reason = _probe_wsl(distro)
        if not ok and want == 'wsl-bwrap':
            raise ValueError('SANDBOX_UNAVAILABLE: ' + reason)
        value = {'backend': 'wsl-bwrap', 'reason': None, 'distro': distro} if ok else \
            {'backend': 'none', 'reason': reason, 'distro': None}
    config['_sandbox'] = value
    return value


def available(config):
    return chosen(config)['backend'] != 'none'


def require(config):
    sandbox = chosen(config)
    if sandbox['backend'] == 'none':
        raise PermissionError('SANDBOX_UNAVAILABLE: ' + sandbox['reason'])
    return sandbox


def prefix(sandbox):
    """What runs a Linux command under this backend."""
    return ['wsl', '-d', sandbox['distro'], '--exec']


def path(sandbox, host_path):
    """A host path as the sandbox sees it."""
    p = Path(host_path).resolve()
    return '/mnt/' + p.drive[0].lower() + p.as_posix()[2:]
