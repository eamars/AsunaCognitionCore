"""ADR-079 step 3: her tools as each conversation's channel declared them, fixed for a session (§9.7).

`speak` lists the parts and the quote the running adapter declared, so a function the platform there cannot carry is
not shown; a call that names one anyway is refused in her words. When a channel stops or starts carrying one, each of
its conversations is told once. Kazusa's QQ Bot conversations speak through `speak` as Xiaoman's do."""
import pytest

from asuna import channel_kinds, role_tools
from asuna.config import ROOT

channel_kinds.load([{'python': ROOT / 'packages' / 'channels' / 'qq-bot' / 'python', 'module': 'qq_bot'},
                    {'python': ROOT / 'packages' / 'channels' / 'napcat-qq' / 'python', 'module': 'napcat_qq'}])
APP, GROUP = '1000000001', '0B1C2D3E4F5A6B7C8D9E0F1A2B3C4D5E'


@pytest.mark.parametrize('kinds', [('text',), ('text', 'recall'), ('text', 'react')])
def test_the_line_field_says_only_what_the_listed_parts_use(kinds):
    item = role_tools.speak_spec(kinds, True)['parameters']['parts']['items']['properties']
    if 'line' not in item:
        assert kinds == ('text',)
        return
    said = item['line']['description']
    assert ('react：' in said) == ('react' in kinds) and ('recall：' in said) == ('recall' in kinds)


