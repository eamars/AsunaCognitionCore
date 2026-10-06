"""Her tool arguments as she plainly meant them (tool_args.py, owner 2026-10-06): shape is taken, bounds kept."""
import pytest

from asuna import tool_args


def test_a_list_written_as_a_string_is_read_as_the_list():
    args, notes = tool_args.normalize('sandbox_run', {'argv': '["python3", "-c", "print(1)"]'})
    assert args['argv'] == ['python3', '-c', 'print(1)'] and notes
    args, _ = tool_args.normalize('development_run', {'argv': "['sh', '-c', 'ls']", 'project': 'core'})
    assert args == {'argv': ['sh', '-c', 'ls'], 'project': 'core'}
    assert tool_args.normalize('sandbox_run', {'argv': ['ls']}) == ({'argv': ['ls']}, [])
    with pytest.raises(ValueError, match='ARGV_NOT_A_LIST'):
        tool_args.normalize('sandbox_run', {'argv': 'python3 -c print(1)'})


def test_true_as_text_is_true_and_bounds_clamp_to_the_tools_own():
    assert tool_args.normalize('development_write', {'overwrite': 'True', 'path': 'a'})[0]['overwrite'] is True
    assert tool_args.normalize('development_write', {'overwrite': 'maybe'})[0]['overwrite'] == 'maybe'   # the tool refuses it
    args, notes = tool_args.normalize('development_database_read', {'collection': 'scenes', 'limit': 200})
    assert args['limit'] == tool_args.DATABASE_PAGE and 'skip' in notes[0]
    assert tool_args.normalize('query_authorized_history', {'window_days': 3650})[0]['window_days'] == 90
    assert tool_args.normalize('integration_test', {'argv': ['x'], 'timeout': 90})[0]['timeout'] == 60
    assert tool_args.normalize('development_database_read', {'collection': 'scenes', 'limit': 20}) == \
        ({'collection': 'scenes', 'limit': 20}, [])
