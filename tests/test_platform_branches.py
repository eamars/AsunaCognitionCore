"""ADR-019 §3.1 (owner 2026-10-07): Asuna inherits DSH's platform layer and assumes no host OS. What a platform does
differently (sandbox, processes, plugin installation) is DSH's. Asuna branches on the OS only where Node or Python
themselves differ: executable names and venv layout. Every such file is listed here with why; a new branch is a
change to this list, seen in review."""
import re
import subprocess

from asuna.config import ROOT

ALLOWED = {
    'src/asuna/queue.py': 'cross-process byte locks: msvcrt on Windows, fcntl elsewhere',
    'packages/cognition-core/src/python-env.js': 'venv layout (Scripts/python.exe or bin/python) and Python launcher names',
    'packages/cognition-core/src/floor.js': 'npm pack goes through cmd.exe as npm.cmd on Windows',
    'tools/asuna-launch.mjs': 'pnpm/corepack shim names; the checkout venv layout',
    'tools/pack_plugins.py': 'npm or npm.cmd',
    'tools/setup_native_profile.py': 'pnpm/corepack shim names',
}
# What runs, and the start path that installs it. Operator diagnostics in tools/ and tests are outside.
SCOPE = ('src', 'packages', 'tools/asuna-launch.mjs', 'tools/pack_plugins.py', 'tools/setup_native_profile.py')
BRANCH = re.compile(rb'process\.platform|os\.name\b|sys\.platform|platform\.system\(')


def test_only_the_listed_files_branch_on_the_operating_system():
    listed = subprocess.run(['git', 'ls-files', '--', *SCOPE], cwd=ROOT, capture_output=True, text=True,
                            check=True).stdout.split()
    branching = {path for path in listed
                 if not path.startswith('packages/cognition-core/python/')     # pack_plugins' copy of src/asuna
                 and '/test/' not in path and (ROOT / path).is_file() and BRANCH.search((ROOT / path).read_bytes())}
    assert branching == set(ALLOWED), {'unlisted': sorted(branching - set(ALLOWED)),
                                       'no longer branching': sorted(set(ALLOWED) - branching)}
