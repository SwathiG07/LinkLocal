from collections import defaultdict
from typing import Any, Callable, DefaultDict, List


class EventEmitter:
    def __init__(self) -> None:
        self._handlers: DefaultDict[str, List[Callable[[Any], None]]] = defaultdict(list)

    def on(self, event_name: str, handler_fn: Callable[[Any], None]) -> None:
        self._handlers[event_name].append(handler_fn)

    def emit(self, event_name: str, data: Any) -> None:
        for handler in list(self._handlers.get(event_name, [])):
            handler(data)

    def off(self, event_name: str, handler_fn: Callable[[Any], None]) -> None:
        handlers = self._handlers.get(event_name, [])
        if handler_fn in handlers:
            handlers.remove(handler_fn)


bus = EventEmitter()
