"""ADR-101: what happened to her, in her own block. A worker that was down while the Host ran on is one outage row,
said in words with its cause; a planned restart names who marked it; her path names come from the table she is checked
against; every turn that does not ask for her thought leaves one row, and her week reads them in either mode."""
import re

import pytest

from asuna import host_stops, local_roots
from test_local_roots import TABLES


# ---- 1. a worker that was down ------------------------------------------------------------------------------------


# ---- 2. a planned restart ----------------------------------------------------------------------------------------


# ---- 3. her path names from the table -----------------------------------------------------------------------------

@pytest.mark.parametrize('host', sorted(TABLES))
def test_her_path_line_names_exactly_the_names_she_is_checked_against(monkeypatch, host):
    table = TABLES[host]
    monkeypatch.setattr(local_roots, 'TABLE', table)
    monkeypatch.setattr(local_roots, 'REFUSED', None)
    line = local_roots.context_line(True)
    listed = re.search('这台机器上的名字只有这些：(.*?)。', line).group(1)
    named = [entry.split(' ', 1)[0] for entry in listed.split('，')]
    assert sorted(named) == sorted(table.names)
    for name in named:                                   # each name it teaches is one the check accepts
        assert not [code for code, _ in table.problems('${ASUNA_%s}/x' % name, True) if code == 'PATH_NAME_UNKNOWN']
    for kind in ('TEMP', 'FS', 'DSH_HOME', 'DRIVE_X'):
        if kind not in table.names:
            assert kind + ' ' not in line


def test_with_no_table_the_line_says_nothing_can_be_handed_over(monkeypatch):
    monkeypatch.setattr(local_roots, 'TABLE', None)
    monkeypatch.setattr(local_roots, 'REFUSED', 'ROOT_TABLE_REFUSED: test')
    assert local_roots.context_line(True) == local_roots.NO_TABLE_LINE


# ---- 4. every turn that does not ask for her thought leaves one row ------------------------------------------------


# ---- failure modes of the failure path ------------------------------------------------------------------------------


@pytest.mark.parametrize('content', [b'{not json', b'[1, 2]', b'{"since": 1}', b'{"cause": "x"' + b' ' * 70000 + b'}'],
                         ids=['torn', 'a list', 'no cause', 'past the size cap'])
def test_a_span_file_that_is_not_one_is_still_an_open_span_with_its_start_not_known(tmp_path, content):
    (tmp_path / host_stops.SPAN_FILE).write_bytes(content)
    assert host_stops.open_span(tmp_path) == {'since': None, 'cause': 'unknown'}


def test_a_mount_point_by_index_is_not_called_a_drive_letter(monkeypatch):
    monkeypatch.setattr(local_roots, 'TABLE', TABLES['linux'])
    monkeypatch.setattr(local_roots, 'REFUSED', None)
    line = local_roots.context_line(True)
    assert 'DRIVE_1 第 1 个挂载的盘' in line and 'DRIVE_C C 盘' in line


