# Model strategy — SEED OS

Status: design only (implementation in M2). Ratified by Directive v1.1.

- **One internal interface**, provider adapters behind it: Anthropic, OpenAI,
  DeepSeek, OpenRouter, OpenAI-compatible, local. Adapters declare capabilities
  (tool calling, structured output, streaming, context window, token accounting)
  rather than assuming parity; the runtime degrades explicitly when a capability
  is missing.
- **Routing by task class:** inexpensive models for routine steps; stronger
  models for planning, architecture, hard coding, security review, debugging, and
  independent verification. Rules are configurable and every routing decision is
  recorded as an execution event.
- **Budgets:** per-task and per-model token and spend limits; hard stop on
  exceed; usage persisted per call.
- **Fallback:** ordered per route on retryable provider errors, bounded retries.
- **Credentials:** stored server-side, never returned to the client, never put in
  model context or logs.
- **No runtime dependency** on Claude Code or Hermes Agent.

Defaults (which model for which class) are chosen in M2 against current provider
pricing and recorded as an ADR.

## M2 live model comparison (2026-10-28)

Run through SEED's own Ollama adapter and agent loop (not a separate script
client) against Ollama Cloud, using `spikes/model-bench/bench.py`. Task: read
`sales.csv` (5 rows), compute total revenue (units × price) and the top region,
write `report.txt`. Pass = the file exists with the correct total and region.
3 trials per model, 8-step limit, tools `list_files` / `read_file` / `write_file`.

`/api/tags` lists the models available to the key. **`gemma4` and `gemma4:12b`
do not exist** on Ollama Cloud; the closest is `gemma4:31b`.

| Model | Pass | Avg input tok | Avg output tok | Avg wall s |
|---|---|---|---|---|
| `gemma4:31b` | 0/3 | 1754 | 109 | 2.0 |
| `deepseek-v4.1-flash` | 3/3 | 2483 | 617 | 3.1 |
| `gpt-oss:20b` | 2/3 | 1301 | 282 | 3.2 |
| `nemotron-3-nano:30b` | 3/3 | 2836 | 988 | 6.7 |
| `gpt-oss:120b` | 3/3 | 1780 | 497 | 3.2 |
| `glm-5.3-flash` | 3/3 | 1581 | 389 | 3.6 |

Findings:
- Tool-call wire format worked for every model: no malformed calls, no tool
  errors. All failures were model behaviour.
- `gemma4:31b` calls tools correctly and is fastest, but computed the total wrong
  all 3 times (e.g. 426 instead of 541) — it does not reason before answering.
  Unsuitable for anything with arithmetic or planning.
- `gpt-oss:20b` once answered without calling any tool (no file written).
- Thinking models spend more output tokens (`nemotron-3-nano` ~1000 per run).

**Pricing: not verified.** Ollama Cloud's public API does not return per-token
prices, so cost is compared by tokens only. The owner should confirm plan limits.

**Recommendation (provisional):** default routine route to `deepseek-v4.1-flash`
(Stephen's candidate; reliable 3/3, tools + vision + thinking, ~3 s). Cheapest by
tokens among reliable models is `glm-5.3-flash` (~1.9k tokens/run), then
`gpt-oss:120b` (~2.3k); keep both as fallbacks. Not chosen: `gemma4:31b`
(wrong answers), `gpt-oss:20b` (skipped tool use), `nemotron-3-nano` (slowest,
most tokens).

Limits: 1 task, n=3, no latency percentiles, no long-context or multi-file
tasks. This does not justify a final ADR; revisit with real SEED workloads.
The run went through the adapter and agent loop directly, not the HTTP/SSE
endpoint or the UI.
