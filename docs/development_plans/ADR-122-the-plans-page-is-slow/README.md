# ADR-122: The plans (Automation) page is slow to open

Status: **Proposed** 2026-11-09 (laid down; not measured, not built). Parked on 2026-11-05 until ADR-117 closed, which
it did on 2026-11-09.

## 1. What is known (2026-11-05; to be read again before measuring)

The Web UI's reminder and Automation page is very slow to load. The data then: `schedule.json` was 271 KB (28 plans,
`deliveryHistory` up to about 50 KB each). The scheduler session has been a single session since 2026-10-02, 14.7 MB
compressed, with every firing a turn in it. That session is the first suspect, if the page opens it.

## 2. Closes when

The cause is measured on copies in an isolated review profile (never her live one) and named as Asuna's or DSH's.
Then it is either fixed here, with the page's open time measured before and after, or handed to the owner as a DSH
change with the measurement.

## 3. Undecided

- The scheduler session's lifecycle: a single session for ever is a state with no end. Rotate it, or keep it and fix
  the page's read.
- Whether `deliveryHistory` needs a bound.
