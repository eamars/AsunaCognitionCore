"""ADR-104 owners and named operations, and the rules that assign each census row (call_site_map.py) to one.

OWNERS is the design's section 4 in data: owner module -> collections, why (where several modules use a collection
today), and its operations {name: meaning}. Reads are views (a named condition with its natural order, built inside
the owner) used with the shared verbs rows / first / count / values; single-record reads and writes are operations
of their own.

assign(row) -> (operation, how): how is 'rule' (by collection, method and condition shape), 'hand' (HAND below, read
in the code: every dynamic or merged condition and every collection chosen at run time), or 'shared' (the shared
layer's own surface).

    python owner_ops.py [--markdown]     # owners, operations; the section 4 table
"""
from __future__ import annotations

import re
import sys

R = 'records.'          # src/asuna/records/<name>.py: the leaf owner modules of collections read across the core

OWNERS = {
    R + 'messages': {
        'collections': ['messages'],
        'why': 'read in 46 modules, written through put by channels, ingress, chat, coordinator, publish and others; '
               'no domain module holds all its rules and the owner must import nothing of the core (a leaf), so a '
               'records module owns it',
        'ops': {
            'get': 'one line by id, optionally fenced to a conversation, epoch, scope, direction, channel or a line '
                   'from a channel (None outside the fence)',
            'many': 'view: lines by ids, optionally fenced to conversations and an epoch, or received since a time',
            'said': 'view: a conversation as people saw it, one epoch (lines people wrote and her delivered lines); '
                    'people only (not the program\'s lines), not yet summarised, seq window, topic, several sources, ids',
            'pointable': 'view: lines one may point at in a conversation (people\'s lines that are not notices, her '
                         'delivered lines), by id or seq',
            'lines': 'view: a conversation\'s lines, live only (in and out) or all, after or between positions',
            'inbound': 'view: lines people wrote, in one conversation or several; author in / not, people only, since, '
                       'seq window, wake reasons, marks (media, notice, peer, group name, aside, forward ref, peer '
                       'name), not an outcome',
            'spoken': 'view: her delivered lines (one conversation or all), by author, since a receipt time, not in '
                      'some conversations, with a receipt',
            'outgoing': 'view: her lines in a conversation in given delivery states',
            'turn_parts': 'view: the lines one turn produced (phase, delivery states in / not in, reply parts, '
                          'segment order, direction)',
            'at': 'view: the line at a conversation position (seq), optionally by author and direction',
            'by_platform_id': 'view: a conversation\'s line by its own id, the platform\'s event id or message id '
                              '(direction, epoch, since, author)',
            'replies_to': 'view: lines replying to these lines, or these ids, in fenced conversations (digest thread)',
            'answers': 'view: lines answering her question: replies to her lines, a wait it woke, reactions, or '
                       'marked answers; after a position, until a time',
            'excluded': 'counts of her lines a digest leaves out (speech not delivered, outbound not speech)',
            'queued': 'view: a channel\'s queued outbound lines for a lane and route (channels._next)',
            'in_flight_scenes': 'values: conversations with a chat line out (SENDING, not a file) claimed since a time',
            'sending': 'view: lines left SENDING on a channel (recover_sending at start)',
            'unsettled': 'count: outbound lines still queued or sending (restarts)',
            'claim_unshown': 'claim-next: the oldest owner line on a route not yet shown to its agent, marked shown',
            'ingress': 'view: host-managed inbound lines in given ingress states',
            'channel_inbound': 'view: host-managed inbound lines from a channel since a time',
            'visits': 'view and count: visit rows of an intent (errands) since a time',
            'errand_results': 'view: completed errand visit lines of a conversation not yet told',
            'mark_errands_told': 'set errand_told on these lines',
            'artifact_refs': 'values: artifact ids lines name as attachment or file (optionally in delivery states)',
            'mentions': 'view: lines of a conversation that mention accounts, since a time',
            'authors': 'values: who wrote in one or several conversations (direction, epoch, not deleted, names)',
            'search': 'view: history search (live or archived lines, text contains with case, authors, time window, '
                      'positions), as history_query asks',
            'web_page': 'the Web memory page\'s source lines: said lines of these sources, optional case-blind '
                        'search, newest first, a page window (its aggregate as reads; the excerpt cut in Python)',
            'mark_recalled': 'set recalled_at on her line',
            'note_failure': 'set a file line\'s failure detail',
            'redact_scope': 'erasure: replace every line of a scope by its retained fields',
            'save': 'revisioned write of a line (Store.put)',
        }},
    R + 'scenes': {
        'collections': ['scenes'],
        'why': 'read in 52 modules; written by condense, coordinator, faults, places, lines, native_worker, ingress',
        'ops': {
            'get': 'a conversation by id', 'by_scope': 'the conversation of a scope (optionally its epoch or kind)',
            'of_kind': 'view: conversations of a kind (optionally all but one)',
            'many': 'view: conversations by ids (optionally of a kind)', 'in_scopes': 'view: conversations of scopes',
            'all': 'view: every conversation', 'condense_wanted': 'view: conversations waiting to be condensed',
            'channel_scenes': 'view: conversations of a kind that a channel carries',
            'next_seq': 'the counter: a conversation\'s next position, taken and raised in one step',
            'authorize': 'the conversation if this person is a member, else Denied (Store.authorize)',
            'want_condense': 'set condense_wanted', 'clear_condense': 'unset condense_wanted',
            'set_condense_floor': 'set condense_floor', 'note_size': 'set conversation_size',
            'note_tokens': 'set conversation_tokens', 'set_character_context': 'set character_context',
            'set_timezone': 'set or clear the conversation\'s time zone', 'note_fault': 'set fault',
            'clear_fault': 'unset fault if it is still the one at this time', 'hold_unsent': 'set unsent',
            'clear_unsent': 'unset unsent if it is still this turn\'s', 'asides_shown': 'raise asides_shown_seq',
            'told_condensed': 'set condensed_told if condensed_at is still this one',
            'apply_condense': 'the condense step\'s result on a conversation (unset wanted, floor, told; set when, by)',
            'save': 'revisioned write (Store.put)'}},
    R + 'episodes': {
        'collections': ['episodes'],
        'why': 'read in 24 modules (turns); written by coordinator and chat through put',
        'ops': {'get': 'a turn by id (optionally fenced: persona, carried system ref, a stream\'s turn)',
                'many': 'view and count: turns by ids (optionally in states)',
                'of_source': 'the turn of a source event (kind, conversation)',
                'of_kind': 'view: turns of a kind, optionally in conversations',
                'open': 'view: turns in states (of a kind, or not of a kind)',
                'answered': 'count: turns that answered these people with speech (familiarity)',
                'of_scope': 'view: turns of a scope (erasure)',
                'redact_scope': 'erasure: replace every turn of a scope by its retained fields',
                'save': 'revisioned write (Store.put)'}},
    R + 'tasks': {
        'collections': ['tasks', 'task_messages'],
        'why': 'tasks read in 18 modules, task_messages in 4; tasks.py holds the lifecycle but imports most of the '
               'core, so the rows live in a leaf module and tasks.py calls it',
        'ops': {'get': 'a task by id (optionally fenced: conversation, scope, epoch, requester, state)',
                'many': 'view: tasks by ids (optionally in states)',
                'in_states': 'view: tasks in states (optionally except one)',
                'by_prefix': 'view: a requester\'s tasks in a conversation whose id starts with a prefix',
                'continuations': 'view: tasks continuing these tasks',
                'awaiting_feedback': 'view: finished tasks whose feedback has not reached her',
                'lease_expired': 'view: running tasks whose lease expired before a time',
                'paused': 'view: paused tasks (reason, since, paused state)',
                'of_conversations': 'view: tasks of conversations', 'created': 'view: tasks created in a window '
                '(optionally in / not in conversations)', 'of_episode': 'view: tasks of a turn',
                'finished_since': 'the first task finished after a time', 'of_scope': 'view: tasks of a scope',
                'redact_scope': 'erasure: replace every task of a scope by its retained fields',
                'recent_with_inputs': 'a conversation\'s 16 most relevant tasks with their newest input time and '
                                      'report length (the $lookup aggregate, as reads plus Python)',
                'thread': 'view: a task\'s messages (from, delivered)',
                'thread_message': 'one task message by id (optionally from)',
                'save': 'revisioned write of a task (Store.put)', 'save_message': 'write of a task message (Store.put)'}},
    R + 'plans': {
        'collections': ['plans'],
        'why': 'schedule.py reads 37 of 48 but is not a leaf; context, role_tools, condense, night, restarts, '
               'reflection_map read it',
        'ops': {'get': 'a plan by id (optionally fenced: conversation, person, epoch, scope)',
                'in_status': 'view: plans in statuses (kinds in)', 'due': 'view: active plans due by a time, not of '
                'kinds', 'of_conversation': 'view: plans of a conversation (person, epoch, scope, statuses, kinds '
                'not in)', 'with_outcome': 'view: plans of kinds in a conversation with a last outcome',
                'count_status': 'count of plans in a status', 'save': 'revisioned write (Store.put)'}},
    R + 'memories': {
        'collections': ['memory_units'],
        'why': 'read in 15 modules; retrieval, memory, dialogue_summary, privacy write; vector search reads it',
        'ops': {'get': 'a memory by id, optionally fenced (readable pairs, scope, epoch, episode, kind, status, not '
                       'a tombstone)',
                'many': 'view: memories by ids (optionally alive, of a kind, of a character, in readable pairs)',
                'readable': 'view: alive memories of a character in these (scope, epoch) pairs, optionally of a kind '
                            '(retrieval, context, the Web page)',
                'of_kind': 'view: memories of a kind in a scope (or of a source)',
                'summary_of': 'the summary of a source line in a scope and epoch',
                'pending_index': 'view: alive memories waiting for their vector (or of an old embedding revision)',
                'dependents': 'view: memories of a scope derived from these sources (erasure)',
                'of_scope': 'view: every memory of a scope (erasure)', 'alive': 'view: every alive memory',
                'tombstone': 'erasure: replace a memory by its tombstone', 'set_epoch': 'move a memory to an epoch',
                'touch_salience': 'raise a memory\'s reference count, set its last reference (counter fields)',
                'nearest': 'vector search (step 1b, unchanged)', 'ensure_vectors': 'the vector space (step 1a)',
                'web_page': 'the Web memory page\'s units: readable units of a kind, optional case-blind search, '
                            'newest by their own time, a page window (its aggregate as reads plus Python)',
                'save': 'revisioned write (Store.put)'}},
    R + 'artifacts': {
        'collections': ['artifacts'],
        'why': 'read in 17 modules; received_files, notices, capabilities, outbound_files, attend, blobs, media_life '
               'write; the bytes are blobs.py\'s',
        'ops': {'get': 'an artifact row by id (optionally of a kind, state, storage, task revision, scopes)',
                'by_ids': 'view: rows by ids (optionally of a storage)',
                'of_task': 'view: a task revision\'s artifacts in states', 'of_tasks': 'view: artifacts of tasks',
                'of_kind': 'view: rows of a kind (state, storage, scope)', 'of_scene': 'view: rows of a kind in a '
                'conversation', 'kept': 'view: received files kept (optionally stored)', 'with_copies': 'view: rows '
                'of a kind with task-folder copies (not of a storage)', 'by_content': 'the row holding these bytes '
                '(sha256, kind, scopes, sources, state)', 'answer': 'the row of an answer', 'admission': 'the newest '
                'admission row of a channel (claimed since)', 'stored': 'view: rows whose bytes are stored',
                'insert': 'insert a row', 'replace': 'replace a capability row',
                'delete_many': 'delete rows by ids (optionally of a kind)', 'delete': 'delete a row',
                'mark_read': 'set last_read_at on a received file in scope', 'mark_sent': 'set last_sent_at',
                'restore_bytes': 'put bytes back on a removed row if it is still removed', 'add_copy': 'add a task-'
                'folder copy', 'set_copies': 'set the copies', 'set_days_from': 'set days_from (optionally add a '
                'source)', 'let_go': 'let a kept file go', 'keep_why': 'set kept_why', 'unkeep': 'unset kept_at',
                'set_received_from': 'set received_from', 'bytes_removed': 'mark a row\'s bytes removed',
                'erase_scope': 'mark a scope\'s stored rows erased (ADR-105)', 'set_fields': 'set a received file\'s '
                'fields (received_files.py:145)', 'count_tool': 'count of done artifacts of a tool',
                'redact_scope': 'erasure: replace a scope\'s rows by their retained fields (erased rows stay)',
                'save': 'revisioned write (Store.put)'}},
    'blobs': {
        'collections': ['artifact_blobs (the blob store)'],
        'why': 'blobs.py is the only user of the blob interface; media_life, outbound_files and the probe call it',
        'ops': {'put_stream': 'store a stream, hashed while copied, read back and checked', 'open': 'open stored '
                'bytes (seekable)', 'delete': 'delete bytes', 'erase_scope': 'delete a scope\'s bytes',
                'exists': 'whether bytes are stored', 'stats': 'how many blobs and bytes (probe)'}},
    R + 'sessions': {
        'collections': ['sessions'],
        'why': 'native_worker reads 30 of 36 but is not a leaf; condense, coordinator, native_api, tools_week, '
               'privacy read',
        'ops': {'get': 'a session by id (optionally native)', 'native': 'view: native sessions (optionally by ids, '
                'lane, not of a conversation)', 'successors': 'view: sessions continuing these', 'main': 'the main '
                'conversation session of a conversation (lane, persona, epoch, context)', 'titled': 'the main session '
                'of a conversation that has a native title', 'of_task': 'a task\'s newest action session (or the '
                'query\'s)', 'of_scope': 'view: sessions of a scope', 'invalidate': 'mark a session invalidated by '
                'an erasure', 'save': 'revisioned write (Store.put)'}},
    R + 'receipts': {
        'collections': ['lane_receipts', 'sink_receipts'],
        'why': 'sink_receipts read by native_worker, host, schedule, context, history_query, scene_links, publish; '
               'lane_receipts by dialogue_summary, coordinator, lanes, native_worker, privacy',
        'ops': {'lane_get': 'a lane receipt by id', 'lane_of_sessions': 'view: lane receipts of sessions',
                'lane_invalidate': 'erasure: replace a lane receipt by its invalidated form', 'sink_get': 'a sink '
                'receipt by id', 'sinks': 'view: sink receipts by ids (or all)', 'sink_of_kind': 'view: sink receipts '
                'of a kind (states, project, except one)', 'sink_window': 'view: receipts in a history window, '
                'newest first, from a position (history_query)', 'redact_scope': 'erasure of a scope\'s sink '
                'receipts', 'save_lane': 'write (Store.put)', 'save_sink': 'write (Store.put)'}},
    'audit': {
        'collections': ['audit_events'],
        'why': 'audit.py holds verify, prune and replay; 18 modules read it; every module appends through '
               'Store.audit, which calls audit.append',
        'ops': {'append': 'append an event to a stream (hash chain, seq unique per stream; Store.audit)',
                'events': 'view: events of types (time window, streams, refused, payload fields, not one occurrence)',
                'last': 'the newest event of a stream or of a type (persona, payload fields)',
                'recent': 'view: the newest events of a type', 'of_document': 'the commit of a document',
                'commit_of': 'the commit of an operation (recover_commits)', 'count': 'count of events of a type '
                '(since, window)', 'latest_kept': 'the newest event of each kept kind per stream (prune: group by '
                '(type, stream) with Max(occurred_at), then reads)', 'prune': 'delete events past retention or '
                'over the cap', 'size': 'the audit\'s records and bytes (the adapter\'s size)', 'streams':
                'values: every stream id', 'redact_streams': 'erasure: rewrite streams with redacted payloads and '
                're-hash (privacy)', 'trace': 'the cli trace: every event, or one stream in seq order'}},
    R + 'heads': {
        'collections': ['state_heads', 'state_revisions'],
        'why': 'documents, memory, understanding, self_state, policy, privacy, native_api, reflection_map, familiarity '
               'read; Store.head, init_head and mutate move here',
        'ops': {'head': 'a head by id', 'current': 'a head and its revision (Store.head)', 'init': 'create a head '
                'with its first revision (Store.init_head)', 'mutate': 'her relationship or scene-affect revision '
                '(Store.mutate)', 'with_prefix': 'view: heads whose id starts with any of these prefixes',
                'heads': 'view: heads by ids or of scopes', 'revision': 'a revision by id (optionally of an entity)',
                'revisions': 'view: revisions by ids', 'by_mutation': 'the revision of a mutation id',
                'history': 'view: an entity\'s revisions, newest first (since / before a time)', 'point_to':
                'erasure: move a head to an older revision', 'drop_head': 'delete a head (optionally if still at a '
                'revision)', 'tombstone_revision': 'erasure: empty a revision', 'stale_revisions': 'view: a scope\'s '
                'revisions no head points at', 'save_head': 'revisioned write (Store.put)', 'save_revision':
                'write (Store.put)'}},
    'documents': {
        'collections': ['journal_entries', 'journal_revisions'],
        'why': 'documents.py (DocumentStore.JOURNALS) writes both; crossing, memory_pilot, memory_tiers read',
        'ops': {'entry': 'a journal entry by id', 'slugs': 'values: a persona\'s journal slugs', 'entries': 'view: a '
                'journal\'s entries in order', 'entry_of': 'the entry of a slug (optionally by mutation)',
                'last_entry': 'the newest entry of a journal', 'revision': 'a journal revision by id or mutation',
                'revisions': 'view: an entry\'s revisions (sid)', 'revision_of_body': 'the revision of a body hash',
                'last_revision': 'the newest revision of a journal', 'save_entry': 'write (Store.put)',
                'save_revision': 'write (Store.put)'}},
    R + 'people': {
        'collections': ['identities', 'scene_people'],
        'why': 'identities read in 9 modules, scene_people in 5; people.py is not a leaf',
        'ops': {'identity': 'an identity by person id', 'by_account': 'the identity of an account (and platform)',
                'all_identities': 'view: every identity', 'of_person': 'the identity whose person_id is this',
                'label': 'a conversation '
                'label row by id', 'labels': 'view: a conversation\'s labels (not a person)', 'label_of_person':
                'the newest label of a person', 'first_label': 'the first label of a conversation',
                'save_identity': 'write (Store.put)', 'save_label': 'write (Store.put)'}},
    'affect': {
        'collections': ['affect_events', 'affect_amendments', 'affect_proposals'],
        'why': 'affect.AffectLedger is the insert-only writer; context, native_api, reflection_map read',
        'ops': {'insert': 'insert-only write; an identical replay returns the stored row', 'events': 'view: a '
                'persona\'s events (ids, not from scopes, id prefix)', 'event': 'an event by id (of a persona)',
                'amendments': 'view: amendments (persona, targets, ops)', 'amendment': 'an amendment by id or target',
                'proposals': 'view: a persona\'s proposals of a row kind', 'proposal': 'a proposal by id or episode',
                'counts': 'counts for the map (events, open, since)'}},
    'stickers': {
        'collections': ['stickers', 'sticker_pool', 'sticker_memory'],
        'why': 'stickers.py writes all three; role_tools and media_life read',
        'ops': {'shelf': 'view: a persona\'s stickers', 'sticker': 'a sticker by name, identity, picture or artifact',
                'shelf_size': 'count of a persona\'s stickers', 'drop_sticker': 'delete a sticker at a revision',
                'pool': 'view: pool candidates (here, newest seen first)', 'candidate': 'a pool row by id, artifact, '
                'identity or md5', 'pool_size': 'count of the pool', 'drop_candidate': 'delete pool rows (id at a '
                'revision, identity, md5)', 'memory': 'a remembered sticker (key or alias, picture, persona)',
                'artifact_ids': 'values: artifact ids on the shelf and in the pool', 'save': 'writes (Store.put)'}},
    'notes': {'collections': ['notes'], 'why': 'notes.py writes; reflection_map and role_tools read',
              'ops': {'get': 'a note by id', 'reply_to': 'the note replying to one', 'questions': 'view: open '
                      'questions to or from a conversation since a time', 'last_seen': 'the newest note between two '
                      'conversations seen in a turn', 'count': 'counts of notes (a day\'s, between conversations, of '
                      'a turn, of a persona since)', 'seen_in': 'add a turn to seen_in', 'save': 'write (Store.put)'}},
    'watches': {'collections': ['watches'], 'why': 'only watches.py', 'ops': {
        'get': 'a watch by id (optionally active, of a persona)', 'active': 'view: a persona\'s active watches',
        'of_person': 'the active watch of a person', 'count_active': 'count of other active watches',
        'seen': 'record a sighting if last_seen_at is still the one read', 'save': 'write (Store.put)'}},
    'questions': {'collections': ['questions'], 'why': 'questions.py writes; role_tools, reflection_map, tools_week read',
                  'ops': {'get': 'a question by id (optionally of a persona)', 'open_in': 'view: open questions to '
                          'a conversation (one source matching)', 'closed_untold': 'view: questions closed by a kind '
                          'of answer not yet told', 'of_persona': 'view: a persona\'s questions in a state',
                          'asked': 'view: questions asked since a time (to a conversation, or from action)',
                          'migrated': 'view: questions migrated from these', 'count_open': 'count not closed',
                          'told': 'add a turn to told_in', 'save': 'write (Store.put)'}},
    R + 'ideas': {'collections': ['ideas'], 'why': 'role_tools writes; native_api, night, reflection_map read',
                  'ops': {'get': 'an idea by id (optionally of a persona)', 'of_persona': 'view: a persona\'s ideas '
                          '(state, words contained in idea or why)', 'count': 'count in states',
                          'save': 'write (Store.put)'}},
    'developer_inbox': {'collections': ['developer_inbox'], 'why': 'developer_inbox.py writes; faults raises counts, '
                        'questions reads', 'ops': {'get': 'an item by id', 'unread': 'view: new items (of a level)',
                        'of_persona': 'view: a persona\'s items not from a source', 'bump': 'raise an item\'s count',
                        'save': 'write (Store.put)'}},
    'group_members': {'collections': ['group_members'], 'why': 'only group_members.py',
                      'ops': {'get': 'a group\'s member list', 'save': 'write (Store.put)'}},
    'host_stops': {'collections': ['host_stops', 'missed_looks'], 'why': 'host_stops.py writes; restarts reads',
                   'ops': {'get': 'a stop by id', 'unshown': 'view: outage stops back since a time or not yet shown',
                           'last_back': 'the newest stop of a kind back since a time', 'mark_shown': 'set shown_at '
                           'where it is still null or missing', 'missed': 'view: missed looks since',
                           'note_missed': 'upsert a missed look', 'forget_missed': 'delete missed looks before',
                           'save': 'write (Store.put)'}},
    'switches': {'collections': ['switches'], 'why': 'only switches.py', 'ops': {
        'get': 'a switch by id (optionally active, of a persona)', 'on': 'view: active switches (kind, conversation, '
        'person)', 'changed': 'view: switches that ran out or were cleared in a window', 'save': 'write (Store.put)'}},
    'own_mute': {'collections': ['own_mutes'], 'why': 'only own_mute.py', 'ops': {
        'get': 'a group\'s own mute', 'save': 'write (Store.put)'}},
    'lane_faults': {'collections': ['lane_faults'], 'why': 'only lane_faults.py', 'ops': {
        'count': 'raise each signature\'s hour count, creating it (many, unordered)', 'forget_old': 'delete counts '
        'past KEEP_DAYS on each write (replaces the TTL index)'}},
    'memory_tiers': {'collections': ['memory_tiers'], 'why': 'memory_tiers.Tiers writes; carried.py writes its room '
                     'rows there today, and they become tiers operations; native_api, reflection_map, '
                     'tools/carried_check read', 'ops': {
        'get': 'a tier row by id', 'items': 'view: a persona\'s rows of a kind (doc, from, since, not told in)',
        'last_move': 'the newest move of an item (optionally from, to, reasons)', 'offered': 'an offer row (of an '
        'item or the week, since)', 'of_doc': 'a persona\'s row of a doc', 'personas': 'values: personas with rows '
        'of a kind', 'drop': 'delete a row', 'drop_scenes': 'delete a persona\'s rows of a kind outside these '
        'conversations', 'told': 'add a conversation to told_in', 'recalled': 'add recalled_in, set recalled_at',
        'shown': 'add shown_in', 'surfaced': 'add surfaced_in, set last_use_at', 'upsert': 'create or update a row',
        'mark': 'set fields on a row (gist, confirmed, heading, rewritten, stay days, place)', 'use': 'raise uses',
        'room_told': 'the room words last told in a conversation, and record new ones (carried.py room rows)'}},
    'memory_pilot': {'collections': ['memory_shadow'], 'why': 'only memory_pilot.py and its report tool', 'ops': {
        'rows': 'view: shadow rows of a kind (status, score, since)', 'count': 'count of a kind (since)',
        'forget': 'delete rows of kinds before', 'insert': 'insert a row', 'surfaced': 'add surfaced_in, raise '
        'surfaced', 'synced': 'set status', 'upsert': 'create or update a row', 'drop_all': 'the report tool\'s reset'}},
    'crossing': {'collections': ['crossing_words', 'memory_fires'], 'why': 'crossing.py writes both; memory_tiers '
                 'reads memory_fires once', 'ops': {
        'word': 'a word row by id', 'words': 'view: word rows by ids', 'build': 'replace the vocabulary (insert '
        'many, drop the old generation)', 'raise_generation': 'raise a row\'s seq if still its generation',
        'note_word': 'upsert a word\'s sightings', 'set_vocabulary': 'upsert the build row', 'fire': 'a fire by id, or '
        'by word since', 'fires': 'view: fires of kinds since (optionally of a persona)', 'record_fire': 'insert or '
        'raise a fire', 'forget_fires': 'delete fires before'}},
    'carried': {'collections': ['carried_counts', 'carried_days', 'carried_sections'], 'why': 'only carried.py',
                'ops': {'count_day': 'replace a day\'s counts (create)', 'days': 'values: days counted',
                        'forget_days': 'delete counts and days before', 'note_section': 'upsert a section\'s first '
                        'and last time carried'}},
    'host_lease': {'collections': ['host_leases'], 'why': 'only host_lease.py', 'ops': {
        'acquire': 'take the lease if free, expired or ours, on the database clock', 'renew': 'move expires_at on',
        'release': 'delete our lease', 'mark_planned': 'mark the running Host\'s stop as planned', 'mine':
        'our lease (when it expired, any planned mark)', 'holder': 'whoever holds it (for the refusal)'}},
}

