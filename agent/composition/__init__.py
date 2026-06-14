"""Agent composition helpers.

These modules hold the per-run resolution logic (prompt context, tool/observability
loading, approval policy) extracted from ``agent/server.py`` so ``get_agent`` reads
as a thin orchestrator. Behaviour is unchanged; ``server.py`` re-imports the public
names so existing call sites and test patch targets keep working.
"""
