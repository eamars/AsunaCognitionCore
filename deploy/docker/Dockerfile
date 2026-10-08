# Asuna in a container (ADR-019 §3.3): the toolchain only. The checkout lives on a volume (owner 2026-10-07), so
# her publications and the data folder (.runtime) persist; the entrypoint installs and starts what the checkout holds,
# through the same launcher a Windows or Linux install uses. Nothing in the core or its plugins knows about Docker.
FROM node:24-trixie-slim

# A compiler for the native modules npm builds (node-pty), git for the checkout and the DSH release the rendering
# extension is built from, python3 for node-gyp, tzdata so TZ gives the host's local time (default quiet hours
# follow it, as on any install), and fonts for text in a rendered SVG (render_svg reads the system fonts; Noto CJK
# for Chinese and Japanese, DejaVu for the rest).
RUN apt-get update \
 && apt-get install --yes --no-install-recommends bash build-essential ca-certificates curl git procps python3 tzdata \
    fonts-dejavu-core fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*

# uv builds the checkout's Python environment and the worker's (the same version the checkout is tested with).
COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /uvx /usr/local/bin/

# pnpm comes from corepack: DSH installs plugins with it, and the rendering extension builds with it.
RUN corepack enable

RUN groupadd --gid 10001 asuna \
 && useradd --uid 10001 --gid 10001 --create-home asuna \
 && mkdir --parents /srv/asuna /opt/asuna \
 && chown asuna:asuna /srv/asuna

# Python and uv's cache live on the checkout volume, so a recreated container keeps working environments.
ENV ASUNA_CHECKOUT=/srv/asuna \
    UV_PYTHON_INSTALL_DIR=/srv/asuna/.runtime/container/python \
    UV_CACHE_DIR=/srv/asuna/.runtime/container/uv-cache \
    UV_LINK_MODE=copy \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    PYTHONUTF8=1

COPY entrypoint.sh lan-login.mjs /opt/asuna/

USER asuna
WORKDIR /srv/asuna
EXPOSE 8780
ENTRYPOINT ["bash", "/opt/asuna/entrypoint.sh"]