# The shared layer (src/asuna/store/) is no collection's owner: it is the surface every owner is built on.
SHARED = {
    'store.put': 'the revisioned write and its audit row (Store.put)',
    'store.schema': 'declare and ensure the collections (Store.migrate becomes Store.ensure)',
    'store.recover_commits': 'commits without an audit row (Store.recover_commits)',
    'store.seed': 'the test world (tests and probes only)',
    'store.maintenance': 'store-wide reads and writes by declared collection name: audit verify, trace, replay',
    'store.collections': 'the declared collection names',
    'dbread': 'her read facade (dbread and development_database_read)',
    'store.adapter_test': 'the adapter\'s integration test (integration/)',
}

OWNER_OF = {coll: owner for owner, spec in OWNERS.items() for coll in spec['collections']}
for _name in ('artifact_blobs', 'artifact_blobs.files', 'artifact_blobs.chunks', 'gridfs:artifact_blobs'):
    OWNER_OF[_name] = 'blobs'


def fields(shape):
    return set(re.findall(r'([A-Za-z_][\w.]*):', shape))


def only(shape, *names):
    return fields(shape) == set(names)


def op(owner, name):
    if name not in OWNERS[owner]['ops']:
        raise KeyError('%s has no operation %s' % (owner, name))
    return owner + '.' + name


