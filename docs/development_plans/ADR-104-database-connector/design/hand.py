"""ADR-104 call sites assigned by hand: every dynamic or merged condition (a condition held in a variable, a dict
merged with **, a key computed at run time) and every collection chosen at run time, each read in the code at
main 5a62ebd6a171. 'file:line' -> (owner operation, what the code asks). All calls on one line share the entry.
"""
M, S, E, T, U, A = ('records.messages.', 'records.scenes.', 'records.episodes.', 'records.tasks.',
                    'records.memories.', 'records.artifacts.')

HAND = {
    'src/asuna/affect.py:394': ('affect.insert', 'the ledger\'s own insert into one of its three collections'),
    'src/asuna/affect.py:396': ('affect.insert', 'the replay check inside insert: the stored row by id or by '
                                '(persona, origin, source_identity)'),
    'src/asuna/audit.py:113': ('store.maintenance', 'verify_documents: each committed document by (collection, id)'),
    'src/asuna/audit.py:134': ('store.maintenance', 'trace_contents: a committed document by (collection, id)'),
    'src/asuna/audit.py:151': ('store.maintenance', 'replay: the target must hold no heads, tasks or lines'),
    'src/asuna/audit.py:168': ('store.maintenance', 'replay: the target\'s current record by id'),
    'src/asuna/audit.py:170': ('store.maintenance', 'replay: write the replayed record (create)'),
    'src/asuna/audit.py:175': ('store.maintenance', 'projection: four collections in id order'),
    'src/asuna/channels.py:168': (M + 'by_platform_id', 'reply_parent: the inbound line of a platform event id, or '
                                  'her delivered line of a platform message id (optionally by author), this epoch'),
    'src/asuna/channels.py:509': (M + 'queued', '_next: the channel\'s queued lines; the query is built in claim() '
                                  'from channel, lane (file or chat) and route target, which become the view\'s '
                                  'parameters'),
    'src/asuna/channels.py:512': (M + 'in_flight_scenes', 'conversations with a chat line SENDING (not a file) '
                                  'claimed since the chat lease'),
    'src/asuna/carried.py:322': ('memory_tiers.room_told', 'room_block: the words last told in this conversation '
                                 '(a row carried.py keeps in memory_tiers)'),
    'src/asuna/carried.py:325': ('memory_tiers.room_told', 'room_block: record the words told (create)'),
    'src/asuna/cli.py:74': ('audit.trace', 'the cli trace: every event, or one stream, in (stream, seq) order'),
    'src/asuna/condense.py:174': (S + 'apply_condense', 'the condense result: unset wanted, floor, told; set '
                                  'condensed_at, condensed_by, conversation_tokens when compacted'),
    'src/asuna/context.py:421': (M + 'said', 'the turn\'s history: said in the epoch, lines people wrote only before '
                                 'the turn\'s source position, newest first, a group\'s or a chat\'s count'),
    'src/asuna/context.py:557': (U + 'readable', 'the development fallback: six alive memories of the readable '
                                 'pairs in id order'),
    'src/asuna/crossing.py:201': (U + 'many', 'chat chunks by ids, alive, hers, in these (scope, epoch) pairs'),
    'src/asuna/crossing.py:481': ('records.heads.history + documents.last_revision',
                                  'versions: the newest revision of a document in each of its two ledgers (one loop '
                                  'over two collections becomes two owner calls)'),
    'src/asuna/dbread.py:109': ('dbread', 'her facade: the collection must be one of the allowlisted declared ones'),
    'src/asuna/dbread.py:119': ('dbread', 'her facade: fields() becomes the declared fields of the collection'),
    'src/asuna/dbread.py:170': ('dbread', 'her facade: find'),
    'src/asuna/dbread.py:180': ('dbread', 'her facade: count'),
    'src/asuna/dbread.py:183': ('dbread', 'her facade: distinct becomes values (group without a total)'),
    'src/asuna/dbread.py:190': ('dbread', 'her facade: aggregate becomes group'),
    'src/asuna/dbread.py:254': ('dbread', 'her facade: collections() lists the allowlisted declared collections'),
    'src/asuna/developer_inbox.py:39': ('developer_inbox.unread', 'new items, optionally of a level, oldest first'),
    'src/asuna/dialogue_summary.py:70': (M + 'said', '_pending: said, people only, after the summary start, not yet '
                                         'in a summary batch, oldest first, a window'),
    'src/asuna/dialogue_summary.py:85': (M + 'said', 'the same query read again after completing a crashed batch'),
    'src/asuna/dice.py:168': ('audit.last', 'the newest presence.rolled since the floor that reached a review, not '
                              'this occurrence'),
    'src/asuna/dice.py:172': ('audit.events', 'presence.rolled since the floor (or the last review), not this '
                              'occurrence, newest REVIEW_ROLLS'),
    'src/asuna/discussion_digest.py:182': (M + 'many', 'read_linkage: lines by ids fenced to the digest\'s '
                                           'conversations and epoch'),
    'src/asuna/discussion_digest.py:333': (M + 'replies_to', 'read_thread_continuations: lines replying to the '
                                           'frontier (any reply key) or wanted ids, fenced'),
    'src/asuna/discussion_digest.py:889': (M + 'excluded', 'counts of speech not delivered and of outbound '
                                           'non-speech in the digest\'s conversations and epoch'),
    'src/asuna/forwards.py:65': (M + 'inbound', 'the newest inbound line carrying this forward ref'),
    'src/asuna/group_members.py:102': (M + 'spoken', 'her newest delivered line with a receipt in a group'),
    'src/asuna/group_members.py:114': (M + 'spoken', 'count of her delivered lines in a group since a local day start'),
    'src/asuna/history_query.py:718': ('records.receipts.sink_window', 'receipts in a window from a position, newest '
                                       'first (sink_time_filter)'),
    'src/asuna/history_query.py:750': (M + 'search', 'outbound fallback: her lines by receipt refs, text, author'),
    'src/asuna/history_query.py:812': (M + 'search', 'search_messages: live or archived lines by scenes, epoch, '
                                       'authors, text (case), window, position'),
    'src/asuna/host.py:42': (S + 'save / records.people.save_identity', 'prepare_channels\' local put(collection, '
                             '...): called for identities (lines 93, 105) and scenes (117, 132); each call becomes '
                             'that owner\'s save'),
    'src/asuna/host_lease.py:71': ('host_lease.acquire', 'take the lease where it expired on the database clock or '
                                   'is ours'),
    'src/asuna/host_lease.py:75': ('host_lease.acquire', 'no lease yet: insert one; a duplicate means someone else '
                                   'holds it'),
    'src/asuna/lines.py:51': (M + 'inbound', 'count of asides on a line since she last spoke there'),
    'src/asuna/lines.py:54': (M + 'inbound', 'the newest asides on a line since she last spoke'),
    'src/asuna/lines.py:80': (M + 'inbound', 'count of asides after the last shown seq'),
    'src/asuna/memory.py:209': (M + 'said', 'chunk: said in a conversation (any epoch), people only, in order'),
    'src/asuna/memory_pilot.py:307': ('memory_pilot.rows', 'turn rows since'),
    'src/asuna/memory_pilot.py:308': ('memory_pilot.rows', 'recall rows since'),
    'src/asuna/memory_pilot.py:339': ('audit.events', 'recall.read events since'),
    'src/asuna/memory_pilot.py:366': ('memory_pilot.count', 'failure rows since'),
    'src/asuna/memory_tiers.py:207': ('memory_tiers.items', 'the owner\'s own items view with its keyword fields'),
    'src/asuna/native_api.py:263': (M + 'inbound', 'the newest 2000 lines people wrote in this conversation, by '
                                    'occurred_at'),
    'src/asuna/native_api.py:461': (M + 'web_page / ' + U + 'web_page', 'the Web memory page: one aggregate on lines '
                                    'or on memories, split into the two owners\' page operations'),
    'src/asuna/native_api.py:586': (U + 'get', 'a memory by id within the page\'s readable pairs'),
    'src/asuna/native_api.py:610': (M + 'said', 'a source line by id within the page\'s sources (said, people only)'),
    'src/asuna/native_api.py:630': (M + 'said', 'up to 12 source lines by ids within the page\'s sources'),
    'src/asuna/native_api.py:634': (U + 'many', 'source units by ids within the readable pairs'),
    'src/asuna/native_cognition.py:36': ('audit.events', 'the newest 24 events of her streams (or one turn\'s)'),
    'src/asuna/native_cognition.py:38': (E + 'get', 'a turn by id within the snapshot\'s fence'),
    'src/asuna/native_worker.py:670': ('records.sessions.of_task', 'the newest action session of a task or the task '
                                       'it continues'),
    'src/asuna/native_worker.py:674': ('records.sessions.of_task', 'else the newest session of the query'),
    'src/asuna/native_worker.py:961': (M + 'inbound', 'the newest inbound line carrying the group or peer name'),
    'src/asuna/native_worker.py:1460': ('dbread', 'development_database_read: her action brain\'s read tool, the '
                                        'same facade'),
    'src/asuna/notes.py:330': ('notes.count', 'today\'s notes from here to there'),
    'src/asuna/notes.py:335': ('notes.count', 'today\'s untrusted group notes'),
    'src/asuna/notes.py:339': ('notes.count', 'today\'s notes between these two groups (either way)'),
    'src/asuna/people.py:415': (M + 'inbound', 'lines whose peer card, nickname, display or alias equals a name'),
    'src/asuna/people.py:549': (M + 'pointable', 'the turn\'s own line if pointable'),
    'src/asuna/people.py:551': (M + 'pointable', 'the pointable line at a seq'),
    'src/asuna/people.py:555': (M + 'pointable', 'the recent pointable lines'),
    'src/asuna/people.py:653': (S + 'get / ' + S + 'by_scope', 'a conversation by id, else by scope'),
    'src/asuna/places.py:238': (M + 'inbound', 'authors of lines people wrote in the last hour, this epoch'),
    'src/asuna/places.py:244': (M + 'inbound', 'the first line after hers that called her (wake reasons), people only'),
    'src/asuna/places.py:321': (M + 'inbound', 'whether anyone answered after her visit line, people only'),
    'src/asuna/privacy.py:92': (E + 'redact_scope / ' + T + 'redact_scope / ' + M + 'redact_scope / ' + A +
                                'redact_scope / records.receipts.redact_scope',
                                'the erasure loop over five collections becomes each owner\'s redact_scope'),
    'src/asuna/privacy.py:100': (E + 'redact_scope / ' + T + 'redact_scope / ' + M + 'redact_scope / ' + A +
                                 'redact_scope / records.receipts.redact_scope',
                                 'its replace with the retained fields, inside each owner\'s redact_scope'),
    'src/asuna/proactive.py:101': (M + 'said', 'observe: said in the epoch (inbound or delivered outbound)'),
    'src/asuna/proactive.py:252': (M + 'lines', 'chain: live lines (in or out) up to a position'),
    'src/asuna/questions.py:188': (M + 'answers', 'group answers after her question line, until a time'),
    'src/asuna/questions.py:263': (M + 'answers', 'lines marked as answering this question, people only, not asides'),
    'src/asuna/questions.py:271': (M + 'answers', 'the first line after hers (by others than the marker)'),
    'src/asuna/questions.py:501': ('questions.asked', 'asked since, to a conversation or from action'),
    'src/asuna/reflection_map.py:179': ('store.collections', 'whether memory_tiers exists becomes: it is declared'),
    'src/asuna/retrieval.py:81': (U + 'pending_index', 'alive memories not READY/REFUSED or of another embedding '
                                  'revision, optionally of one scope and epoch'),
    'src/asuna/retrieval.py:184': (U + 'readable', 'own_thoughts lexical: her monologues in the pairs, newest formed '
                                   '2048'),
    'src/asuna/retrieval.py:194': (U + 'get', 'a ranked monologue by id within the same fence'),
    'src/asuna/retrieval.py:219': (U + 'readable', 'search lexical: alive memories in the pairs, newest 4096'),
    'src/asuna/retrieval.py:267': (U + 'get', 'a ranked memory by id within the fence'),
    'src/asuna/retrieval.py:294': (U + 'get', 'a superseded memory by id within the pairs'),
    'src/asuna/role_tools.py:3189': (T + 'get', 'her task page: by id at home, else fenced to the place'),
    'src/asuna/role_tools.py:3260': ('records.ideas.of_persona', 'her ideas in a state, words contained in idea or why'),
    'src/asuna/scene_links.py:52': (S + 'all', '_rows(db, "scenes") is its only call'),
    'src/asuna/state.py:134': ('store.schema', 'migrate: existing collections'),
    'src/asuna/state.py:137': ('store.schema', 'migrate: create with the validator'),
    'src/asuna/state.py:190': ('store.schema', 'migrate: indexes'),
    'src/asuna/state.py:231': ('store.put', 'put: insert'),
    'src/asuna/state.py:239': ('store.put', 'put: replace keeping counter fields'),
    'src/asuna/state.py:241': ('store.put', 'put: replace at a revision'),
    'src/asuna/state.py:256': ('store.recover_commits', 'documents with _last_op in every writable collection'),
    'src/asuna/state.py:269': (U + 'ensure_vectors', 'step 1a'),
    'src/asuna/state.py:271': (U + 'ensure_vectors', 'step 1a'),
    'src/asuna/state.py:274': (U + 'ensure_vectors', 'step 1a'),
    'src/asuna/state.py:277': (U + 'ensure_vectors', 'step 1a'),
    'src/asuna/state.py:309': (U + 'nearest', 'step 1b'),
    'src/asuna/state.py:317': ('store.maintenance', 'Store.get(collection, key, scope): no caller in src/asuna or '
                               'tools (census at 5a62ebd6); it goes, its scope rules live in the owners\' get'),
    'src/asuna/state.py:346': ('store.seed', 'seed: skip rows already there'),
    'src/asuna/state.py:351': ('store.seed', 'seed: write the world\'s rows'),
    'src/asuna/state.py:435': (M + 'get / ' + A + 'get / ' + E + 'get', 'mutate\'s source check: a cited id in '
                               'lines, artifacts or turns'),
    'src/asuna/stickers.py:170': ('stickers.sticker', 'the same sticker by identity or picture'),
    'src/asuna/stickers.py:409': ('stickers.memory', 'a remembered sticker by key or alias'),
    'src/asuna/stickers.py:422': ('stickers.memory', 'a remembered sticker by md5 key or picture'),
    'src/asuna/stickers.py:465': ('stickers.pool', 'pool candidates here (or all), newest seen first'),
    'src/asuna/stickers.py:505': ('stickers.sticker', 'the same sticker by identity or picture'),
    'src/asuna/stickers.py:673': ('stickers.memory', 'a persona\'s remembered sticker by key or alias'),
    'src/asuna/summary_trigger.py:99': (M + 'said', 'observe: said in the epoch'),
    'src/asuna/switches.py:80': ('switches.on', 'active switches of a kind, conversation or person, by until'),
    'src/asuna/tools_week.py:236': ('audit.events', 'speech tallies in the week'),
    'src/asuna/tools_week.py:240': ('audit.events', 'root tallies of a persona in the week'),
    'src/asuna/tools_week.py:270': ('audit.count', 'thought.taken in the week'),
    'src/asuna/tools_week.py:271': ('audit.events', 'thought.none in the week'),
    'src/asuna/understanding.py:151': (M + 'inbound', 'people only, after a position, wake reasons'),
    'src/asuna/vision.py:410': (M + 'inbound', 'lines with media since a cutoff, in a conversation\'s epoch'),
    'src/asuna/waiting.py:63': (M + 'inbound', 'whether anyone (or this person) wrote after her line, people only'),
    'src/asuna/watches.py:136': ('watches.seen', 'record a sighting if last_seen_at is still the one read'),
}
