# ADR-120: Bringing stored things back into the work

Status: **Proposed** 2026-11-09 (laid down; not designed, not built). Her request, gathered into one class at big
sis's ask (agent line 0035, 2026-11-05 16:01: nine dated incidents with their idea ids). Repro material: her
2026-11-02 four-part bundle, which she has kept.

## 1. The gap

The program keeps "what is stored" and "what this turn can use or send" as two worlds, with no way across for her or
the action brain. It is one gap, in four directions:

1. **A stored thing's body by its id.** `read_file` does not take a blob id, `read_image` takes only images,
   `received_file` takes only this turn's `att-…` refs, and `web_fetch` takes no `file://`. From a task, the DATA path
   is `PATH_DENIED`. Seen 10-26, 11-02 and 11-04 (the last two relayed by her home turn).
2. **A public URL's bytes into `/task`.** `web_fetch` refuses `image/*` (`unsupported content type`), and no tool
   writes fetched bytes into `/task`. Seen 10-15, 10-19 and 10-24.
3. **An old image product onto this turn's sendable list.** `offer_file` takes only `/task` paths; a blob id, a store
   path and a disk path are each refused. Once she redrew a picture instead, which meant a second generation and
   different pixels. Seen 10-27 and 10-31.
4. **A viewed frame into a picture she can send.** A video reaches her as timed still grids, and a frame cannot
   become a picture she sends. Seen 10-21 (the refusal text is to be pulled from the store by its id), with two more
   readings since.

Not in this ADR (her line): the two image-generation recipe items, which are their own bundle.

## 2. Closes when

Each of the four directions has a designed path in her wording, with each lane's trust boundary kept (a public task
never reads home-only data). Each is built, and her repro bundle plus one staged case per direction go through end
to end. A direction may be dropped only with the reason written here.

## 3. Undecided

- One tool per direction, or one transfer that takes any stored ref (she leaves this choice to us).
- Which lane may move what: home vs public, the action brain vs her.
- Size limits for fetched bytes, and what is recorded as an artifact.
- Whether the owner's 11-05 report (an image delivered, its text not) belongs to this class or to the outbound one.
