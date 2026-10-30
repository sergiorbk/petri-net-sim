"""Event-loop factory for local servers with PostgreSQL checkpointing."""

import asyncio
import sys


def new_event_loop() -> asyncio.AbstractEventLoop:
    # Psycopg's asynchronous connections require a selector loop on Windows.
    if sys.platform == "win32":
        return asyncio.SelectorEventLoop()
    return asyncio.new_event_loop()
