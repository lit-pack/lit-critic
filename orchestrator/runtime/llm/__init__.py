"""
LLM abstraction layer for the lit-critic system.

Provides a provider-agnostic interface for text generation, tool use,
and streaming, with concrete implementations for Anthropic and OpenAI.
"""

from .base import LLMClient, LLMResponse, LLMToolResponse
from .factory import create_client

__all__ = [
    "LLMClient",
    "LLMResponse",
    "LLMToolResponse",
    "create_client",
]
