"""ADR-058: the heartbeat rolls a die before it reaches her. Nothing (no turn, unless an hour would lose something
only a heartbeat shows), interesting, self development, self evaluation, review the dice, reach out at home, and idle (nothing but its hint, the seventh face); awake and
asleep weights she sets by name; the roll is one line of text, reproducible from the beat, and recorded."""
import collections

import pytest

from asuna import dice


def test_a_roll_follows_its_weights_is_the_same_for_the_same_beat_and_a_zero_never_comes():
    weights = dice.parse('歇着 40、有趣 35、自我评估 25')
    rolls = collections.Counter(dice.roll('beat-%d' % n, weights) for n in range(4000))
    assert rolls['self_development'] == 0
    assert all(abs(rolls[o] / 4000 - weights[o] / 100) < 0.03 for o in ('nothing', 'interesting', 'self_evaluation'))
    assert dice.roll('beat-7', weights) == dice.roll('beat-7', weights)
    assert weights['self_development'] == 0 and weights['reach_out'] == 0, 'a name left out weighs 0'
    assert dice.parse('歇着40,复盘 2/找人 5') == {**dict.fromkeys(dice.OUTCOMES, 0), 'nothing': 40, 'review_dice': 2,
                                                 'reach_out': 5}
    for bad in ('40/35/10/15', '歇着 0', '睡觉 10', '歇着 10、歇着 5', '歇着', None):
        with pytest.raises(ValueError):
            dice.parse(bad)


def test_the_seventh_face_idle_parses_defaults_to_zero_and_is_listed_even_at_zero():
    assert 'idle' in dice.OUTCOMES and dice.NAMES['idle'] == '待着'
    assert dice.parse('待着 5、有趣 95')['idle'] == 5
    assert dice.parse(dice.DEFAULTS['awake']) == {'nothing': 40, 'interesting': 31, 'self_development': 10,
                                                  'self_evaluation': 12, 'review_dice': 2, 'reach_out': 5, 'idle': 0}
    assert dice.parse(dice.DEFAULTS['asleep']) == {'nothing': 66, 'interesting': 0, 'self_development': 20,
                                                   'self_evaluation': 8, 'review_dice': 2, 'reach_out': 4, 'idle': 0}
    for period in ('awake', 'asleep'):
        assert dice.weights_for({}, {}, period)['idle'] == 0, 'the core persona defaults weigh it 0 too'
    assert dice.words(dice.parse('有趣 1')).endswith('待着 0'), 'words lists the new face even at 0'


