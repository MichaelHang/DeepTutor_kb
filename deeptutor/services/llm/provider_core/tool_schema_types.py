"""Advertise tool parameters a provider can actually type.

Some OpenAI-compatible endpoints cannot map a *union* parameter type — a
parameter declared ``["string", "null"]`` — back onto a tool call they
stream. The Xiaomi MiMo endpoint does exactly that: it stops writing the
tool call's arguments at the union-typed parameter and closes the argument
object there, so the model receives a truncated JSON fragment. The fragment is
then "repaired" into a nested object, and the parameter the model set — a
document path, a page number — silently arrives as a dictionary instead.

The tool's own schema keeps the union, because DeepTutor's argument guard
distinguishes "absent" from "explicitly null" by it (#1928). Only the wire
copy is flattened, and only for the endpoints that need it.
"""

from __future__ import annotations

from typing import Any

__all__ = ["flatten_tool_schema_types", "flatten_tools_schema_types", "wire_tool_schemas"]


def _flatten_property(prop: Any) -> Any:
    """Collapse a union-typed property onto its first concrete type."""
    if not isinstance(prop, dict):
        return prop
    schema_type = prop.get("type")
    if not isinstance(schema_type, list):
        return prop
    concrete = next((item for item in schema_type if item != "null"), None)
    if concrete is None:
        return prop
    flattened = dict(prop)
    flattened["type"] = concrete
    enum = flattened.get("enum")
    if isinstance(enum, list):
        without_null = [item for item in enum if item is not None]
        if without_null:
            flattened["enum"] = without_null
        else:
            flattened.pop("enum")
    return flattened


def flatten_tool_schema_types(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Return *tools* with every union-typed parameter collapsed to one type."""
    if not tools:
        return tools
    flattened: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            flattened.append(tool)
            continue
        function = tool.get("function")
        if not isinstance(function, dict):
            flattened.append(tool)
            continue
        parameters = function.get("parameters")
        if not isinstance(parameters, dict):
            flattened.append(tool)
            continue
        properties = parameters.get("properties")
        if not isinstance(properties, dict):
            flattened.append(tool)
            continue
        new_function = dict(function)
        new_parameters = dict(parameters)
        new_parameters["properties"] = {
            name: _flatten_property(prop) for name, prop in properties.items()
        }
        new_function["parameters"] = new_parameters
        new_tool = dict(tool)
        new_tool["function"] = new_function
        flattened.append(new_tool)
    return flattened


def flatten_tools_schema_types(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Alias kept for call sites that read better without the extra word."""
    return flatten_tool_schema_types(tools)


def wire_tool_schemas(
    tools: list[dict[str, Any]] | None, binding: str | None, model: str | None = None
) -> list[dict[str, Any]] | None:
    """The tool schemas *binding* can actually type.

    Endpoints that cannot map a union-typed parameter get the flattened copy;
    the rest keep the union, which is what DeepTutor's argument guard reads
    to tell "absent" from "explicitly null" (#1928).
    """
    if not tools:
        return tools
    from deeptutor.services.llm.capabilities import supports_nullable_tool_params

    if supports_nullable_tool_params(binding or "", model):
        return tools
    return flatten_tool_schema_types(tools) or tools
