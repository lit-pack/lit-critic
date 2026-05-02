"""
Factory for creating LLM client instances by provider name.
"""

from .base import LLMClient


# Supported provider names (lowercase).
SUPPORTED_PROVIDERS = ("anthropic", "openai")


def create_client(provider: str, api_key: str) -> LLMClient:
    """Create an ``LLMClient`` for the given provider.

    Args:
        provider: One of ``"anthropic"`` or ``"openai"`` (case-insensitive).
        api_key:  The API key for the provider.

    Returns:
        A concrete ``LLMClient`` instance ready for use.

    Raises:
        ValueError: If the provider is not recognised.
        ImportError: If the provider's SDK package is not installed.
    """
    provider = provider.lower().strip()

    if provider == "anthropic":
        try:
            from .anthropic_client import AnthropicClient
        except ImportError as e:
            raise ImportError(
                "The 'anthropic' package is required for Anthropic models. "
                "Install it with: pip install anthropic"
            ) from e
        return AnthropicClient(api_key=api_key)

    if provider == "openai":
        try:
            from .openai_client import OpenAIClient
        except ImportError as e:
            raise ImportError(
                "The 'openai' package is required for OpenAI models. "
                "Install it with: pip install openai"
            ) from e
        return OpenAIClient(api_key=api_key)

    valid = ", ".join(SUPPORTED_PROVIDERS)
    raise ValueError(
        f"Unknown LLM provider '{provider}'. Supported providers: {valid}"
    )
