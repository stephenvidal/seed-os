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
