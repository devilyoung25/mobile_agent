"""System prompt — re-exported from the on-core package.

The engine prompt is brand-neutral; provider policy (e.g. Azure DevOps) is now
injected by the composition layer via ``construct_system_prompt(integration_policy=...)``
rather than hardcoded in the engine.
"""

from on_core.prompt import construct_system_prompt

__all__ = ["construct_system_prompt"]
