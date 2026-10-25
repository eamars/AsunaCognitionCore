"""The installer's profile patch: the local files seed the core's deployment once; after that the saved one is it."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import setup_native_profile  # noqa: E402


def defaults(channels):
    return [{'id': 'web', 'config': {'searchProvider': 'asuna-search'}},
            {'id': 'asuna-cognition-core', 'config': {'python': 'new-python', 'persona': 'p',
                                                       'deployment': {'channels': channels, 'timezone': 'Etc/UTC'}}}]


def test_a_channel_removed_from_the_saved_deployment_stays_removed_at_the_next_install():
    saved = [{'id': 'asuna-cognition-core', 'config': {'python': 'old-python', 'channelAdmission': 'explicit',
                                                       'deployment': {'channels': {'qq': {'a': 1}, 'agent': {}},
                                                                      'timezone': 'Etc/GMT-1'}}},
             {'id': 'locale', 'config': {'preference': 'zh'}}]
    merged = setup_native_profile.compose(defaults({'qq': {'a': 2}, 'dsh': {'routes': {}}, 'agent': {}}), saved)
    core = next(row for row in merged if row['id'] == 'asuna-cognition-core')['config']
    assert core['deployment'] == {'channels': {'qq': {'a': 1}, 'agent': {}}, 'timezone': 'Etc/GMT-1'}, \
        'the local files no longer bring back a channel removed on the settings card'
    assert core['python'] == 'old-python' and core['channelAdmission'] == 'explicit', 'other saved fields win as before'
    assert any(row['id'] == 'locale' for row in merged), 'rows this installer does not write are kept'
    assert next(row for row in merged if row['id'] == 'web')['config'] == {'searchProvider': 'asuna-search'}


def test_a_first_install_takes_its_deployment_from_the_local_files():
    merged = setup_native_profile.compose(defaults({'qq': {'a': 2}}), [])
    core = next(row for row in merged if row['id'] == 'asuna-cognition-core')['config']
    assert core['deployment'] == {'channels': {'qq': {'a': 2}}, 'timezone': 'Etc/UTC'}
    saved_without = [{'id': 'asuna-cognition-core', 'config': {'python': 'old-python'}}]
    core = next(row for row in setup_native_profile.compose(defaults({'qq': {}}), saved_without)
                if row['id'] == 'asuna-cognition-core')['config']
    assert core['deployment'] == {'channels': {'qq': {}}, 'timezone': 'Etc/UTC'}, 'a profile with no deployment yet is seeded'
