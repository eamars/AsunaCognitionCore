# ADR-124: Image routes say what they need, and take it

Status: **Proposed** 2026-11-10 (laid down; nothing built). Her request on the agent line (0215, 2026-11-10), from her
idea `idea-ff702804`: three verdicts on `generate_image`, the action brain's drawing tool.

## 1. What is known

- `integration_image.list_workflows` drops every ready route whose `parameter_schema.required` names a picture other
  than `input_image` (`unsupplied`: an inpaint mask and the like). The route is not in what `list_routes=yes` returns,
  and nothing says it was left out. Asking for it by name is refused with `IMAGE_WORKFLOW_NEEDS_MORE_PICTURES`, whose
  note says it is not in the list.
- `generate_image` takes one picture, `source_image`, uploaded as the route's `input_image`. No other picture reaches
  the service.
- Her reading (2026-11-09, three orders): every one of the 18 routes she was shown takes one picture; an inpaint route
  was refused for the missing picture and did not appear in the list. To her a hidden route reads as "the service
  cannot do this", not "I did not give it something".

## 2. Her three verdicts

| # | Item | Her verdict |
|---|---|---|
| R1 | `list_routes` lists the filtered routes too, each with the pictures it still needs | Take it |
| R2 | A required picture slot other than the source (`mask_image` and the like) open, so an inpaint route can be driven | Take it |
| R3 | Repeatable picture slots (a list, or `source_image` plus `reference_image`) | Only after the service is shown to have a ready edit route driven by several pictures; no slot for a route that does not exist |

## 3. To design before building

- R1: how a route that cannot run yet reads in the list (her wording), and whether R2 makes R1's "needs" empty for
  the slots it opens.
- R2: where the extra picture comes from (a picture of hers by ref or `artifact_id`, read through `read_image`'s
  fence like `source_image`; a mask she draws with `render_svg`), how its name maps to the route's parameter, the
  upload and the `forget` after the job for each picture, and the size cap per picture.
- R3: read the service's workflow list (metadata only, no drawing) for a ready route with more than one picture
  parameter. None: R3 is dropped with that reading as its reason.

## 4. Closes when

Each of R1 to R3 is built and shown end to end on the real service in the action brain (R1: the list shows the inpaint
route and what it needs; R2: an inpaint job driven with a mask, its picture read back with `read_image`), or dropped
with its reason (R3: the workflow listing that shows no multi-picture route). She reads R1's wording before it is built.
