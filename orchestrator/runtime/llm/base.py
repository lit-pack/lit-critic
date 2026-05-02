"""
Abstract base class and response types for the LLM abstraction layer.

All provider-specific clients must implement the ``LLMClient`` interface.
The response dataclasses provide a uniform structure regardless of provider.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional


@dataclass
class LLMResponse:
    """Response from a plain text LLM call."""

    text: str
    truncated: bool = False


@dataclass
class LLMToolResponse:
    """Response from an LLM call that forces tool/function use.

    Attributes:
        tool_input: Parsed dict from the tool call arguments.
        truncated:  True if the response was cut short by the token limit.
        raw_text:   Any non-tool text content (useful for diagnostics when
                    the model emits reasoning alongside the tool call).
    """

    tool_input: dict = field(default_factory=dict)
    truncated: bool = False
    raw_text: str = ""


class LLMClient(ABC):
    """Provider-agnostic async LLM client.

    Every concrete implementation (Anthropic, OpenAI, …) must provide
    three capabilities:

    1. **create_message** send messages, get text back.
    2. **create_message_with_tool** send messages with a forced tool/function
       call, get a structured dict back.
    3. **stream_message** async generator that yields text chunks as they
       arrive, suitable for token-by-token display.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close the underlying HTTP client and release connection resources.

        Subclasses should override this to call their SDK's own close method.
        The default implementation is a no-op so that existing code that does
        not call aclose() continues to work without modification.
        """

    # ------------------------------------------------------------------
    # Connectivity probe
    # ------------------------------------------------------------------

    async def check_connectivity(self) -> bool:
        """Return True if the provider API is reachable, False otherwise.

        Makes a lightweight API call (e.g. models.list) with a short timeout.
        Subclasses should override this with a provider-specific probe.
        The default implementation always returns True so that test doubles and
        mock clients do not need to implement the method.
        """
        return True

    # ------------------------------------------------------------------
    # Plain text completion
    # ------------------------------------------------------------------

    @abstractmethod
    async def create_message(
        self,
        model: str,
        max_tokens: int,
        messages: list[dict],
        system: Optional[str] = None,
    ) -> LLMResponse:
        """Send a list of messages and return the assistant's text reply.

        Args:
            model:      Provider-specific model identifier (e.g. ``"claude-sonnet-4-5-20250929"``).
            max_tokens: Maximum tokens to generate.
            messages:   Conversation turns — ``[{"role": "user"|"assistant", "content": "..."}]``.
            system:     Optional system prompt (separate from the messages list).

        Returns:
            An ``LLMResponse`` with the assistant's text and a truncation flag.
        """

    # ------------------------------------------------------------------
    # Structured output via tool / function calling
    # ------------------------------------------------------------------

    @abstractmethod
    async def create_message_with_tool(
        self,
        model: str,
        max_tokens: int,
        messages: list[dict],
        tool_schema: dict,
        tool_name: str,
        system: Optional[str] = None,
    ) -> LLMToolResponse:
        """Send messages and force the model to call a specific tool/function.

        The ``tool_schema`` is in **Anthropic format** (the canonical format
        used throughout the codebase)::

            {
                "name": "report_findings",
                "description": "...",
                "input_schema": { ... JSON Schema ... }
            }

        Each provider implementation is responsible for translating this to
        its native format (e.g. OpenAI function-calling format).

        Args:
            model:        Provider-specific model identifier.
            max_tokens:   Maximum tokens to generate.
            messages:     Conversation turns.
            tool_schema:  Tool definition in Anthropic format.
            tool_name:    Name of the tool the model must call.
            system:       Optional system prompt.

        Returns:
            An ``LLMToolResponse`` with the parsed tool input dict.
        """

    # ------------------------------------------------------------------
    # Streaming text completion
    # ------------------------------------------------------------------

    @abstractmethod
    async def stream_message(
        self,
        model: str,
        max_tokens: int,
        messages: list[dict],
        system: Optional[str] = None,
    ) -> AsyncIterator[str | LLMResponse]:
        """Stream assistant text token-by-token.

        This is an async generator that yields:
            - ``str`` a text chunk as it arrives from the API.
            - ``LLMResponse`` a single final item with the full text and
              truncation flag, emitted after all text chunks.

        Usage::

            async for item in client.stream_message(...):
                if isinstance(item, str):
                    print(item, end="", flush=True)
                elif isinstance(item, LLMResponse):
                    # Final response object
                    full_text = item.text

        Args:
            model:      Provider-specific model identifier.
            max_tokens: Maximum tokens to generate.
            messages:   Conversation turns.
            system:     Optional system prompt.
        """
        # The yield below is never reached; it exists solely to tell Python
        # that this abstract method defines an async generator signature.
        yield  # type: ignore[misc]
