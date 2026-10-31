"""Event loop selection.

psycopg's async driver (used by Procrastinate) can't run on Windows' default Proactor loop, so every entry point
uses a selector loop there; elsewhere uvloop is used when installed.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from collections.abc import Callable, Coroutine
from typing import Any


def new_event_loop() -> asyncio.AbstractEventLoop:
    """Loop factory, also passed to uvicorn as ``loop="agnostic_server.loops:new_event_loop"``."""
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    try:
        uvloop = importlib.import_module("uvloop")
    except ImportError:
        return asyncio.new_event_loop()
    factory: Callable[[], asyncio.AbstractEventLoop] = uvloop.new_event_loop
    return factory()


def run[T](main: Callable[[], Coroutine[Any, Any, T]]) -> T:
    return asyncio.run(main(), loop_factory=new_event_loop)
