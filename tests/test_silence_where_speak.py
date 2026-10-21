"""Where only speak speaks (role_tools.REPLY_REPLACES, owner 2026-10-19), a turn that does not call it says nothing. A
stay_silent call there runs as she meant it, the way an old name runs: it ends the turn, and its result says once that
not calling speak is enough. The tool list her conversation shows does not change (its prompt cache holds)."""
from asuna import role_tools
from asuna.coordinator import Coordinator
from asuna.lanes import FakeLane, FakeTurn
from test_adr009_p2 import THINK
from test_reply_actions import mention, world


def test_stay_silent_where_speak_replaced_it_ends_the_turn_quietly(store):
    world(store)
    lane = FakeLane(store, [FakeTurn([THINK, ('stay_silent', {'why': '这句不用我接'}), ('speak', {'parts': [
        {'kind': 'text', 'text': '不该发出去'}]})], '')])
    ep = Coordinator(store, lane).ingest(mention('silent-1'), persona='P1')
    offered = lane.calls[0]['tools']
    assert 'speak' in offered and 'stay_silent' not in offered, 'the tool list is as before'
    silent = [row for row in lane.tool_results if row[2] == 'stay_silent']
    assert silent and silent[0][5] is True and silent[0][4]['note'] == role_tools.SILENT_WHERE_SPEAK
    assert silent[0][4]['silent'] is True and silent[0][4]['sent'] == '这回合 speak 一条都没发。'
    assert not [row for row in lane.tool_results if row[2] == 'speak'], 'the turn ended at stay_silent'
    saved = store.db.episodes.find_one({'_id': ep['_id']})
    assert saved['state'] == 'COMMITTED' and saved['silent']['reason'] == '这句不用我接'


def test_the_host_lets_it_through_as_it_does_an_old_name():
    assert role_tools.aliases()['stay_silent'] == 'speak'
