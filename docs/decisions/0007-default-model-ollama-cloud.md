# ADR-0007: Default model on Ollama Cloud (provisional)

**Status:** Accepted, provisional — revisit after real SEED workloads and once plan pricing is known.

**Context:** M2 uses Ollama Cloud. Stephen's candidates were `gemma4`, `gemma4:12b`
and `deepseek-v4.1-flash`. `/api/tags` shows the first two do not exist; `gemma4:31b`
does. A live tool-calling comparison (3 trials × 6 models, through SEED's adapter
and agent loop) is in `docs/model-strategy.md`.

**Options:** `gemma4:31b` (fast, 0/3 correct); `deepseek-v4.1-flash` (3/3);
`glm-5.3-flash` (3/3, fewest tokens); `gpt-oss:120b` (3/3); `gpt-oss:20b` (2/3);
`nemotron-3-nano:30b` (3/3, slowest, most tokens).

**Choice:** `SEED_DEFAULT_MODEL=deepseek-v4.1-flash`; fallbacks `glm-5.3-flash`,
then `gpt-oss:120b`.

**Reason:** reliable tool calls and correct results at ~3 s per run, and it was the
owner's candidate. `glm-5.3-flash` used fewer tokens but price is unpublished, so
token count alone does not decide.

**Consequences:** per-token pricing is unverified; `gemma4:31b` must not be used for
tasks with computation. Sample is small (one task, n=3).
