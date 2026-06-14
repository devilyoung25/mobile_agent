"""Model launcher public API.

Only logical ON Model Gateway models are exported here. The gateway, not this
repo, owns concrete providers such as Ollama, OpenRouter, Anthropic, or OpenAI.
"""

from .client import ModelLauncherClient, ModelLaunchPlan, create_model_plan
from .gateway_metadata import (
    GatewayModel,
)
from .gateway_metadata import (
    get_models as get_gateway_models,
)
from .gateway_metadata import (
    snapshot as gateway_models_snapshot,
)
from .kwargs import (
    DEFAULT_GATEWAY_EFFORT,
    DEFAULT_GATEWAY_MAX_TOKENS,
    DEFAULT_GATEWAY_MODEL,
    ModelKwargs,
    gateway_api_key,
    gateway_base_url,
    gateway_max_tokens,
    gateway_temperature,
    make_model,
)
from .registry import (
    ModelOption,
    default_effort_for_model,
    default_model_id,
    default_model_pair,
    default_subagent_model_pair,
    model_supports_effort,
    model_supports_images,
    provider_fallback_pair,
    supported_model_ids,
    supported_models,
)

__all__ = [
    "DEFAULT_GATEWAY_EFFORT",
    "DEFAULT_GATEWAY_MAX_TOKENS",
    "DEFAULT_GATEWAY_MODEL",
    "GatewayModel",
    "ModelKwargs",
    "ModelLaunchPlan",
    "ModelLauncherClient",
    "ModelOption",
    "create_model_plan",
    "gateway_models_snapshot",
    "get_gateway_models",
    "default_effort_for_model",
    "default_model_id",
    "default_model_pair",
    "default_subagent_model_pair",
    "gateway_api_key",
    "gateway_base_url",
    "gateway_max_tokens",
    "gateway_temperature",
    "make_model",
    "model_supports_effort",
    "model_supports_images",
    "provider_fallback_pair",
    "supported_model_ids",
    "supported_models",
]