M, S, E, T, P, U, A = (R + n for n in ('messages', 'scenes', 'episodes', 'tasks', 'plans', 'memories', 'artifacts'))


# --- per collection rules: (row) -> operation or None ---------------------------------------------------------

def r_messages(row):
    m, s, ch = row['method'], row['shape'], row['change']
    o = lambda n: op(M, n)
    f = fields(s)
    if m == 'Store.put':
        return o('save')
    if m == 'find_one_and_update':
        return o('claim_unshown')
    if m == 'update_many' and 'errand_told' in ch:
        return o('mark_errands_told')
    if m == 'update_one' and 'recalled_at' in ch:
        return o('mark_recalled')
    if m == 'update_one' and 'failure_detail' in ch:
        return o('note_failure')
    if m == 'distinct':
        if 'artifact_id' in ch:
            return o('artifact_refs')
        if 'field=author' in ch:
            return o('authors')
        if 'field=scene_id' in ch and 'direction:eq=inbound' in s:
            return o('inbound')                          # values(inbound(since=...), 'scene_id')
        return None
    if s.startswith('{_id:val'):
        return o('get')
    if s.startswith('{_id:in'):
        return o('many')
    if m == 'count_documents' and 'delivery_state' in f and 'scene_id' not in f and 'episode_id' not in f:
        return o('unsettled')
    if 'event.visit.intent' in f:
        return o('visits')
    if 'errand_told' in f:
        return o('errand_results')
    if 'ingress_state' in f:
        return o('ingress')
    if 'host_managed' in f:
        return o('channel_inbound')
    if 'channel_id' in f and 'SENDING' in s:
        return o('sending')
    if 'event.group_context.mentioned_account_ids.0' in f:
        return o('mentions')
    if f & {'platform_message_id', 'event.channel.platform_event_id', 'event.event_id', 'platform_event_id'}:
        return o('by_platform_id')
    if 'episode_id' in f:
        return o('turn_parts')
    if 'or({direction:eq=inbound}|{direction:val})' in s:
        return o('lines')
    if 'or({direction:eq=inbound' in s:
        return o('said')
    if 'delivery_state:in=READY/QUEUED_EXTERNAL/SENDING' in s:
        return o('outgoing')
    if 'direction:eq=outbound' in s and ('DELIVERED' in s or 'phase:eq=SPEAK' in s):
        return o('spoken')
    if 'scene_seq:val' in s:
        return o('at')
    if 'direction:eq=inbound' in s:
        return o('inbound')
    if 'scene_id' in f and 'direction' not in f and ('scene_seq' in f or 'sort' in row['mods']):
        if 'event.group_context.wake_reason' in f or 'event.raw.group_name' in f:
            return o('inbound')
        return o('lines')
    if s == '{}' and row['file'].startswith('tools/'):
        return o('lines')                                 # the probe counts every line of its throwaway database
    return None


