# ADR 0001 — Arquitectura de ON Mobile Agent

- **Estado:** Aceptada
- **Fecha:** 2026-06-14
- **Contexto del producto:** ON Mobile Agent es un fork de openSWE convertido en
  **plataforma agentic para equipos de ingeniería**. MVP para el **equipo de
  desarrollo móvil** (Azure DevOps, Android), con intención de escalar a otros
  equipos/tecnologías (p.ej. .NET) vía *domain-packs*.

Este ADR fija las decisiones de arquitectura para que el producto escale sin
reescrituras y sin que se filtren responsabilidades entre capas.

## Actualización 2026-06 — DeveloperProfile (supersede `domain/skill` formal)

> Esta sección **prevalece** sobre las menciones de *domain-packs*, *skills* formales,
> *SkillResolver* y *Skill como contrato* que aparecen más abajo (registro histórico).

La unidad operativa del MVP es el **`DeveloperProfile`** (`agent/composition/developer_profiles.py`):
describe el mundo operativo de un equipo/stack (proyectos/repos ADO, rama de integración, stack,
task kinds, reglas). La composición resuelve, por-run y en orden:
`resolve_developer_profile` → `resolve_task_kind` (TaskResolver) → `resolve_operating_context`
(ContextResolver) → `load_tools_for` (CapabilityGateway) → `construct_system_prompt` → engine.

Reglas vigentes:
- **NO hay un `SkillResolver` formal** ni "Skill como contrato". No se reintroduce.
- **`domain_pack`** queda como **id interno de capability-pack** (compat con el CapabilityGateway),
  no como "domain-pack" versionado con skills/evidencia/evals.
- **Android Skills MCP / Knowledge MCP = context providers read-only** (aportan contexto técnico/
  de negocio vía el `ContextProvider` seam del ContextResolver). **No autorizan nada.**
- **El CapabilityGateway es quien autoriza tools.** Entra es la autoridad de identidad/scope; el
  profile **acota** dentro de lo que el actor ya puede ver y **agrega contexto**, nunca concede.

## Capas (responsabilidades, sin mezclar)

1. **apps/dashboard** — UI. Habla con platform. No razona ni ejecuta tools.
2. **platform-runtime** (`platform/dashboard_api`) — backend: auth, sesiones,
   settings, auditoría, persistencia operativa. **No es un segundo agente**: no
   complementa respuestas del modelo fuera del loop (sí consulta para admin/config).
3. **agent-composition** (hoy `agent/server.py`, debe quedar **delgada**) — arma el
   agente por-run: actor, workspace, modelo, prompt, skills, tools MCP, policy,
   approvals, domain-pack.
4. **engine-core** (`engine/agent-engine-core/on_core`) — loop agentic **neutral**.
   Recibe modelos/tools/prompt/backend ya resueltos. **No conoce** proveedores,
   Azure, Entra, Android ni MCPs concretos. (Garantizado por
   `tests/test_engine_neutrality.py`.)
5. **model-gateway** — única fuente de verdad de modelos y capacidades.
6. **capability-gateway** (`packages/capability-gateway`) — gobierna tools: registro de
   capabilities, validación, inyección de credenciales por-actor, allow/deny,
   provenance/audit y dispatch. MCP es un adapter del gateway, no la abstracción raíz.
7. **MCP/REST/SDK servers** — las "manos": ADO, Android Knowledge, Business
   Knowledge, Mobile QA Runner. Aislados cuando ejecuten fuera del proceso.
8. **domain-packs** — especialización por equipo (mobile-pack; futuro dotnet-pack):
   manifiesto versionado de MCPs requeridos, skills, policies, evidencia, evals,
   defaults.

