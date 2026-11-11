# ADR-120: Bringing stored things back into the work

Status: **Proposed** 2026-11-09 (laid down; not designed, not built). ADR-124 (image routes, her request of
2026-11-10) merged in on 2026-11-11 at the owner's word, as §4: R2's extra picture is a stored picture brought into a
tool, this ADR's own question, so the two are designed and built together. Her request, gathered into one class at big
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
to end. A direction may be dropped only with the reason written here. The image routes close as §4.4 says.

## 3. Undecided

- One tool per direction, or one transfer that takes any stored ref (she leaves this choice to us).
- Which lane may move what: home vs public, the action brain vs her.
- Size limits for fetched bytes, and what is recorded as an artifact.
- Whether the owner's 11-05 report (an image delivered, its text not) belongs to this class or to the outbound one.

## 4. The image routes (ADR-124, merged 2026-11-11)

Her request on the agent line (0215, 2026-11-10), from her idea `idea-ff702804`: three verdicts on `generate_image`,
the action brain's drawing tool. R1 needs no transfer and can be built on its own; R2 waits for this ADR's transfer
(where its picture comes from).

### 4.1 What is known

- `integration_image.list_workflows` drops every ready route whose `parameter_schema.required` names a picture other
  than `input_image` (`unsupplied`: an inpaint mask and the like). The route is not in what `list_routes=yes` returns,
  and nothing says it was left out. Asking for it by name is refused with `IMAGE_WORKFLOW_NEEDS_MORE_PICTURES`, whose
  note says it is not in the list.
- `generate_image` takes one picture, `source_image`, uploaded as the route's `input_image`. No other picture reaches
  the service.
- Her reading (2026-11-09, three orders): every one of the 18 routes she was shown takes one picture; an inpaint route
  was refused for the missing picture and did not appear in the list. To her a hidden route reads as "the service
  cannot do this", not "I did not give it something".

### 4.2 Her three verdicts

| # | Item | Her verdict |
|---|---|---|
| R1 | `list_routes` lists the filtered routes too, each with the pictures it still needs | Take it |
| R2 | A required picture slot other than the source (`mask_image` and the like) open, so an inpaint route can be driven | Take it |
| R3 | Repeatable picture slots (a list, or `source_image` plus `reference_image`) | Only after the service is shown to have a ready edit route driven by several pictures; no slot for a route that does not exist |

### 4.3 To design before building

- R1: how a route that cannot run yet reads in the list (her wording), and whether R2 makes R1's "needs" empty for
  the slots it opens.
- R2: where the extra picture comes from (a picture of hers by ref or `artifact_id`, read through `read_image`'s
  fence like `source_image`; a mask she draws with `render_svg`), how its name maps to the route's parameter, the
  upload and the `forget` after the job for each picture, and the size cap per picture.
- R3: read the service's workflow list (metadata only, no drawing) for a ready route with more than one picture
  parameter. None: R3 is dropped with that reading as its reason.

### 4.4 Its part of the closing condition

Each of R1 to R3 is built and shown end to end on the real service in the action brain (R1: the list shows the inpaint
route and what it needs; R2: an inpaint job driven with a mask, its picture read back with `read_image`), or dropped
with its reason (R3: the workflow listing that shows no multi-picture route). She reads R1's wording before it is built.
