# ADR-125: An image the platform took too long to accept is sent but unknown

Status: **Proposed** 2026-11-11 (laid down; nothing built). The owner asked her about pictures that seemed lost
(her home line, 2026-11-10); big sis read the adapter's journals (structure, states and codes only), and her readings
(agent line 0333, 0334) corrected two points. Her answer to the owner: a picture may have arrived even though the
record cannot show it.

## 1. What is known (2026-11-10)

- 65 image sends from 2026-10-09 to 2026-11-09 ended `UNKNOWN`, each with NapCat's `retcode` 1200 and the message
  `Timeout: NTEvent serviceAndMethod:NodeIKernelMsgService/sendMsg`: the platform client stopped waiting for its own
  upload, not a refusal. 64 of the 65 are PNG. The rate rises with size: about 1% under 256 KB, 35% at 2 MB and more.
- An `UNKNOWN` send has no `platform_message_id`. So the read-back that checks a send (`outbound.py`, only for
  `platform_accepted`) never runs, and the picture cannot be recalled. One cause, both symptoms.
- The adapter never sees her own sent messages: `message_sent` is in `NOT_PROJECTED` (`qqadapter/notices.py`), and
  catch-up's history read drops her own lines (`qqadapter/catchup.py`, `take`). Catch-up's history read is the one
  place that already fetches what the platform holds for a group.
- At least one timed-out picture did arrive (her counterexample): a DM image of 2026-10-24, retcode 1200, is on the
  platform. So `UNKNOWN` is not "lost".
- Notices held in a group without a gate (`held_notice`, `src/asuna/notices.py`) are not missing: 31 were held from
  2026-11-03 and each was shown once and deleted, as designed. A held row keeps its notice kind only inside the stored
  event (`row`), so a reading cannot count them by kind without opening each.

## 2. Items

| # | Item | Closes when |
|---|---|---|
| G1 | Large images shrunk before they are sent | Her image skill is planned to shrink a large picture first (her idea, not yet built); the program is the backstop: a picture over a size threshold is re-encoded before the upload. Threshold, format and the quality she accepts are designed with her from the size table above; shown by a picture over the threshold leaving at its new size |
| G2 | An `UNKNOWN` send settled from the platform's history | After an `UNKNOWN` image send in a group, the platform's history for that group is read once for her own line carrying that picture in the send's window; found, the send is settled with its `platform_message_id` (read-back and recall work again); not found, it stays `UNKNOWN` and says so. DMs: designed only if the platform's DM history can be read the same way, else dropped for DMs with that reason. Shown by a staged timeout on the adapter's fake platform, and by the first real one after install, which she reports |
| G3 | A held notice carries its kind | The `held_notice` row carries the notice kind beside `row`, so the held notices can be counted by kind; written for new rows only (no history conversion) |

## 3. Closes when

G1 to G3 each built and shown as in its row, or dropped with its reason. G1's threshold and G2's wording are hers to
read before they are built.
