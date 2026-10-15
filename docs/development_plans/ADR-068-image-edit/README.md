# ADR-068: Editing a picture with generate_image

Status: **Accepted 2026-10-15** (the owner chose each point below), built the same day.

## What happened

Her action brain was asked to edit a picture. `generate_image` drew only from text: its route list hid every route
that works from a picture, so the task guessed about fifteen route names (each a 404), then found
`qwen-image-2.1-edit`, which our side refused with `IMAGE_WORKFLOW_NOT_TEXT_TO_IMAGE` and no word on what to do.
The image service could edit all along: upload one picture (`POST /upload/image`), pass its name as the workflow's
`input_image`, give the change as the prompt.

## Decision

1. **One optional parameter, `source_image`**: a picture's ref or `artifact_id`, exactly as `read_image` takes it.
   It is read with `read_image`'s own fence for the task's conversation (`vision.picture_to_edit`): a turn edits
   only a picture it may look at. The route check is skipped, since the bytes go to the service, not to a model.
2. **Where an edit may go** (owner's choice of three): an edit of her own drawing is hers like any drawing. An edit
   of anyone else's picture is not hers: it is kept in the task's scope, marked `edit:<scope>`, and may be sent
   only back to the conversation the picture came from, where it is listed first (`edited_from_here`). The owner's
   private chats still take what their scopes hold. This keeps a photo from one group out of every other group
   by design, without judging its content.
3. **The service owns size and frames** (owner's choice): its `input_fit` defaults to `downscale`, which fits an
   oversized source to the route and takes the first frame of an animated one, and says so in `warnings`
   (`input_downscaled`, `input_resized`, `input_first_frame`, with the original and used size); a real failure
   reports `out_of_memory`; every refusal carries a stable `error.code`. This side passes each warning on with its
   code and sizes, and checks no size of its own beyond the 8 MiB transfer cap. With the default there is no option
   to reveal to the model.
4. **No upload stays on the service**: uploads are named `asuna-edit-<sha>-<random>` and deleted when their job is
   over; one kept for a still-queued job is removed by a later call (older than an hour).
5. **Routes**: `list_routes` lists routes that work from a picture too, marked `source_image: required/optional`;
   without a named route the service picks one (`input_mode=image-edit`). A route that does not fit the call is
   refused naming the missing or extra field.

## Cost to each brain

Action brain: one optional parameter (`source_image`) on an existing tool, and 150 more description characters
(the tool 1808 → 1994 characters). Character brain: nothing. No per-turn lines.

## Also fixed

Each trusted integration run (an image or a fetch) left its folder under `integration/owner/runs` (955 folders,
41 MB since 2026-09-22); the folder is now removed when the run ends.

## Open

An inpaint route also needs a `mask_image`, which `generate_image` cannot give: such routes are not listed and
are refused by name. A mask is not in this decision.


The service's `input_fit` and error codes were live but not yet committed on its side when this was built.
