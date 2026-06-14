# ON Model Gateway

OpenSWE / ON Mobile Agent does not route model providers directly. It talks to
one OpenAI-compatible endpoint owned by the external **ON Model Gateway**.

That gateway is responsible for:

- choosing the best Ollama model available;
- downgrading within Ollama when needed;
- falling back to OpenRouter for retryable provider failures;
- preserving streaming, tool calls, tool choice, and OpenAI-compatible errors.

## Required endpoints

The external gateway must expose:

```text
GET  /health
GET  /v1/models
POST /v1/chat/completions
```

`/v1/chat/completions` must support streaming and tool calls because
DeepAgents/LangChain rely on both.

## Model capability discovery (single source of truth)

The gateway is the **only** source of truth for per-model capabilities. It
exposes them by extending the standard OpenAI `GET /v1/models` objects with extra
fields (standard OpenAI clients ignore the extras):

```json
{ "object": "list", "data": [
  { "id": "on-auto-coder", "object": "model", "owned_by": "on-model-gateway",
    "label": "ON Auto Coder",
    "max_input_tokens": 200000,
    "max_output_tokens": 64000,
    "supports_images": false,
    "efforts": ["medium", "high"],
    "default_effort": "medium" }
] }
```

The agent derives all of the following from this metadata — nothing is hardcoded
or duplicated:

| Field              | Drives in the agent                                              |
| ------------------ | --------------------------------------------------------------- |
| `max_input_tokens` | Context window → summarization/compaction trigger (85% of it)   |
| `max_output_tokens`| Output token cap (`max_tokens` per request)                     |
| `supports_images`  | Whether image input is accepted (dashboard + request building)  |
| `efforts`          | Allowed reasoning efforts; the agent sends `reasoning_effort`    |
| `default_effort`   | Default reasoning effort                                         |
| `label`            | Dashboard model selector label                                  |

Contract notes:

- For `auto`/logical models that route to several real backends, return the
  **minimum guaranteed** `max_input_tokens` so compaction stays conservative.
- Missing fields are tolerated: the agent falls back to env (below) or safe
  defaults, so the system keeps working while the gateway is being built.
- Capabilities are cached in-process with a short TTL
  (`MODEL_GATEWAY_METADATA_TTL`, default 120s); the catalog and model
  construction both read the same snapshot.

## OpenSWE env

Add this to `.env`:

```env
MODEL_GATEWAY_BASE_URL=http://localhost:4000/v1
MODEL_GATEWAY_API_KEY=
# Selection: which logical models the agent uses by default.
MODEL_GATEWAY_MODEL=on-auto-coder
MODEL_GATEWAY_SUBAGENT_MODEL=on-auto-coder
MODEL_GATEWAY_TEMPERATURE=0
# How often capabilities are re-discovered from the gateway (seconds).
MODEL_GATEWAY_METADATA_TTL=120
```

The vars below are **fallbacks only** — used when the gateway is unreachable or
has not yet implemented the extended `/v1/models` fields. When the gateway
provides a field, it wins. Normally leave them empty.

```env
MODEL_GATEWAY_MAX_TOKENS=64000           # output cap fallback
MODEL_GATEWAY_MAX_INPUT_TOKENS=          # context-window fallback (keeps compaction calibrated)
MODEL_GATEWAY_MAX_OUTPUT_TOKENS=
MODEL_GATEWAY_MODELS=                     # catalog fallback
MODEL_GATEWAY_MODEL_LABELS=on-auto-coder=on-auto-coder
MODEL_GATEWAY_EFFORTS=medium
MODEL_GATEWAY_DEFAULT_EFFORT=medium
MODEL_GATEWAY_IMAGE_MODELS=
```

## Dev flow

1. Start the external ON Model Gateway repo.
2. Confirm health:

   ```bash
   curl -fsS http://localhost:4000/health
   ```

3. Start ON Mobile Agent:

   ```bash
   make dev-all
   ```

`make dev-all` fails fast if `MODEL_GATEWAY_BASE_URL` is missing or if
`/health` does not respond. It no longer starts Ollama.

## What not to configure here

Do not configure provider routing in this repo:

- no `OLLAMA_*`;
- no `OPENROUTER_*`;
- no `MODEL_ROUTER_CHAIN`;
- no provider model ids in the dashboard selector.

Those belong to ON Model Gateway.
