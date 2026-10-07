#!/usr/bin/env bash
# Starts Asuna in a container (ADR-019 §3.3). Deployment glue only: everything after it is the same launcher a
# Windows or Linux install runs, which installs the checkout when it changed and then starts DSH.
set -Eeuo pipefail

checkout="${ASUNA_CHECKOUT:-/srv/asuna}"
profile="${ASUNA_PROFILE:-asuna-demo}"
config="${ASUNA_CONFIG:-config/demo.local.json}"
port="${ASUNA_PORT:-8780}"
cd "$checkout"

# 1. The checkout: cloned once into the empty volume, then it is hers and the owner's (git pull, her publications).
if [[ ! -d .git ]]; then
  echo "Asuna: cloning ${ASUNA_REPO:-https://github.com/eamars/AsunaCognitionCore.git} into the checkout volume"
  git clone --branch "${ASUNA_REF:-main}" "${ASUNA_REPO:-https://github.com/eamars/AsunaCognitionCore.git}" .
fi
state=.runtime/container
mkdir -p "$state"

# 2. Node dependencies, again whenever the lockfile changes.
lock="$(sha256sum package-lock.json | cut -d' ' -f1)"
if [[ ! -d node_modules || "$(cat "$state/npm-lock" 2>/dev/null || true)" != "$lock" ]]; then
  echo "Asuna: installing Node dependencies"
  npm ci --no-audit --no-fund --foreground-scripts
  echo "$lock" > "$state/npm-lock"
fi

# 3. The checkout's Python environment (uv.lock), which runs the packer and the installer.
uv sync --frozen --quiet

# 4. LAN access as the owner's existing DSH container has it (ADR-019 §6.1 Q6): no login token.
node /opt/asuna/lan-login.mjs "$checkout"

# 5. The reviewed native rendering extension (tools/dsh-inline), built once from DSH's public release tag.
inline_current() {
  .venv/bin/python - <<'PY'
import hashlib, json, pathlib, sys
folder = pathlib.Path('.runtime/adr008/packages')
try:
    built = json.loads((folder / 'native-inline-manifest.json').read_text(encoding='utf-8'))
except (OSError, ValueError):
    sys.exit(1)
patch = hashlib.sha256(pathlib.Path('tools/dsh-inline/rc2-inline.patch').read_bytes()).hexdigest()
current = built and all(item['patchSha256'] == patch and pathlib.Path(item['path']).is_file()
                        and hashlib.sha256(pathlib.Path(item['path']).read_bytes()).hexdigest() == item['sha256']
                        for item in built)
sys.exit(0 if current else 1)
PY
}
if ! inline_current; then
  echo "Asuna: building the native rendering extension from DSH's release"
  source="$(mktemp -d)"
  git clone --quiet --depth 1 --branch dsh-v0.2.0-rc.2 https://github.com/deepseek-ai/deepseek-harness.git "$source/dsh"
  node tools/build_dsh_inline.mjs --source "$source/dsh"
  rm -rf "$source"
fi

# 6. The first install of this profile. Later starts install changes by themselves (the launcher's sync).
base=.runtime/adr008
[[ "$profile" == asuna-native ]] || base=".runtime/adr008/profiles/$profile"
if ! grep -q '"setup"' "$base/launch.json" 2>/dev/null; then
  if [[ ! -f "$config" && -n "${ASUNA_CONFIG_JSON:-}" ]]; then
    mkdir -p "$(dirname "$config")" && printf '%s' "$ASUNA_CONFIG_JSON" > "$config"
  fi
  # The demo profile (the default) needs only MongoDB's address. Its config is made the usual way
  # (tools/make_demo_config.py, its own database, no channels) from the tracked example, with every model route on a
  # closed local port: this stack never calls a model until a real config is given (AGENTS.md: synthetic inference).
  if [[ ! -f "$config" && "$profile" == asuna-demo && -n "${ASUNA_MONGO_URI:-}" ]]; then
    .venv/bin/python - "$state/demo-source.json" <<'PY'
import json, os, sys
value = json.load(open('config/local.example.json', encoding='utf-8'))
value['mongo_uri'] = os.environ['ASUNA_MONGO_URI']
for lane in ('character', 'executor', 'embedding'):
    value[lane]['base_url'] = 'http://127.0.0.1:9/v1'          # the discard port: nothing answers
json.dump(value, open(sys.argv[1], 'w', encoding='utf-8'), indent=2)
PY
    .venv/bin/python tools/make_demo_config.py --local "$state/demo-source.json" --out "$config"
  fi
  if [[ ! -f "$config" ]]; then
    echo "Asuna: $config is missing in the checkout volume; place it, or set ASUNA_CONFIG_JSON" \
         "(or ASUNA_MONGO_URI for the demo profile)" >&2
    exit 1
  fi
  persona="${ASUNA_PERSONA_PACKAGE:-tests/fixtures/personas/demo}"
  pack=(--persona "$persona")
  install=(--profile "$profile" --config "$config" --persona-package "$persona")
  for channel in ${ASUNA_CHANNEL_PACKAGES:-}; do
    pack+=(--channel "$channel")
    install+=(--channel-package "$channel")
  done
  [[ "${ASUNA_SHARED_ACTION_MODEL:-0}" == 1 ]] && install+=(--shared-action-model)
  .venv/bin/python tools/pack_plugins.py "${pack[@]}"
  .venv/bin/python tools/setup_native_profile.py "${install[@]}"
fi

exec ./start-asuna.sh --profile "$profile" --config "$config" --port "$port"
