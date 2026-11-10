"""Her plan tool on one of the four rhythms (ADR-119 F10): update and cancel are refused alike, in her wording, and
the plan stays as it was. On the fixture world of test_adr087_step4."""
import pytest

from asuna import role_tools
from asuna.records import plans as plan_records
from asuna.schedule import PRESENCE_PLAN
from test_adr087_step4 import her, presence_plan, refused, turn  # noqa: F401  (her: the fixture)

WORDS = '这四条归程序，调它们用 set_policy（快慢、时间和夜里的窗口；总开关归主人）。'


@pytest.mark.parametrize('op', [{'do': 'update', 'after_seconds': 600}, {'do': 'cancel'}])
def test_her_plan_tool_refuses_a_rhythm_in_her_words_and_leaves_it(her, op):
    presence_plan(her)
    ep_id = turn(her, ['plan'])
    no = refused(her, ep_id, 'plan', {**op, 'plan_id': PRESENCE_PLAN})
    assert list(no.codes) == ['PLAN_RHYTHM']
    assert WORDS in str(no) and '改不了' not in str(no) and '开关，在家里用' not in str(no), str(no)
    assert str(no) == role_tools.PLAN_RHYTHM % PRESENCE_PLAN
    assert plan_records.get(her.store, PRESENCE_PLAN)['status'] == 'ACTIVE'
