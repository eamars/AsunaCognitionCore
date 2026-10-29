"""Workspace mode contracts; C2 live evidence is separate from these test doubles."""

import pytest

from asuna.tasks import failure_words
from asuna.testing import remove_workspace


CREATED = []


@pytest.fixture(autouse=True)
def remove_workspaces():
    yield
    while CREATED:
        remove_workspace(CREATED.pop())


def test_failure_words_name_the_code_the_note_and_what_else_the_tool_said():
    assert failure_words({'written': True}) is None
    assert failure_words({'error': 'TASK_OPERATION_FAILED: 没有 a.txt', 'execution': {'exit_code': 1}}) == \
        'TASK_OPERATION_FAILED: 没有 a.txt'
    assert failure_words({'rendered': False, 'error': 'SVG_NOT_FOUND', 'note': '先用 write_file 写好 .svg。',
                          'path': 'a.svg'}) == 'SVG_NOT_FOUND: 先用 write_file 写好 .svg。 {"path": "a.svg"}'
    assert failure_words({'error': 'INVALID_IMPORT_ARGUMENTS'}) == 'INVALID_IMPORT_ARGUMENTS'
    # A picture still being drawn has not failed: the same job is fetched by calling again.
    assert failure_words({'generated': False, 'error': 'IMAGE_JOB_STILL_RUNNING', 'prompt_id': 'p-1'}) is None


def test_a_failed_file_operation_says_why_and_what_to_do(tmp_path):
    from asuna.tasks import workspace_file
    (tmp_path / 'big.txt').write_text('x' * 40000, encoding='utf-8')
    (tmp_path / 'kept.txt').write_text('原文', encoding='utf-8')
    big = workspace_file(tmp_path, [], 'read_file', {'path': 'big.txt'})['error']
    assert big.startswith('TASK_OPERATION_FAILED: READ_LIMIT: big.txt 有 40000 字节') and 'sandbox_run' in big
    assert 'overwrite=true' in workspace_file(tmp_path, [], 'write_file', {'path': 'kept.txt', 'text': '新'})['error']
    assert 'list_files' in workspace_file(tmp_path, [], 'read_file', {'path': 'none.txt'})['error']
    assert '相对路径' in workspace_file(tmp_path, [], 'read_file', {'path': '../outside.txt'})['error']


def test_a_written_file_holds_the_text_as_given(tmp_path):
    """No line-ending translation on any platform: LF stays LF."""
    from asuna.tasks import workspace_file
    assert workspace_file(tmp_path, [], 'write_file', {'path': 'notes.md', 'text': '一\n二\n'})['written']
    assert (tmp_path / 'notes.md').read_bytes() == '一\n二\n'.encode('utf-8')


