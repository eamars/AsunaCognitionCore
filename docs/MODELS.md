# Choosing models for the two brains

Which model may run which brain, what has been tested, and how to test a new one.

**Agents, read in this order:**
- §1 before you set or change a route.
- §4 before a Claude model goes anywhere near the character brain.
- §5 to qualify a model.

## 1. Rules

1. Each brain has its own route, and the routes are set independently. Never infer a model from a brain's name, or
   a brain from a model's name.
2. **A Claude model that stops the think stage runs the character route only with `thoughts: thinking`** (§4,
   [RUNTIME_API.md](../RUNTIME_API.md) deployment settings). Probe a Claude model before it goes there (§5).
3. A Claude model may run the action brain's `actionHigh` route (§2, §4).
4. A route on a paid provider is the owner's choice. Applying route settings restarts the worker, so apply them when
   she is quiet.

## 2. The routes

Routes are set on the Asuna Cognition Core settings card (Plugins → Asuna Cognition Core). They pick from the
providers on DSH's Models page, where the keys live. `config/local.json` holds no routes.

| Route | What runs on it | Fields |
|---|---|---|
| `character` | every turn of hers, at home, in private chats and in groups; her relevance gate | `provider`, `model`, `reasoningEffort`, `maxTokens`, `attendEffort` (the gate), `groupEffort` (group turns) |
| `action` | delegated tasks: tools, web search, files, code | `provider`, `model`, `reasoningEffort`, `maxTokens`, `idleMinutes` |
| `actionHigh` | optional: the 高 tier of a delegated task | same fields as `action`; an empty provider means no 高 |

- An empty `reasoningEffort` field uses the model's default. A level the model does not offer is refused.
- A 高 request that ends in an error DSH's retries did not cure, a refusal included, is retried on `action`. The task
  then stays on `action`.

Full contract: [RUNTIME_API.md](../RUNTIME_API.md).

## 3. Models tested

| Model | Provider | Route | How it was tested | Result |
|---|---|---|---|---|
| `qwen38-next-uncensored-strata-vision` | the operator's local server, OpenAI-compatible, qwen thinking format | `character` and `action` | in daily use on both; refusal probe on the research and recall conversations only, at commit `6df200a9` | in use; probe: none stopped or declined. Missed moments not yet measured: that run offered no `speak` in its groups, so every moment that needs it missed by construction |
| `claude-sonnet-5-5`, effort medium | Anthropic | `character`, `thoughts: tool` | refusal probe, all seven conversations × 3 (51 turns), at commit `6df200a9` | **FAIL**: all 33 turns that reached the model were stopped on their first request, before any output, category `reasoning_extraction`; 18 turns got provider errors |
| `claude-haiku-5-5`, effort high | Anthropic | `character`, `thoughts: tool` | refusal probe, all eight conversations × 3 (57 turns), 2026-10-26 | FAIL on missed moments only: 0 stopped, 0 declined; 5 of 57 missed (home 4 of 6 used no `plan` or `delegate`; research 1 of 9 no `delegate`) |
| `claude-haiku-5-5`, effort high | Anthropic | `character`, `thoughts: thinking` | refusal probe, the same 57 turns, 2026-10-26 | FAIL on missed moments only: 0 stopped, 0 declined; 8 of 57 missed (home 4 of 6; research 4 of 9 spoke instead of delegating) |
| `claude-sonnet-5-5`, effort medium | Anthropic | `actionHigh` | in use for 高 tasks | runs; not probed (the probe covers the character brain only) |
| `deepseek-flash` | DeepSeek API | none | an offline experiment on choosing which line to quote | not refusal-probed |

A probe result holds for that model when it ran. Providers change models and their checks, so run the probe again
before relying on an old row.

## 4. Claude models: warnings

- **With `thoughts: tool` the character route goes silent on a model that stops the think stage.** Anthropic's
  safety system stops every character request (`stop_reason: "refusal"`, category `reasoning_extraction`) before the
  model writes anything, even in harmless small talk. DSH turns the stop into a failed turn, so she does not answer,
  in any conversation. Anthropic names Fable 5.1, Opus 5.5, Opus 5, Sonnet 5.5 and Fable 5 for this refusal; Haiku
  5.5 is not stopped (§3).
- **The stop answers to the request's design, not to what people say.** It comes on the first request of a turn,
  before `think` or any other tool runs.
- **It cannot be prompted around.** Rewording prompts, tool descriptions or the turn's steps to get past the check
  would work around a provider's safety system. `thoughts: thinking` is not a rewording: nothing then asks the model
  for its thoughts, and her 心里话 are the summary of its own thinking, which the API returns.
- **Sonnet 5.5 always thinks.** DSH's catalog gives it no "off" level, so every request uses adaptive thinking at the
  route's effort. The probe's `--effort` sends the same shape.
- **On `actionHigh`, a refusal falls back to the low tier.** A refused 高 request is retried on `action`, and the task
  records `fell: refused`. A refusal does not make 高 rest.
- **Claude routes are paid** on the owner's key, per token.

## 5. Testing a model

The refusal probe runs synthetic conversations through the real character-brain design. It sends only the model
call to the provider, keeps no model words, and prints PASS, FAIL or NO RESULT. Details are in
[tools/README.md](../tools/README.md#refusal-probe).

```bash
python tools/refusal_probe.py --dry-run
```

```bash
python tools/refusal_probe.py --provider anthropic --model <model id> --effort <level> --thoughts <tool|thinking>
```

```bash
python tools/refusal_probe.py --provider openai-compatible --base-url <url>/v1 --model <model id> --key-env <VAR>
```

- **The key**: an Anthropic key is read from `ANTHROPIC_API_KEY`. Any other provider's key is read from the variable
  named by `--key-env`. The key is never printed.
- **Effort**: pass the effort the route will use (`--effort`), and the same model id the route names.
- **PASS**: no turn was stopped or declined, and every moment got the tool it needs.
- **FAIL**: lists each reason and each step that missed.
- **NO RESULT**: a dry run, or turns that could not run (provider errors) with no failure. Run it again.
