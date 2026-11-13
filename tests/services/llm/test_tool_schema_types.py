"""A provider that cannot type a union parameter must get a flattened schema.

The Xiaomi MiMo endpoint closes a streamed tool call's arguments at the first
union-typed property, so the model's own value for that parameter never
arrives. The tool's own schema keeps the union — DeepTutor's argument guard
reads it to tell "absent" from "explicitly null" — so the flattening belongs
on the wire copy only.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.llm.capabilities import supports_nullable_tool_params
from deeptutor.services.llm.provider_core.tool_schema_types import (
    flatten_tool_schema_types,
)

_UNION_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "rag",
            "description": "Retrieve passages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "q"},
                    "source_path": {"type": ["string", "null"], "description": "p"},
                    "page": {"type": ["integer", "null"], "description": "n"},
                    "region": {"type": ["array", "null"], "description": "r"},
                    "presentation": {
                        "type": ["string", "null"],
                        "enum": ["inspect", "teaching", None],
                        "description": "m",
                    },
                },
                "required": ["query"],
            },
        },
    }
]


def test_a_union_parameter_is_collapsed_onto_its_concrete_type() -> None:
    flattened = flatten_tool_schema_types(_UNION_TOOLS)
    assert flattened is not None
    properties = flattened[0]["function"]["parameters"]["properties"]
    assert properties["source_path"]["type"] == "string"
    assert properties["page"]["type"] == "integer"
    assert properties["region"]["type"] == "array"
    assert properties["query"]["type"] == "string"


def test_a_null_enum_member_is_dropped_with_the_union() -> None:
    flattened = flatten_tool_schema_types(_UNION_TOOLS)
    assert flattened is not None
    presentation = flattened[0]["function"]["parameters"]["properties"]["presentation"]
    assert presentation["type"] == "string"
    assert presentation["enum"] == ["inspect", "teaching"]


def test_the_original_schema_is_not_mutated() -> None:
    flatten_tool_schema_types(_UNION_TOOLS)
    properties = _UNION_TOOLS[0]["function"]["parameters"]["properties"]
    assert properties["source_path"]["type"] == ["string", "null"]


def test_a_tool_without_parameters_is_left_alone() -> None:
    tools: list[dict[str, Any]] = [{"type": "function", "function": {"name": "x"}}]
    assert flatten_tool_schema_types(tools) == tools
    assert flatten_tool_schema_types(None) is None


def test_the_mimo_endpoint_is_marked_as_cannot_typing_a_union() -> None:
    assert supports_nullable_tool_params("xiaomi_mimo") is False
    assert supports_nullable_tool_params("openai") is True


def _provider(binding: str):
    from deeptutor.services.llm.provider_core.openai_compat_provider import (
        OpenAICompatProvider,
    )
    from deeptutor.services.provider_registry import find_by_name

    spec = find_by_name(binding)
    return OpenAICompatProvider(
        api_key="test-key",
        api_base="https://example.invalid/v1",
        spec=spec,
        provider_name=binding,
        configure_env=False,
    )


def test_the_chat_completions_body_carries_the_flattened_schema() -> None:
    """The Chat Completions path is where the MiMo endpoint is reached."""
    provider = _provider("xiaomi_mimo")
    kwargs = provider._build_kwargs(
        [{"role": "user", "content": "hi"}],
        _UNION_TOOLS,
        "mimo-v2.6-flash",
        1024,
        0.7,
        None,
        None,
    )
    properties = kwargs["tools"][0]["function"]["parameters"]["properties"]
    assert properties["source_path"]["type"] == "string"
    assert properties["page"]["type"] == "integer"


def test_an_endpoint_that_can_type_a_union_keeps_it() -> None:
    provider = _provider("openai")
    kwargs = provider._build_kwargs(
        [{"role": "user", "content": "hi"}],
        _UNION_TOOLS,
        "gpt-4o",
        1024,
        0.7,
        None,
        None,
    )
    properties = kwargs["tools"][0]["function"]["parameters"]["properties"]
    assert properties["source_path"]["type"] == ["string", "null"]