def r_scenes(row):
    m, s, ch = row['method'], row['shape'], row['change']
    o = lambda n: op(S, n)
    f = fields(s)
    if m == 'Store.put':
        return o('save')
    if m == 'Store.authorize':
        return o('authorize')
    if m == 'find_one_and_update':
        return o('next_seq')
    if m == 'update_one':
        pairs = (('condense_floor', 'set_condense_floor'), ('conversation_size', 'note_size'),
                 ('conversation_tokens', 'note_tokens'), ('character_context', 'set_character_context'),
                 ('timezone', 'set_timezone'), ('asides_shown_seq', 'asides_shown'),
                 ('condensed_told', 'told_condensed'))
        if 'condense_wanted' in ch:
            return o('clear_condense' if ch.startswith('unset') else 'want_condense')
        for key, name in pairs:
            if key in ch:
                return o(name)
        if 'fault' in ch:
            return o('clear_fault' if ch.startswith('unset') else 'note_fault')
        if 'unsent' in ch:
            return o('clear_unsent' if ch.startswith('unset') else 'hold_unsent')
        return None
    if s == '{_id:val}':
        return o('get')
    if 'scope_key:in' in s:
        return o('in_scopes')
    if 'scope_key' in f:
        return o('by_scope')
    if 'condense_wanted' in f:
        return o('condense_wanted')
    if 'channel_id' in f:
        return o('channel_scenes')
    if s.startswith('{_id:in'):
        return o('many')
    if 'kind' in f:
        return o('of_kind')
    if s == '{}':
        return o('all')
    return None


