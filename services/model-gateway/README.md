# ON Model Gateway

OpenAI-compatible, **multi-provider** facade that the AgentEngine talks to as its
single logical model endpoint. It owns the **capability catalog** and **proxies**
chat completions to the right provider (Ollama Cloud, OpenRouter, …). Provider
keys live only here. Decoupled: the engine reaches it over HTTP via
`MODEL_GATEWAY_BASE_URL`; it is not a workspace package and is never imported.

## Endpoints
- `GET /health`
- `GET /v1/models` — flat catalog; each model tagged with `provider` + `available`
- `GET /v1/providers` — models grouped by provider (for the UI's provider tabs)
- `POST /v1/chat/completions` — routes to the model's provider (streaming + not)

## Availability (reactive)
A model that returns a 4xx/5xx upstream (e.g. OpenRouter free **429 rate-limit**,
or an Ollama **403 "requires subscription"**) is marked **unavailable** for a
cooldown (honoring `Retry-After`) and reported `available:false` so the UI greys
it out. It auto-recovers when the window passes or a later request succeeds.

## Providers & discovery
A provider with no key is skipped. Keys live in this folder's `.env` (see
`.env.example`).
- **Ollama** — `GATEWAY_OLLAMA_DISCOVERY=auto` (default) lists the full cloud
  catalog; `curated` exposes only `OLLAMA_MODELS` / `GATEWAY_OLLAMA_MODELS` (what
  your account can actually run — the full catalog includes subscription-locked
  models that 403 and then grey out).
- **OpenRouter** — static list `GATEWAY_OPENROUTER_MODELS` (default `openrouter/free`,
  the auto-rotating free meta-model).

## Run (dev)
```bash
cd services/model-gateway
cp .env.example .env   # fill OLLAMA_API_KEY / OPENROUTER_API_KEY
uv run uvicorn model_gateway.app:app --port 4001
```
Then point the engine at it: `MODEL_GATEWAY_BASE_URL=http://localhost:4001/v1`.

## Test
```bash
cd services/model-gateway && uv run pytest -q
```
