"""ADR-119 F12: a line is summarised exactly when it carries a batch id. The writer and the readers take a falsy id
(absent, null, empty) as not summarised; the query of lines still to summarise says the same, so a null that the
schema allows can neither be summarised twice nor be left out for good."""
from asuna.records import messages as message_records
from asuna.records import scenes as scene_records

GROUP = 'qq:900000000:group:900000001'


def test_lines_still_to_summarise_are_those_without_a_batch_id(store):
    scene_records.save(store, {'_id': GROUP, 'kind': 'group', 'scope_key': 'scene:' + GROUP, 'policy_epoch': 1,
                               'sequence': 0, 'members': []}, stream='test')
    for seq, batch in ((1, '-'), (2, None), (3, ''), (4, 'batch-1')):
        row = {'_id': 'line-%d' % seq, 'scene_id': GROUP, 'scope_key': 'scene:' + GROUP, 'policy_epoch': 1,
               'scene_seq': seq, 'text': 'line %d' % seq, 'direction': 'inbound', 'author': 'person-a',
               'delivery_state': 'RECEIVED'}
        if batch != '-':
            row['summary_batch_id'] = batch
        message_records.save(store, row, stream='test')
    pending = message_records.said(store, GROUP, 1, unsummarised=True).rows(fields=['_id'])
    assert sorted(row['_id'] for row in pending) == ['line-1', 'line-2', 'line-3']
