"""ADR-019 §1 rule 4 (owner 2026-10-07): Docker is a deployment layer on top of DSH. The cognition core and its plugins
neither rely on it nor know about it; everything Docker-specific lives in deploy/docker/."""
import re

from asuna.config import ROOT
from asuna import repo_files

SOURCES = ('src', 'packages')             # what runs: the core and its plugins (tools/ holds operator diagnostics)
BUILT_COPY = 'packages/cognition-core/python/'          # pack_plugins' copy of src/asuna, checked through src


def test_core_and_plugins_do_not_know_about_docker():
    listed = repo_files.files(ROOT, *SOURCES)
    word = re.compile(rb'docker', re.IGNORECASE)
    found = [path for path in listed if not path.startswith(BUILT_COPY) and (ROOT / path).is_file()
             and word.search((ROOT / path).read_bytes())]
    assert not found, 'Docker belongs in deploy/docker/: %s' % found
