"""
OpenAI implementation of the LLM client interface.

Wraps the ``openai.AsyncOpenAI`` SDK, translating between the
provider-agnostic ``LLMClient`` interface and OpenAI's chat completions API.

Handles the differences between Anthropic and OpenAI formats:
- System prompt: Anthropic uses a separate ``system`` parameter;
  OpenAI uses a ``{"role": "system", ...}`` message.
- Tool schema: Anthropic uses ``input_schema``; OpenAI uses
  ``{"type": "function", "function": {"parameters": ...}}``.
- Streaming: Anthropic yields text via ``stream.text_stream``;
  OpenAI yields ``ChatCompletionChunk`` objects with delta content.
"""

import json
import logging
from typing import AsyncIterator, Optional

from openai import AsyncOpenAI

from .base import LLMClient, LLMResponse, LLMToolResponse

logger = logging.getLogger(__name__)


def _anthropic_tool_to_openai(tool_schema: dict) -> dict:
    """Convert an Anthropic-format tool definition to OpenAI function-calling format.

    Anthropic format::

        {
            "name": "report_findings",
            "description": "...",
            "input_schema": { ... }
        }

    OpenAI format::

        {
            "type": "function",
            "function": {
                "name": "report_findings",
                "description": "...",
                "parameters": { ... }
            }
        }
    """
    return {
        "type": "function",
        "function": {
            "name": tool_schema["name"],
            "description": tool_schema.get("description", ""),
            "parameters": tool_schema.get("input_schema", {}),
        },
    }


def _build_openai_messages(
    messages: list[dict], system: Optional[str] = None
) -> list[dict]:
    """Prepend a system message if ``system`` is provided.

    OpenAI expects the system prompt as the first message with
    ``"role": "system"``, whereas Anthropic uses a separate parameter.
    """
    result: list[dict] = []
    if system:
        result.append({"role": "system", "content": system})
    result.extend(messages)
    return result


class OpenAIClient(LLMClient):
    """LLMClient backed by the OpenAI chat completions API."""

    def __init__(self, api_key: str):
        self._client = AsyncOpenAI(api_key=api_key, max_retries=1)

    async def aclose(self) -> None:
        """Close the underlying httpx transport."""
        await self._client.close()

    async def check_connectivity(self) -> bool:
        """Probe OpenAI reachability via a cheap models.list call (3s timeout)."""
        try:
            await self._client.models.list(timeout=3.0)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Plain text completion
    # ------------------------------------------------------------------

    async def create_message(
        self,
        model: str,
        max_tokens: int,
        messages: list[dict],
        system: Optional[str] = None,
    ) -> LLMResponse:
        oai_messages = _build_openai_messages(messages, system)

        response = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=oai_messages,
        )

        choice = response.choices[0]
        text = choice.message.content or ""
        truncated = choice.finish_reason == "length"

        return LLMResponse(text=text, truncated=truncated)

    # ------------------------------------------------------------------
    # Structured output via function calling
    # ------------------------------------------------------------------

    async def create_message_with_tool(
        self,
        model: str,
        max_tokens: int,
        messages: list[dict],
        tool_schema: dict,
        tool_name: str,
        system: Optional[str] = None,
    ) -> LLMToolResponse:
        """Call the OpenAI API with forced function calling.

        Translates the Anthropic-format ``tool_schema`` to OpenAI's
        function-calling format and forces the model to call the named
        function via ``tool_choice``.
        """
        oai_messages = _build_openai_messages(messages, system)
        oai_tool = _anthropic_tool_to_openai(tool_schema)

        response = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=oai_messages,
            tools=[oai_tool],
            tool_choice={"type": "function", "function": {"name": tool_name}},
        )

        choice = response.choices[0]
        truncated = choice.finish_reason == "length"

        # Extract function call arguments
        tool_input: dict = {}
        raw_text = choice.message.content or ""

        if choice.message.tool_calls:
            tool_call = choice.message.tool_calls[0]
            try:
                tool_input = json.loads(tool_call.function.arguments)
            except (json.JSONDecodeError, AttributeError) as e:
                logger.warning("Failed to parse OpenAI tool call arguments: %s", e)
                raw_text += f"\n[Parse error: {e}]"

        return LLMToolResponse(
            tool_input=tool_input,
            truncated=truncated,
            raw_text=raw_text,
        )

    # ------------------------------------------------------------------
    # Streaming text completion
    # ------------------------------------------------------------------

    async def stream_message(
        self,
        model: str,
        max_tokens: int,
        messages: list[dict],
        system: Optional[str] = None,
    ) -> AsyncIterator[str | LLMResponse]:
        oai_messages = _build_openai_messages(messages, system)

        stream = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=oai_messages,
            stream=True,
        )

        full_text_parts: list[str] = []
        truncated = False

        async for chunk in stream:
            choice = chunk.choices[0] if chunk.choices else None
            if choice is None:
                continue

            delta = choice.delta
            if delta and delta.content:
                full_text_parts.append(delta.content)
                yield delta.content

            if choice.finish_reason == "length":
                truncated = True

        full_text = "".join(full_text_parts)
        yield LLMResponse(text=full_text, truncated=truncated)
