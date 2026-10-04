"""ADR-009 P5 MongoDB tests: T5.6 salience ranking against the golden file."""
import json

import pytest

from asuna.evidence import Evidence
from asuna.retrieval import Retrieval
import retrieval_golden_cases as golden


@pytest.fixture
def retrieval(store, tmp_path):
    golden.seed(store)
    value = Retrieval(store, Evidence(tmp_path / 'ev'))
    yield value
    value.close()


def test_T5_6_zero_weights_match_golden_and_pins_rise(store, retrieval):
    expected = json.loads(golden.GOLDEN.read_text(encoding='utf-8'))
    zero = {'w_pin': 0, 'w_heat': 0, 'w_age': 0, 'half_life_days': 30}
    assert golden.rank(retrieval, salience=zero) == expected
    assert golden.rank(retrieval) == expected
    # g03 is a weak match for "拼图周末" (last of four); pinned with a pin weight, it rises.
    unit = store.db.memory_units.find_one({'_id': 'g03'})
    store.put('memory_units', {**unit, 'pinned': True}, expected=unit['revision'])
    pinned = golden.rank(retrieval, salience={**zero, 'w_pin': 1.0})['拼图周末']
    assert pinned[0] == 'g03' and pinned.index('g03') < expected['拼图周末'].index('g03')
    # A pinned flag alone changes nothing while its weight is zero.
    assert golden.rank(retrieval, salience=zero) == expected
