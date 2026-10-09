"""Small helpers that turn untyped JSON into typed values (or raise)."""

import json
from typing import cast

from codex_query.domain.errors import ProviderResponseError

type JsonObject = dict[str, object]


def parse_json(text: str) -> object:
    """Parse a JSON string, raising ProviderResponseError on failure.

    Args:
        text: The raw JSON string to parse.

    Returns:
        The parsed Python object.

    Raises:
        ProviderResponseError: If the string is not valid JSON.
    """
    try:
        value: object = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"Provider returned invalid JSON: {text[:200]!r}"
        raise ProviderResponseError(msg) from exc
    return value


def as_object_or_none(value: object) -> JsonObject | None:
    """Cast a value to a JsonObject if it is a dictionary.

    Args:
        value: The object to inspect.

    Returns:
        The dictionary cast as JsonObject, or None if it is not a dict.
    """
    if isinstance(value, dict):
        return cast("JsonObject", value)
    return None


def as_object(value: object, what: str) -> JsonObject:
    """Validate and cast a value to a JsonObject.

    Args:
        value: The object to validate.
        what: Context description of the field for error reporting.

    Returns:
        The value cast as JsonObject.

    Raises:
        ProviderResponseError: If the value is not a dictionary.
    """
    result = as_object_or_none(value)
    if result is None:
        msg = f"Expected a JSON object for {what!r}"
        raise ProviderResponseError(msg)
    return result


def as_list(value: object, what: str) -> list[object]:
    """Validate and cast a value to a list of objects.

    Args:
        value: The object to validate.
        what: Context description of the field for error reporting.

    Returns:
        The list of objects.

    Raises:
        ProviderResponseError: If the value is not a list.
    """
    if isinstance(value, list):
        return cast("list[object]", value)
    msg = f"Expected a JSON array for {what!r}"
    raise ProviderResponseError(msg)


def get_object(obj: JsonObject, key: str) -> JsonObject:
    """Retrieve a nested JsonObject from a dict by key.

    Args:
        obj: The source dictionary.
        key: The key to look up.

    Returns:
        The nested JsonObject.

    Raises:
        ProviderResponseError: If the key is missing or the value is not a dict.
    """
    return as_object(obj.get(key), key)


def get_object_or_empty(obj: JsonObject, key: str) -> JsonObject:
    """Retrieve a nested JsonObject by key, returning an empty dict
    if missing or invalid.

    Args:
        obj: The source dictionary.
        key: The key to look up.

    Returns:
        The nested JsonObject, or an empty dict.
    """
    return as_object_or_none(obj.get(key)) or {}


def get_list(obj: JsonObject, key: str) -> list[object]:
    """Retrieve a list from a dict by key.

    Args:
        obj: The source dictionary.
        key: The key to look up.

    Returns:
        The retrieved list.

    Raises:
        ProviderResponseError: If the key is missing or the value is not a list.
    """
    return as_list(obj.get(key), key)


def get_list_or_empty(obj: JsonObject, key: str) -> list[object]:
    """Retrieve a list by key, returning an empty list if missing or invalid.

    Args:
        obj: The source dictionary.
        key: The key to look up.

    Returns:
        The retrieved list, or an empty list.
    """
    value = obj.get(key)
    return cast("list[object]", value) if isinstance(value, list) else []


def get_str_or_none(obj: JsonObject, key: str) -> str | None:
    """Retrieve a string value by key, returning None if missing or not a string.

    Args:
        obj: The source dictionary.
        key: The key to look up.

    Returns:
        The string value, or None.
    """
    value = obj.get(key)
    return value if isinstance(value, str) else None


def get_int_or_none(obj: JsonObject, key: str) -> int | None:
    """Retrieve an integer value by key, excluding booleans.

    Args:
        obj: The source dictionary.
        key: The key to look up.

    Returns:
        The integer value, or None if missing, not an int, or a boolean.
    """
    value = obj.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def as_float_vector(value: object, what: str) -> list[float]:
    """Validate and convert a list into a vector of float values.

    Args:
        value: The object containing the list of numbers.
        what: Context description of the field for error reporting.

    Returns:
        A list of float numbers.

    Raises:
        ProviderResponseError: If the value is not a list or contains non-numeric
            items (including booleans).
    """
    vector: list[float] = []
    for item in as_list(value, what):
        if isinstance(item, bool) or not isinstance(item, int | float):
            msg = f"Non-numeric value in {what!r}"
            raise ProviderResponseError(msg)
        vector.append(float(item))
    return vector