def r_episodes(row):
    m, s = row['method'], row['shape']
    o = lambda n: op(E, n)
    f = fields(s)
    if m == 'Store.put':
        return o('save')
    if s.startswith('{_id:val'):
        return o('get')
    if s.startswith('{_id:in'):
        return o('many')
    if 'source_event_id' in f:
        return o('of_source')
    if 'person_id' in f:
        return o('answered')
    if 'scope_key' in f:
        return o('of_scope')
    if 'state' in f:
        return o('open')
    if 'episode_kind' in f:
        return o('of_kind')
    return None


def r_tasks(row):
    m, s, c = row['method'], row['shape'], row['collection']
    o = lambda n: op(T, n)
    f = fields(s)
    if c == 'task_messages':
        if m == 'Store.put':
            return o('save_message')
        if s.startswith('{_id:val'):
            return o('thread_message')
        return o('thread')
    if m == 'Store.put':
        return o('save')
    if m == 'aggregate':
        return o('recent_with_inputs')
    if s.startswith('{_id:val'):
        return o('get')
    if s.startswith('{_id:in'):
        return o('many')
    if '_id:regex' in s:
        return o('by_prefix')
    for key, name in (('continues_task_id', 'continuations'), ('feedback_state', 'awaiting_feedback'),
                      ('lease_expires_at', 'lease_expired'), ('pause_reason', 'paused'),
                      ('finished_at', 'finished_since'), ('episode_id', 'of_episode'), ('scope_key', 'of_scope'),
                      ('created_at', 'created')):
        if key in f:
            return o(name)
    if 'scene_id:in' in s:
        return o('of_conversations')
    if 'state' in f:
        return o('in_states')
    return None


