"""Input validation utilities for API endpoints.

This module provides helper functions for validating and extracting
parameters from requests, with proper error handling.
"""

from typing import Any, Callable, Optional, TypeVar
from starlette.requests import Request
from starlette.datastructures import QueryParams, FormData


T = TypeVar("T")


class ValidationError(Exception):
    """Raised when input validation fails."""
    pass


def get_required_param(
    params: QueryParams | FormData | dict,
    key: str,
    param_type: type[T] = str,
    validator: Optional[Callable[[T], bool]] = None,
) -> T:
    """Get a required parameter with type conversion and validation.

    Args:
        params: QueryParams, FormData, or dict to extract from
        key: Parameter name
        param_type: Type to convert to (default: str)
        validator: Optional validation function that returns True if valid

    Returns:
        The parameter value converted to the specified type

    Raises:
        ValidationError: If parameter is missing, conversion fails, or validation fails

    Examples:
        >>> get_required_param(request.query_params, "id", int)
        123
        >>> get_required_param(request.query_params, "username", str, lambda x: len(x) <= 16)
        "player123"
    """
    # Check if parameter exists
    if key not in params:
        raise ValidationError(f"Missing required parameter: {key}")

    # Get the raw value
    raw_value = params[key]

    # Handle empty strings
    if isinstance(raw_value, str) and not raw_value.strip():
        raise ValidationError(f"Parameter '{key}' cannot be empty")

    # Type conversion
    try:
        if param_type == str:
            value = str(raw_value).strip()
        elif param_type == int:
            value = int(raw_value)
        elif param_type == float:
            value = float(raw_value)
        elif param_type == bool:
            # Convert string boolean values
            if isinstance(raw_value, str):
                value = raw_value.lower() in ("true", "1", "yes", "on")
            else:
                value = bool(raw_value)
        else:
            value = param_type(raw_value)
    except (ValueError, TypeError) as e:
        raise ValidationError(
            f"Invalid value for parameter '{key}': expected {param_type.__name__}, got '{raw_value}'"
        ) from e

    # Run custom validator if provided
    if validator is not None:
        try:
            if not validator(value):
                raise ValidationError(f"Validation failed for parameter '{key}': {value}")
        except Exception as e:
            raise ValidationError(
                f"Validation error for parameter '{key}': {e}"
            ) from e

    return value


def get_optional_param(
    params: QueryParams | FormData | dict,
    key: str,
    default: T,
    param_type: type[T] = str,
    validator: Optional[Callable[[T], bool]] = None,
) -> T:
    """Get an optional parameter with type conversion and validation.

    Args:
        params: QueryParams, FormData, or dict to extract from
        key: Parameter name
        default: Default value if parameter is missing
        param_type: Type to convert to
        validator: Optional validation function that returns True if valid

    Returns:
        The parameter value converted to the specified type, or default if missing

    Examples:
        >>> get_optional_param(request.query_params, "page", 1, int)
        1
        >>> get_optional_param(request.query_params, "limit", 50, int, lambda x: 0 < x <= 100)
        50
    """
    if key not in params:
        return default

    try:
        return get_required_param(params, key, param_type, validator)
    except ValidationError:
        # If validation fails for an optional param, return default
        return default


def validate_range(min_val: Optional[float] = None, max_val: Optional[float] = None) -> Callable:
    """Create a validator that checks if a value is within a range.

    Args:
        min_val: Minimum value (inclusive), or None for no minimum
        max_val: Maximum value (inclusive), or None for no maximum

    Returns:
        Validator function

    Example:
        >>> get_required_param(params, "age", int, validate_range(0, 120))
    """
    def validator(value: float) -> bool:
        if min_val is not None and value < min_val:
            raise ValueError(f"Value must be >= {min_val}")
        if max_val is not None and value > max_val:
            raise ValueError(f"Value must be <= {max_val}")
        return True
    return validator


def validate_length(min_len: Optional[int] = None, max_len: Optional[int] = None) -> Callable:
    """Create a validator that checks string length.

    Args:
        min_len: Minimum length (inclusive), or None for no minimum
        max_len: Maximum length (inclusive), or None for no maximum

    Returns:
        Validator function

    Example:
        >>> get_required_param(params, "username", str, validate_length(3, 16))
    """
    def validator(value: str) -> bool:
        length = len(value)
        if min_len is not None and length < min_len:
            raise ValueError(f"Length must be >= {min_len}")
        if max_len is not None and length > max_len:
            raise ValueError(f"Length must be <= {max_len}")
        return True
    return validator


def validate_one_of(allowed_values: list[Any]) -> Callable:
    """Create a validator that checks if value is in a list of allowed values.

    Args:
        allowed_values: List of allowed values

    Returns:
        Validator function

    Example:
        >>> get_required_param(params, "mode", str, validate_one_of(["osu", "taiko", "catch", "mania"]))
    """
    def validator(value: Any) -> bool:
        if value not in allowed_values:
            raise ValueError(f"Value must be one of: {allowed_values}")
        return True
    return validator


def validate_pattern(pattern: str) -> Callable:
    """Create a validator that checks if a string matches a regex pattern.

    Args:
        pattern: Regular expression pattern

    Returns:
        Validator function

    Example:
        >>> get_required_param(params, "email", str, validate_pattern(r'^[\w\.-]+@[\w\.-]+\.\w+$'))
    """
    import re
    compiled_pattern = re.compile(pattern)

    def validator(value: str) -> bool:
        if not compiled_pattern.match(value):
            raise ValueError(f"Value does not match required pattern")
        return True
    return validator


def safe_get_list_item(items: list, index: int, default: Any = None) -> Any:
    """Safely get an item from a list by index.

    Args:
        items: List to access
        index: Index to retrieve
        default: Default value if index is out of bounds

    Returns:
        The item at the index, or default if out of bounds

    Example:
        >>> safe_get_list_item(login_info, 0, "")
        "username"
    """
    try:
        return items[index]
    except (IndexError, TypeError):
        return default
