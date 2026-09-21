"""JSON validation and formatting utilities."""

import json


def validate_and_format_json(raw_text: str) -> str:
    """Validate a JSON string and return it indented with 2 spaces.

    Args:
        raw_text: A string containing JSON data.

    Returns:
        The JSON re-serialized with 2-space indentation.

    Raises:
        ValueError: If ``raw_text`` is not valid JSON.
    """
    if not isinstance(raw_text, str):
        raise ValueError("Input must be a string containing JSON.")

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc

    return json.dumps(parsed, indent=2, ensure_ascii=False)
