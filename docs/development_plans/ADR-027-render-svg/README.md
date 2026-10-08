# ADR-027: render_svg — an SVG she writes becomes a picture she can see and send

Status: **Accepted and built** 2026-10-08. The owner's question; the owner chose the renderer and the scope.

## 1. Context

On 2026-10-08 the owner set her the usual agent test in a QQ group: draw a pelican riding a bicycle as SVG, then show
it. Her action brain wrote a 5.5 KB SVG and stopped at rendering:

- In a group the action brain has no `sandbox_run` (owner scenes only, 2026-10-06), so no code at all.
- Where she can run Python (3.12 with httpx, websockets, pymongo, PyYAML, Pillow), nothing reads SVG: not the
  standard library, not Pillow. A hand-written rasterizer on Pillow could draw simple shapes but not text,
  gradients or transforms.
- `read_image` takes a message attachment or a stored picture's `artifact_id`, not a file in the task folder, and a
  `data:` URI is refused by `read_image` and `web_fetch`. So even a PNG she made could not be looked at or sent.

She reported the gap honestly and wrote it in her idea notebook (a rasterizing tool, or a way to register a task file
as a picture).

## 2. Decisions (owner, 2026-10-08)

- **D1 — A program-side render_svg tool**, rendering with resvg through `@resvg/resvg-js` on the Host (the same Rust
  engine as the Python `resvg` wheel, widely used, prebuilt for Windows and Linux), rather than the small Python
  binding or no tool.
- **D2 — Every conversation.** Like `generate_image`: it runs none of her code, reads only her task folder and makes
  no network request, so the group test can pass.
- **D3 — It works in the Docker deployment too.** The image gets fonts (the slim base has none, and text would
  render blank): DejaVu, and Noto CJK for Chinese and Japanese.

## 3. Safety

Measured with resvg-js 2.6.2: an `<image>` whose `href` is an absolute path on the Host is loaded and drawn (with or
without `resourcesDir`); `file:` URLs, relative paths and `http(s)` links are not. In a group, an SVG asked for by
anyone could otherwise turn a picture on the Host into one she sends. So the worker parses the SVG (Python's XML
parser) and removes the link of every `<image>` and `<feImage>` that is not an embedded `data:` picture, says how many
it removed, and refuses an SVG that declares XML entities. resvg reads system fonts only. Rendering runs in a worker
thread, stopped after 20 s, refused above 2048×4096 pixels; the SVG is at most 2 MiB.

## 4. As built

`src/asuna/svg_render.py` (`RENDER_SVG_TOOL`, `safe_svg`, `render`; the Host renderer attached by `native_worker` as
the `render_svg` Host request); `packages/cognition-core/src/svg.js` and `svg-worker.js` (`renderSvg`); granted in
`coordinator._grants` when the Host renderer is attached; dispatched in `tasks.py` without the effects lock, with a
line in the task brief. The PNG goes to a new file under `images/` and is registered through
`outbound_media.import_register` with source `integration:svg:<path>`, so it counts as her own picture.
`deploy/docker/Dockerfile` installs `fonts-dejavu-core` and `fonts-noto-cjk`. Tests: `tests/test_svg_render.py`,
`packages/cognition-core/test/svg.test.js`. Current reference: [RUNTIME_API.md](../../../RUNTIME_API.md).
