"""Counters written outside a document's revision (state.COUNTER_FIELDS: a scene's sequence, a memory's salience, a
watch's sightings, a note's seen_in, a stored file's touches): every one has its case on MongoDB
(integration/counter_bumps.py, run by integration/test_store_counters.py), and a stored file's row is never started
over (records.artifacts.save refuses it). Neither check needs a database."""
import sys
from pathlib import Path

import pytest

from asuna.records import artifacts as artifact_records
from asuna.state import COUNTER_FIELDS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'integration'))
from counter_bumps import BUMPS  # noqa: E402


def test_every_counter_collection_has_a_case():
    assert set(BUMPS) == set(COUNTER_FIELDS)
    assert all(set(BUMPS[name][0]) == set(fields) for name, fields in COUNTER_FIELDS.items())


def test_a_stored_file_is_never_started_over():
    with pytest.raises(ValueError, match='ARTIFACT_COUNTERS_KEPT'):
        artifact_records.save(None, {'_id': 'a'}, expected=1, reset_counters=True)