def r_plans(row):
    m, s = row['method'], row['shape']
    o = lambda n: op(P, n)
    f = fields(s)
    if m == 'Store.put':
        return o('save')
    if s.startswith('{_id:'):
        return o('get')
    if m == 'count_documents':
        return o('count_status')
    if 'next_fire_at' in f:
        return o('due')
    if 'last_outcome' in f:
        return o('with_outcome')
    if 'scene_id' in f:
        return o('of_conversation')
    if 'status' in f:
        return o('in_status')
    return None


def r_memory_units(row):
    m, s, ch = row['method'], row['shape'], row['change']
    o = lambda n: op(U, n)
    f = fields(s)
    if m == 'Store.put':
        return o('save')
    if m == 'Store.nearest':
        return o('nearest')
    if m == 'Store.ensure_vectors':
        return o('ensure_vectors')
    if m == 'replace_one':
        return o('tombstone')
    if m == 'update_one' and 'policy_epoch' in ch:
        return o('set_epoch')
    if m == 'update_one' and 'salience' in ch:
        return o('touch_salience')
    if s.startswith('{_id:val'):
        return o('get')
    if s.startswith('{_id:in'):
        return o('many')
    if 'source_event_ids:val' in s:
        return o('summary_of')
    if 'depends_on' in f:
        return o('dependents')
    if only(s, 'scope_key'):
        return o('of_scope')
    if only(s, 'status'):
        return o('alive')
    if 'kind' in f:
        if 'character_id' in f:
            return o('readable')
        return o('of_kind')
    return None


def r_artifacts(row):
    m, s, ch = row['method'], row['shape'], row['change']
    o = lambda n: op(A, n)
    f = fields(s)
    if m == 'Store.put':
        return o('save')
    simple = {'insert_one': 'insert', 'replace_one': 'replace', 'delete_many': 'delete_many', 'delete_one': 'delete',
              'count_documents': 'count_tool', 'update_many': 'erase_scope'}
    if m in simple:
        return o(simple[m])
    if m == 'update_one':
        if 'let_go_at' in ch:
            return o('let_go')
        if 'unset(kept_at' in ch:
            return o('unkeep')
        for key, name in (('last_read_at', 'mark_read'), ('last_sent_at', 'mark_sent'), ('refetched_at', 'restore_bytes'),
                          ('addToSet(copies)', 'add_copy'), ('set(copies)', 'set_copies'),
                          ('days_from', 'set_days_from'), ('kept_why', 'keep_why'),
                          ('received_from', 'set_received_from'), ('bytes_removed_at', 'bytes_removed')):
            if key in ch:
                return o(name)
        if ch == 'set':
            return o('set_fields')
        return None
    if s.startswith('{_id:in'):
        return o('by_ids')
    if s.startswith('{_id:'):
        return o('get')
    if 'task_id:in' in s:
        return o('of_tasks')
    for key, name in (('task_id', 'of_task'), ('sha256', 'by_content'), ('answer', 'answer'),
                      ('channel_id', 'admission'), ('copies.0', 'with_copies'), ('kept_at', 'kept'),
                      ('scene_id', 'of_scene')):
        if key in f:
            return o(name)
    if only(s, 'storage'):
        return o('stored')
    if 'kind' in f:
        return o('of_kind')
    return None


def r_blobs(row):
    m, c = row['method'], row['collection']
    o = lambda n: op('blobs', n)
    if m == 'upload_from_stream':
        return o('put_stream')
    if m == 'open_download_stream':
        return o('open')
    if m == 'delete':
        return o('delete')
    if c == 'artifact_blobs.files' and m == 'find':
        return o('erase_scope')
    if c == 'artifact_blobs.files' and m == 'find_one':
        return o('exists')
    if c == 'artifact_blobs.files' and m == 'update_one':
        return o('put_stream')            # put_stream records the hash itself; no second write
    if m == 'count_documents':
        return o('stats')
    return None


def r_sessions(row):
    m, s = row['method'], row['shape']
    o = lambda n: op(R + 'sessions', n)
    f = fields(s)
    if m == 'Store.put':
        return o('save')
    if m == 'update_one':
        return o('invalidate')
    if s.startswith('{_id:val'):
        return o('get')
    for key, name in (('successor_id', 'successors'), ('scope_key', 'of_scope'), ('native_title', 'titled'),
                      ('main_conversation', 'main'), ('native_host', 'native')):
        if key in f:
            return o(name)
    return None


def r_receipts(row):
    m, s, c = row['method'], row['shape'], row['collection']
    o = lambda n: op(R + 'receipts', n)
    if c == 'lane_receipts':
        if m == 'Store.put':
            return o('save_lane')
        if m == 'replace_one':
            return o('lane_invalidate')
        if s.startswith('{_id:val'):
            return o('lane_get')
        return o('lane_of_sessions')
    if m == 'Store.put':
        return o('save_sink')
    if s.startswith('{_id:val'):
        return o('sink_get')
    if s.startswith('{_id:in'):
        return o('sinks')
    if s == '{}' and row['file'].startswith('tools/'):
        return o('sinks')                                 # the probe counts its throwaway database's receipts
    if 'kind' in fields(s):
        return o('sink_of_kind')
    return None


def r_audit(row):
    m, s = row['method'], row['shape']
    o = lambda n: op('audit', n)
    f = fields(s)
    if m == 'aggregate':
        return o('latest_kept')
    if m == 'command':
        return o('size')
    if m == 'delete_many':
        return o('prune')
    if m == 'insert_one' or (m == 'find_one' and only(s, 'stream_id')):
        return o('append')
    if m == 'distinct':
        return o('streams')
    if m == 'replace_one' or (m == 'find' and only(s, 'stream_id')):
        return o('redact_streams')
    if m == 'find' and s.startswith('{_id:nin'):
        return o('prune')
    if m == 'count_documents':
        return o('count')
    if 'payload.operation' in f:
        return o('commit_of')
    if 'payload.document._id' in f or 'payload.id' in f:
        return o('of_document')
    if m == 'find_one':
        return o('last')
    if m == 'find' and only(s, 'type') and 'limit' in row['mods']:
        return o('recent')
    if m == 'find' and 'type' in f:
        return o('events')
    return None


