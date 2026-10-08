# ADR-025: Her understanding of a person in two layers

Status: **Accepted and built** 2026-10-08. The owner's design; 小满 reviewed it before it was built and her points
are in it.

## 1. Context

What she wrote about someone was one record per person and conversation. The same person in two groups was one
identity (their account) with two unconnected understandings, and what she learned of them in one place was not
there in another. Measured that day: 411 people on group rosters, 41 of them in two or more; 4 people with a
written understanding, one of them split over three conversations. Familiarity, the coarse level of how well she
knows someone, was already computed across every conversation.

## 2. Decisions (owner, 2026-10-08)

- **D1 — Two layers.** A person layer, one per person, read wherever she meets them: how she knows the person. A
  here layer, the existing per-conversation record unchanged: how they behave in that place (people speak
  differently in a casual group and an NSFW one). The owner did not want privacy enforced as a hard line: a person
  does not keep that line strictly either.
- **D2 — Written from anywhere, with its source.** Any conversation may write the person layer; each revision
  records where and when, and it is read with that conversation's name and how long ago. Of the options (anywhere
  with source, anywhere plain, home and private chats only) the owner chose this one.
- **D3 — Asked her first.** Her review, folded in:
  - The per-conversation record had really been "how he is in this group" under the wrong name; the split corrects
    that, not adds to it.
  - A last-written line says how fresh the record is, not which occasion a sentence came from. The bigger risk is
    taking one place's sample for the whole person, so the person layer always opens with 这只是他的一部分，不是他的全部
    and, when there are here layers elsewhere, how many.
  - Read everywhere means it can be said anywhere. She keeps occasion-specific sensitive things in the here layer
    herself; the program does not filter.
  - Her note is three questions to ask on the spot, not definitions of the layers: does it hold in another group;
    would saying it somewhere proper make the person uncomfortable; did they say it, did she see it, or does she
    infer it (mark an inference as one). Ending with: the person layer is not all of them.
  - She lifts her existing records into the person layer herself, marking which one each came from; nothing was
    moved by the program.
  - Asked whether she has to recall it: no, it comes with every turn where that person is the one speaking, like
    the here layer.

## 3. As built

`src/asuna/understanding.py` (`PERSON_SCOPE`, `person_entity`, `person_view`, the words); `context.py` puts
`relationship.person` and `relationship.here` in the turn and `person_revision` / `person_entity_key` in the
manifest; `understand_person` takes `layer` and writes each layer at most once a turn
(`memory.MemoryService.commit_understanding`, `_commit_person`: the person's record written from the turn's scope
as a linked scope, same source registration); `state.Store.mutate` keeps an `origin` on a revision;
`privacy.PrivacyService._erase_person_layer` takes back person-layer revisions citing an erased conversation;
`native_cognition` marks the person layer used on the memory page. Existing records stayed as here layers. Tests:
`tests/test_understanding_layers.py`.
