# @asuna/demo

Synthetic persona package for tests and the demo Web environment (ADR-009 §0.3).
It contains placeholder text only. Build and install it into the isolated
`asuna-demo` profile:

```bash
python tools/make_demo_config.py
python tools/pack_plugins.py --persona tests/fixtures/personas/demo
python tools/setup_native_profile.py --profile asuna-demo --config config/demo.local.json --persona-package tests/fixtures/personas/demo
start-asuna.cmd --profile asuna-demo --config config/demo.local.json
```