**Capability vs Skill:** Capability = capacidad / fuente viva de contexto ("qué
puede hacer o consultar"), implementable vía MCP, REST, SDK u otro adapter. Skill
= procedimiento experto = **contrato estable** (objetivo,
triggers, pasos mínimos, evidencia requerida, tools permitidas, criterios de éxito,
antipatrón) + conocimiento **dinámico** vía Knowledge MCP/RAG (no markdown gigante).

## Decisiones

### D1 — Deployment-agnóstico, multi-USER, multi-TENANT diferido
Se ejecuta vía Docker. El destino (laptop de cada dev **o** box interno con IP
privada) **queda abierto**: el mismo artefacto sirve ambos, con ~0 costo de cambio.
- **Multi-USER soportado por diseño** vía actor Entra (token/credencial/scope
  por-actor; workspaces y checkpoints por-thread). Funciona igual con 1 usuario local
  o varios contra un box interno.
- **Multi-TENANT (orgs aisladas) diferido** — no se construye maquinaria de tenant.
- `domain_pack` es first-class (mobile ahora, dotnet luego). No se añade `tenant_id`.
- **Trade-off:** el camino "box interno" exige auth en cada request (sin confiar en
  localhost), no exponer el runtime langgraph directo, y validar concurrencia (varios
  runs en un proceso) — soportado por el modelo por-thread, no probado bajo carga.

### D2 — Topología: monolito modular en docker-compose
`app` (control + agentic juntos, **frontera interna limpia**, splitteable a 2
servicios cuando se vaya a web) + contenedor `model-gateway` + un contenedor por MCP
aislado + volumen de checkpoints. **Mobile QA Runner corre en el HOST** (gradle/adb/
emulador no van en Docker). Bind `0.0.0.0` + auth Entra; langgraph no expuesto en la
IP, solo el API autenticado.
- **Alternativa descartada (por ahora):** microservicios desde el inicio → demasiado
  ops/latencia para un equipo chico y un solo dominio. Las **fronteras como
  interfaces** (no como red) hacen barata la migración futura a web/servicios.
- Nota: el `docker-compose` (cómo el **dev** corre el producto) es distinto del
  **devcontainer** (sandbox donde el **agente** ejecuta código del repo).

### D3 — Capability Gateway + credenciales por-actor
Las capabilities corren fuera del engine y pueden estar respaldadas por MCP, REST,
SDK u otro adapter. Las credenciales (PAT/bearer) se **mintean por-actor
server-side** y **nunca** llegan al LLM ni al workspace; el engine solo recibe
tools resueltas. Patrón de referencia ya existente:
`load_azure_devops_tools_for_actor` + `get_azure_devops_access_token` (Entra→ADO).
- **Por qué:** es el constraint de seguridad #1 del proyecto (tokens nunca expuestos).

### D4 — Model Gateway como única fuente de verdad de capacidades
El gateway expone catálogo + capacidades por modelo **extendiendo `GET /v1/models`**
(campos extra: `max_input_tokens`, `max_output_tokens`, `supports_images`, `efforts`,
`default_effort`, `label`; clientes OpenAI estándar los ignoran). El agente los
consume para: compactación (profile→ventana real), `reasoning_effort`, output cap,
soporte de imágenes y catálogo de UI. El `registry` del agente es **proyección del
snapshot**; los env son **fallback/bootstrap**.
- **Por qué:** el agente usaba IDs lógicos (`on-auto-coder`) que ocultan las
  capacidades reales → compactaba tarde (probado: `profile is None` → fallback fijo
  170k), mandaba efforts inválidos, max_tokens fijo y duplicaba catálogo.
- Para modelos "auto"/lógicos, las capacidades deben ser **garantías mínimas
  conservadoras**, no optimistas.
- **Fail-soft:** sin gateway o sin campos extra, opera con fallback de env. IO solo
  async; `snapshot()` nunca bloquea (evita el guard de blockbuster).

### D5 — Business Knowledge MCP (first-party, scope por acceso)
Un MCP de conocimiento de **producto/negocio/reglas** (distinto del Android
Knowledge, que es técnico), **scopeado por los proyectos de Azure DevOps a los que
el actor tiene acceso** (`list_projects(actor_id)`, ya existe). El filtro de acceso
es **server-side real** aunque el contenido esté curado a mano: nunca servir
contenido de un proyecto fuera del scope (sería fuga de datos). Tech-independent →
reutilizable por packs futuros. Contenido: contrato estable, backing curado→RAG.

## Consecuencias

- El engine queda neutral y verificado mecánicamente; añadir un proveedor/dominio
  no toca el engine.
- Cambiar capacidades en el gateway actualiza UI, selección, compactación, efforts y
  límites sin duplicar config.
- La composición (`agent/server.py`) debe adelgazarse: hoy mezcla composición +
  runtime + policy de producto.
- La neutralidad del engine queda protegida por `tests/test_engine_neutrality.py`
  con `KNOWN_LEAKS = {}`.

## Diferido (cuando/si va a web)
Separación física control/agentic, audit spine único de compliance, maquinaria
multi-tenant, escalado horizontal. Habilitado por las fronteras de D2, no construido
ahora.

## Reparto de trabajo (dos agentes)
- **Carril A — Engine & Models:** gateway (D4), neutralidad del engine, adelgazar
  composición, docker-compose, resolución de scope.
- **Carril B — Tools & Domain:** capability-gateway (D3), domain-pack + mobile-pack,
  Business/Android Knowledge MCP (D5), cablear ADO por el gateway.
- **Seam:** `load_tools_for(actor_id, *, domain_pack, project_scope) -> list[BaseTool]`
  (B implementa; A lo cablea en `get_agent`). B no edita `agent/server.py`.
