"""Pretty-printing utilities for structured data."""

from typing import Dict, Any
import ujson as json


def pp(d: Dict[str, Any] | list[Any] | Any | None = None) -> str:
    """Pretty-print a data structure to a JSON string."""
    if d is None:
        return '{}'
    else:
        return json.dumps(d, indent=2, escape_forward_slashes=False)
