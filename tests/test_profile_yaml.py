"""The profile DSH writes is YAML 1.2: a model's `off` effort, written bare, stays the word off when the installer
reads the profile and is quoted when it writes it back, so DSH can still load its model providers."""
import sys

import yaml

from asuna.config import ROOT

sys.path.insert(0, str(ROOT / 'tools'))
import setup_native_profile  # noqa: E402


def test_bare_off_stays_a_word_through_read_and_write():
    efforts = setup_native_profile.profile_yaml("reasoningEfforts:\n  off: null\n  low: low\nflag: true\n")
    assert efforts == {'reasoningEfforts': {'off': None, 'low': 'low'}, 'flag': True}
    written = yaml.safe_dump(efforts, allow_unicode=True, sort_keys=False)
    assert "'off': null" in written and setup_native_profile.profile_yaml(written) == efforts
