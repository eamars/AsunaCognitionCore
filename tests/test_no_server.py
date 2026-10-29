"""A unit run reaches no database server: opening one is refused (DATABASE_IN_UNIT_RUN) in the test process and in a
child process it starts, and every configuration the run loads names an address that cannot resolve."""
import json
import subprocess
import sys

import pytest

from asuna import dbread
from asuna.store import adapters
from asuna.store.errors import InUnitRun
from asuna.testing import suite_config
from conftest import NO_SERVER

SETTINGS = {'mongo_uri': 'mongodb://192.0.2.1:27017/'}      # TEST-NET-1: never a server of ours


def test_opening_or_dropping_a_database_is_refused_in_the_test_process():
    with pytest.raises(InUnitRun, match='DATABASE_IN_UNIT_RUN'):
        adapters.open(SETTINGS, adapters.TEST_PREFIX + 'x')
    with pytest.raises(InUnitRun, match='DATABASE_IN_UNIT_RUN'):
        adapters.drop(SETTINGS, adapters.TEST_PREFIX + 'x')
    with pytest.raises(InUnitRun, match='DATABASE_IN_UNIT_RUN'):
        dbread.Reader.from_host()
    with pytest.raises(InUnitRun, match='DATABASE_IN_UNIT_RUN'):
        dbread.development_rows(SETTINGS, 'x', 'messages', {})


def test_a_child_process_of_the_run_is_refused_too():
    code = ('import json\n'
            'from asuna.store import adapters\n'
            'try:\n'
            '    adapters.open({"mongo_uri": "mongodb://192.0.2.1:27017/"}, "asuna_v2_test_x")\n'
            '    print(json.dumps("opened"))\n'
            'except RuntimeError as error:\n'
            '    print(json.dumps(str(error).split(":")[0]))\n')
    done = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-500:]
    assert json.loads(done.stdout) == 'DATABASE_IN_UNIT_RUN', 'a child of the run could open a database'


def test_every_loaded_configuration_names_an_address_that_cannot_resolve():
    assert suite_config()['mongo_uri'] == NO_SERVER
