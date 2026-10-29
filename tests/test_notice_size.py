"""Her turn notices stay small (owner, 2026-10-05): headlines, not audit ids or every path."""
from asuna.tasks import bounded_result


def test_a_task_result_keeps_the_report_but_not_its_tool_record_ids():
    result = {'task_id': 't', 'text': '做完了。', 'finish_reason': 'stop', 'artifact_refs': ['tool-' + 'a' * 64] * 40,
              'facts': [{'text': '做完了。', 'evidence_refs': ['tool-' + 'a' * 64] * 40}]}
    shown = bounded_result(result)
    assert shown['text'] == '做完了。' and shown['tool_records'] == 40 and 'artifact_refs' not in shown
    assert 'facts' not in shown, 'the report is not shown twice, nor every record id with it'
    assert 'artifact_refs' in result and 'facts' in result, 'the stored result is unchanged'