def r_heads(row):
    m, s, c = row['method'], row['shape'], row['collection']
    o = lambda n: op(R + 'heads', n)
    f = fields(s)
    store_ops = {'Store.head': 'current', 'Store.init_head': 'init', 'Store.mutate': 'mutate'}
    if m in store_ops:
        return o(store_ops[m])
    if c == 'state_heads':
        if m == 'Store.put':
            return o('save_head')
        if m == 'delete_one':
            return o('drop_head')
        if m == 'update_one':
            return o('point_to')
        if '_id:regex' in s:
            return o('with_prefix')
        if s == '{_id:val}':
            return o('head')
        return o('heads')
    if m == 'Store.put':
        return o('save_revision')
    if m == 'update_one':
        return o('tombstone_revision')
    if '_id:nin' in s:
        return o('stale_revisions')
    if 'mutation_id' in f:
        return o('by_mutation')
    if s.startswith('{_id:val'):
        return o('revision')
    if s.startswith('{_id:in'):
        return o('revisions')
    if 'entity_key' in f:
        return o('history')
    return None


def r_documents(row):
    m, s, c = row['method'], row['shape'], row['collection']
    o = lambda n: op('documents', n)
    f = fields(s)
    if c == 'journal_entries':
        if m == 'Store.put':
            return o('save_entry')
        if m == 'distinct':
            return o('slugs')
        if s.startswith('{_id:val'):
            return o('entry')
        if m == 'find':
            return o('entries')
        return o('last_entry') if 'sort' in row['mods'] else o('entry_of')
    if m == 'Store.put':
        return o('save_revision')
    if s.startswith('{_id:val') or 'mutation_id' in f:
        return o('revision')
    if 'body_sha256' in f:
        return o('revision_of_body')
    if m == 'find':
        return o('revisions')
    return o('last_revision')


def r_people(row):
    m, s, c = row['method'], row['shape'], row['collection']
    o = lambda n: op(R + 'people', n)
    f = fields(s)
    if c == 'identities':
        if m == 'Store.put':
            return o('save_identity')
        if s == '{}':
            return o('all_identities')
        if 'account_id' in f:
            return o('by_account')
        if 'person_id' in f:
            return o('of_person')
        return o('identity')
    if m == 'Store.put':
        return o('save_label')
    if s == '{_id:val}':
        return o('label')
    if 'person:ne' in s:
        return o('labels')
    if only(s, 'person'):
        return o('label_of_person')
    if only(s, 'scene_id'):
        return o('first_label')
    return None


def r_affect(row):
    m, c = row['method'], row['collection']
    o = lambda n: op('affect', n)
    if m == 'count_documents':
        return o('counts')
    one = m == 'find_one'
    return o({'affect_events': ('events', 'event'), 'affect_amendments': ('amendments', 'amendment'),
              'affect_proposals': ('proposals', 'proposal')}[c][one])


def r_stickers(row):
    m, c = row['method'], row['collection']
    o = lambda n: op('stickers', n)
    if m == 'Store.put':
        return o('save')
    if m == 'distinct':
        return o('artifact_ids')
    if c == 'stickers':
        return o({'count_documents': 'shelf_size', 'delete_one': 'drop_sticker', 'find': 'shelf'}.get(m, 'sticker'))
    if c == 'sticker_pool':
        if m.startswith('delete'):
            return o('drop_candidate')
        return o({'count_documents': 'pool_size', 'find': 'pool'}.get(m, 'candidate'))
    return o('memory')


def r_small(owner, mapping):
    def rule(row):
        m, s, ch = row['method'], row['shape'], row['change']
        if m == 'Store.put':
            return op(owner, 'save')
        for test, name in mapping:
            if test(m, s, ch):
                return op(owner, name)
        return None
    return rule


r_notes = r_small('notes', [
    (lambda m, s, c: m == 'update_one', 'seen_in'), (lambda m, s, c: m == 'count_documents', 'count'),
    (lambda m, s, c: s.startswith('{_id:val'), 'get'), (lambda m, s, c: 'reply_to' in s, 'reply_to'),
    (lambda m, s, c: 'question' in s, 'questions'), (lambda m, s, c: 'seen_in' in s, 'last_seen')])
r_watches = r_small('watches', [
    (lambda m, s, c: m == 'update_one', 'seen'), (lambda m, s, c: m == 'count_documents', 'count_active'),
    (lambda m, s, c: s.startswith('{_id:val'), 'get'), (lambda m, s, c: 'person:' in s, 'of_person'),
    (lambda m, s, c: m == 'find', 'active')])
r_questions = r_small('questions', [
    (lambda m, s, c: m == 'update_many', 'told'), (lambda m, s, c: m == 'count_documents', 'count_open'),
    (lambda m, s, c: s.startswith('{_id:val'), 'get'), (lambda m, s, c: 'migrated_from' in s, 'migrated'),
    (lambda m, s, c: 'closed.by' in s, 'closed_untold'), (lambda m, s, c: 'asked_at' in s, 'asked'),
    (lambda m, s, c: 'sources' in s, 'open_in'), (lambda m, s, c: 'persona' in s, 'of_persona')])
r_ideas = r_small(R + 'ideas', [
    (lambda m, s, c: m == 'count_documents', 'count'), (lambda m, s, c: s.startswith('{_id:val'), 'get'),
    (lambda m, s, c: m == 'find', 'of_persona')])
r_inbox = r_small('developer_inbox', [
    (lambda m, s, c: m == 'update_one', 'bump'), (lambda m, s, c: s.startswith('{_id:val'), 'get'),
    (lambda m, s, c: 'source.by' in s, 'of_persona')])
r_group_members = r_small('group_members', [(lambda m, s, c: True, 'get')])
r_own_mutes = r_small('own_mute', [(lambda m, s, c: True, 'get')])
r_switches = r_small('switches', [
    (lambda m, s, c: s.startswith('{_id:val'), 'get'), (lambda m, s, c: 'cleared_at' in s, 'changed')])
r_host_stops = r_small('host_stops', [
    (lambda m, s, c: m == 'update_many', 'mark_shown'), (lambda m, s, c: s.startswith('{_id:val'), 'get'),
    (lambda m, s, c: s.startswith('{how:in'), 'unshown'), (lambda m, s, c: 'back_at' in s, 'last_back')])
r_missed = r_small('host_stops', [
    (lambda m, s, c: m == 'delete_many', 'forget_missed'), (lambda m, s, c: m == 'update_one', 'note_missed'),
    (lambda m, s, c: m == 'find', 'missed')])
