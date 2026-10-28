# ADR-0006 — Provider interface, Ollama first, bounded streaming agent loop

**Status:** Accepted (2026-10-28)

**Context:** M2 needs real model + tool execution. The owner chose Ollama Cloud
(temporary key) as the first provider, picking among gemma4 / deepseek-v4.1-flash /
gemma4:12b by measured economy. The directive requires provider-agnosticism,
explicit termination, bounded retries, and no model-generated shell in the API
process.

**Decision**
- `seed_api.core.providers.base.Provider` (complete / stream / list_models) with a
  classified `ProviderError` (auth, rate_limited, unavailable, bad_request,
  bad_response, timeout; the middle three-ish are retryable). Adapters translate
  to provider-neutral `Message`/`ChatResult`/`StreamEvent` types.
- First adapter: Ollama native `/api/chat` (NDJSON streaming, function tools,
  token counts from `prompt_eval_count`/`eval_count`). Base URL configurable, so
  the same adapter serves self-hosted Ollama.
- `run_agent` loop with `RunLimits` (steps, wall time, total tokens, tool calls per
  step, output tokens per step, provider retries). Terminations: completed,
  max_steps, deadline, token_budget, provider_error, cancelled. Ordered,
  sequence-numbered events for SSE now and persistence later.
- Typed `ToolRegistry`: Pydantic input/output models, permission tag, timeout,
  output cap; failures come back to the model as typed errors. Tools marked
  `requires_approval` are refused until approvals exist (M4).
- First tools are file list/read/write confined to a per-run workspace (path and
  symlink escape blocked). No shell/exec tool until the sandbox (M3).

**Consequences:** Runs are in-request (closing the stream cancels; nothing is
persisted) until SEED Flow (M3). Model choice is configuration
(`SEED_DEFAULT_MODEL`), decided by the benchmark, not code.
