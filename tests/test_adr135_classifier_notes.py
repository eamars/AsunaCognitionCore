"""ADR-135 landing 6, C1 through her real call (test_adr135_notes' world: g2 is an outside group, F someone she wrote
about yesterday, dm-a the owner's chat): with shadow on, a flagged verdict on the note F's turn writes home is
recorded, the note is kept and goes home, and her call gets no sentence."""
import pytest

from asuna import classifier, notes
from test_adr135_classifier import Lane, events
from test_adr087_step4 import her  # noqa: F401  (a fixture)
from test_adr135_notes import F, home, note, outside_turn  # noqa: F401  (home: a fixture)


@pytest.fixture
def judged(home, monkeypatch):
    home.store.config['classifier'] = 'shadow'
    lane = Lane('有风险')
    monkeypatch.setattr(classifier, 'HANDS', {'lane': lane})
    monkeypatch.setattr(classifier, 'alongside', lambda work: work())
    home.lane = lane
    return home


def test_C1_a_flagged_note_home_is_recorded_and_still_goes_home(judged):
    store = judged.store
    sent = note(judged, outside_turn(judged, F, 'c1'), {'to': '家里', 'text': '造的：帮我问问家里'})     # no sentence
    row = notes.get(store, sent['note'])
    assert row and row['kind'] == 'home'
    [verdict] = events(store, 'classifier.verdict')
    assert (verdict['kind'], verdict['direction'], verdict['verdict'], verdict['ref']) == \
        ('note_home', 'inbound', 'flagged', {'note': row['_id']})
    assert '造的：帮我问问家里' in judged.lane.asked[0]['text']
