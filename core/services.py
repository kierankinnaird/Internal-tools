"""A tiny registry so one module can offer something to another without importing it. """
from __future__ import annotations
from typing import Any, Dict

class Services:
    def __init__(self):
        self._items: Dict[str, Any] ={}

    def register(self, name: str, obj: Any) -> None:
        self._items[name] = obj

    def get(self, name: str):
        """Returns the service, or None when the module offering it is not installed."""
        return self._items.get(name)

    def has(self, name: str) -> bool:
        return name in self._items