"""Git's askpass for her confined commands on Windows (ADR-065): asks Git Credential Manager for the Host user's login.

Git starts a credential helper through Git for Windows' sh.exe, which cannot start in the sandbox; an askpass program
it starts directly. Git asks for a username, then a password; this asks the credential manager (never interactively)
for that remote and prints only the part asked for, to git. Nothing goes on a command line or into a file.
"""
import re
import subprocess
import sys
from pathlib import Path


def main(prompt):
    asked = re.match(r"(Username|Password) for '([a-z]+)://(?:([^@']+)@)?([^/']+)", prompt)
    if not asked:
        return 1
    kind, protocol, user, host = asked.groups()
    core = subprocess.run(['git', '--exec-path'], capture_output=True, text=True).stdout.strip()
    manager = Path(core).parents[1] / 'bin' / 'git-credential-manager.exe'
    query = 'protocol=%s\nhost=%s\n%s\n' % (protocol, host, 'username=%s\n' % user if user else '')
    answer = subprocess.run([str(manager), 'get'], input=query, capture_output=True, text=True, timeout=60)
    values = dict(line.split('=', 1) for line in answer.stdout.splitlines() if '=' in line)
    value = values.get('username' if kind == 'Username' else 'password')
    if answer.returncode or not value:
        return 1
    sys.stdout.write(value + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(' '.join(sys.argv[1:])))