r_lane_faults = r_small('lane_faults', [(lambda m, s, c: True, 'count')])
r_memory_shadow = r_small('memory_pilot', [
    (lambda m, s, c: m == 'create_index', 'rows'),          # its index becomes a declared one (store.schema)
    (lambda m, s, c: m == 'drop', 'drop_all'), (lambda m, s, c: m == 'count_documents', 'count'),
    (lambda m, s, c: m == 'delete_many', 'forget'), (lambda m, s, c: m == 'insert_one', 'insert'),
    (lambda m, s, c: 'surfaced' in c, 'surfaced'), (lambda m, s, c: m == 'update_many', 'synced'),
    (lambda m, s, c: m == 'update_one', 'upsert'), (lambda m, s, c: m == 'find', 'rows')])
r_memory_tiers = r_small('memory_tiers', [
    (lambda m, s, c: m == 'delete_one', 'drop'), (lambda m, s, c: m == 'delete_many', 'drop_scenes'),
    (lambda m, s, c: m == 'distinct', 'personas'), (lambda m, s, c: m == 'update_many', 'told'),
    (lambda m, s, c: 'recalled_in' in c, 'recalled'),
    (lambda m, s, c: 'shown_in' in c and 'setOnInsert' not in c, 'shown'),
    (lambda m, s, c: 'surfaced_in' in c, 'surfaced'), (lambda m, s, c: 'inc(uses)' in c, 'use'),
    (lambda m, s, c: m == 'update_one' and ('setOnInsert' in c or c in (
        'set', 'set(at,doc,order,persona,row)', 'set(day,persona,row,scene_id)')), 'upsert'),
    (lambda m, s, c: m == 'update_one', 'mark'),
    (lambda m, s, c: s.startswith('{_id:val'), 'get'), (lambda m, s, c: 'what:' in s, 'offered'),
    (lambda m, s, c: 'item:val' in s, 'last_move'), (lambda m, s, c: m == 'find_one' and 'doc:val' in s, 'of_doc'),
    (lambda m, s, c: True, 'items')])
r_crossing = r_small('crossing', [
    (lambda m, s, c: m == 'insert_many', 'build'), (lambda m, s, c: m == 'delete_many' and 'generation' in s, 'build'),
    (lambda m, s, c: m == 'delete_many', 'forget_fires'), (lambda m, s, c: 'generation:val' in s, 'raise_generation'),
    (lambda m, s, c: 'vocabulary' in c, 'set_vocabulary'), (lambda m, s, c: 'theirs' in c, 'note_word'),
    (lambda m, s, c: m in ('insert_one', 'update_one'), 'record_fire')])


def r_crossing_rows(row):
    hit = r_crossing(row)
    if hit:
        return hit
    many = row['method'] == 'find'
    if row['collection'] == 'crossing_words':
        return op('crossing', 'words' if many else 'word')
    return op('crossing', 'fires' if many else 'fire')


r_carried = r_small('carried', [
    (lambda m, s, c: m == 'delete_many', 'forget_days'), (lambda m, s, c: m == 'distinct', 'days'),
    (lambda m, s, c: m == 'replace_one', 'count_day'), (lambda m, s, c: m == 'update_one', 'note_section')])


def r_host_leases(row):
    line, m = int(row['line']), row['method']
    o = lambda n: op('host_lease', n)
    if m == 'delete_one':
        return o('release')
    if m == 'find_one':
        return o('mine') if 'instance' in row['shape'] else o('holder')
    return {71: o('acquire'), 75: o('acquire'), 85: o('renew'), 111: o('mark_planned')}.get(line)


RULES = {'messages': r_messages, 'scenes': r_scenes, 'episodes': r_episodes, 'tasks': r_tasks, 'task_messages': r_tasks,
         'plans': r_plans, 'memory_units': r_memory_units, 'artifacts': r_artifacts, 'gridfs:artifact_blobs': r_blobs,
         'artifact_blobs.files': r_blobs, 'artifact_blobs.chunks': r_blobs, 'sessions': r_sessions,
         'lane_receipts': r_receipts, 'sink_receipts': r_receipts, 'audit_events': r_audit, 'state_heads': r_heads,
         'state_revisions': r_heads, 'journal_entries': r_documents, 'journal_revisions': r_documents,
         'identities': r_people, 'scene_people': r_people, 'affect_events': r_affect, 'affect_amendments': r_affect,
         'affect_proposals': r_affect, 'stickers': r_stickers, 'sticker_pool': r_stickers, 'sticker_memory': r_stickers,
         'notes': r_notes, 'watches': r_watches, 'questions': r_questions, 'ideas': r_ideas,
         'developer_inbox': r_inbox, 'group_members': r_group_members, 'own_mutes': r_own_mutes,
         'switches': r_switches, 'host_stops': r_host_stops, 'missed_looks': r_missed, 'lane_faults': r_lane_faults,
         'memory_shadow': r_memory_shadow, 'memory_tiers': r_memory_tiers, 'crossing_words': r_crossing_rows,
         'memory_fires': r_crossing_rows, 'carried_counts': r_carried, 'carried_days': r_carried,
         'carried_sections': r_carried, 'host_leases': r_host_leases}

from hand import HAND  # noqa: E402  'file:line' -> (operation, what the code asks), read in the code


DYNAMIC = re.compile(r'<var>|\*\*|<key>|<dynamic>|<database>')


def assign(row):
    key = '%s:%s' % (row['file'], row['line'])
    if key in HAND:
        return HAND[key][0], 'hand'
    method = row['method']
    if method == 'Store.audit':
        return op('audit', 'append'), 'rule'
    if method == 'Store.migrate':
        return 'store.schema', 'shared'
    if method == 'Store.seed':
        return 'store.seed', 'shared'
    if method == 'Store.recover_commits':
        return 'store.recover_commits', 'shared'
    if row['file'].startswith('integration/'):
        return 'store.adapter_test', 'shared'
    if method == 'command' and row['collection'] == 'command:ping':
        return 'store.ping', 'shared'
    if DYNAMIC.search(row['shape']) or DYNAMIC.search(row['change']) or DYNAMIC.search(row['collection']) \
            or '|' in row['collection']:
        return 'UNASSIGNED', ''                      # dynamic or merged: by hand only
    rule = RULES.get(row['collection'])
    if rule:
        name = rule(row)
        if name:
            return name, 'rule'
    return 'UNASSIGNED', ''


def count_ops():
    return sum(len(spec['ops']) for spec in OWNERS.values())


def markdown():
    out = ['| owner | collections | why one owner | operations |', '|---|---|---|---|']
    for owner, spec in OWNERS.items():
        ops = '; '.join('`%s` %s' % (name, meaning) for name, meaning in spec['ops'].items())
        out.append('| `%s` | %s | %s | %s |' % (owner, ', '.join(spec['collections']), spec['why'], ops))
    return '\n'.join(out)


if __name__ == '__main__':
    print('owners', len(OWNERS), 'operations', count_ops(),
          'collections', sum(len(spec['collections']) for spec in OWNERS.values()))
    if '--markdown' in sys.argv:
        print(markdown())
