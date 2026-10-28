"""A unit run reaches no database server (ADR-104): both locks of conftest hold, here and in a child process."""
import json
import subprocess
import sys

import pymongo

from asuna.config import load
from asuna.state import Store
from conftest import NO_SERVER, UNIT_RUN_SITE


def test_every_client_is_the_in_process_stand_in_whatever_its_address():
    client = pymongo.MongoClient('mongodb://192.0.2.1:27017/', serverSelectionTimeoutMS=100)   # TEST-NET-1
    assert getattr(client, 'unit_run', False)
    client.close()


def test_every_loaded_configuration_names_an_address_that_cannot_resolve(store):
    assert load()['mongo_uri'] == NO_SERVER
    assert store.config['mongo_uri'] == NO_SERVER and getattr(store.client, 'unit_run', False)
    assert getattr(Store(load(), store.name).client, 'unit_run', False)


def test_a_child_process_of_the_run_gets_the_stand_in_too():
    code = 'import json, pymongo; print(json.dumps(getattr(pymongo.MongoClient("mongodb://192.0.2.1"), "unit_run", False)))'
    done = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr[-500:]
    assert json.loads(done.stdout) is True, 'a child without %s on its PYTHONPATH could reach a server' % UNIT_RUN_SITE
