import math
from contextlib import asynccontextmanager
from types import TracebackType
from typing import AsyncIterator, Optional, Type

import anyio
from anyio.abc import AnyByteStream, ByteStream, TaskGroup
from anyio.streams.buffered import BufferedByteReceiveStream

from ._machine import Event, ReceiveMessage, SendData, TelnetMachine


class AnyioTelnetServer(ByteStream):
    _task_group: TaskGroup

    def __init__(self, stream: AnyByteStream) -> None:
        self._stream = stream
        self._msg_stream_producer, msg_stream_consumer = anyio.create_memory_object_stream(math.inf, item_type=bytes)
        self._msg_stream_buff = BufferedByteReceiveStream(msg_stream_consumer)
        self._machine = TelnetMachine()
        self._machine.register_event_cb(self._receive_event)

    @asynccontextmanager
    async def _make_ctx(self) -> "AsyncIterator[AnyioTelnetServer]":
        async with anyio.create_task_group() as self._task_group:
            self._task_group.start_soon(self._receive_worker)
            try:
                yield self
            finally:
                self._task_group.cancel_scope.cancel()
                await self.aclose()

    async def __aenter__(self) -> "AnyioTelnetServer":
        self._ctx = self._make_ctx()
        return await self._ctx.__aenter__()

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        await self._ctx.__aexit__(exc_type, exc_value, traceback)

    def _receive_event(self, event: Event) -> None:
        if isinstance(event, ReceiveMessage):
            self._msg_stream_producer.send_nowait(event.contents)
        elif isinstance(event, SendData):
            self._task_group.start_soon(self._stream.send, event.contents)

    async def _receive_worker(self) -> None:
        async for data in self._stream:
            self._machine.receive_data(data)

    async def aclose(self) -> None:
        await self._msg_stream_buff.aclose()

    async def send_eof(self) -> None:
        await self._stream.send_eof()

    async def receive(self, max_bytes: int = 4096) -> bytes:
        return await self._msg_stream_buff.receive(max_bytes=max_bytes)

    async def send(self, data: bytes) -> None:
        self._machine.send_message(data)
