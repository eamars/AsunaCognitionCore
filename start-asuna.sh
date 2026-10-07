#!/bin/sh
# Starts the native Web host on Linux or macOS: the same entry as start-asuna.cmd on Windows (tools/asuna-launch.mjs).
cd "$(dirname "$0")" || exit 1
exec node tools/asuna-launch.mjs ui "$@"
