# ADR-035: QQ picture links are re-signed when fetched

Status: **Accepted 2026-10-10**, decided by Xiaoman and Claude (the owner left the decision to them). To be built
after her read-by-path change (published the same night), on top of it.

## Context

Pictures in her QQ groups often could not be read a while after they were posted (`IMAGE_FETCH_FAILED`, HTTP 400,
`retcode -5503007`, "download url has expired"). Measured on 2026-10-10 against the stored links:

- A link works for about 7 minutes after it arrives; from 13 minutes on, every link sampled was expired, back to
  three days.
- The picture itself is not gone. Each link carries a signature (`rkey`). With the `rkey` of a link that had just
  arrived, 20 of 20 expired group links up to two days old, and 7 of 7 of the oldest stored (about six days),
  downloaded again. Private-chat pictures (`appid=1406`) take the private key; the group key (`appid=1407`) is
  refused for them (`retcode -5503023`).
- What she ran into over three days: of 15 group turns started by a line with a photo, 12 pictures were pulled with
  the turn (the other 3 turns started after the link expired); her own `read_image` 38 read and 3 expired; the action
  brain, which reads minutes later, failed most often.
- A local cache was weighed: group photos are about 300 a day, 180 MB; three days of them would be about 550 MB, of
  which she looked at about 50 pictures.

## Decision

- **D1. Re-sign, do not store.** Before fetching a picture from the QQ media host, the program replaces the link's
  `rkey` with the current key of the same kind (`appid` 1407 group, 1406 private). Every stored picture is reachable
  again; nothing is downloaded ahead.
- **D2. Where the current keys come from.** The QQ adapter asks NapCat for them (`nc_get_rkey`) every few minutes and
  hands them to the host; a key from a link that arrived in the last few minutes is the fallback.
- **D3. Three answers, not one** (her requirement): the signature is expired and a current key did not help; the
  picture is gone; no current key is available. She can tell whether to wait or give up.
- **D4. A local cache stays the fallback design** for the day QQ removes pictures, not built now.

## Consequences

- Old group pictures, days back, can be read again by her and by the action brain.
- The fix depends on NapCat's key interface and QQ's current signing; D3 makes a change there visible at once.
