import math
import sys
from types import TracebackType
from typing import Any, AsyncIterator, Callable, Optional, Type, TypeVar

import anyio
from anyio.abc import AnyByteStream, ByteStream, TaskGroup
from anyio.streams.buffered import BufferedByteReceiveStream

from ._machine import TelnetClient, TelnetMachine, TelnetServer
from ._opt import Opt

if sys.version_info >= (3, 7):
    from contextlib import asynccontextmanager
else:
    from async_generator import asynccontextmanager

T = TypeVar("T", bound="_AnyioTelnet")


class _AnyioTelnet(ByteStream):
    _task_group: TaskGroup

    def __init__(self, stream: AnyByteStream, on_receive_error: Optional[Callable[[Exception], Any]] = None) -> None:
        self._stream = stream
        self._on_receive_error = on_receive_error

        self._msg_stream_producer, msg_stream_consumer = anyio.create_memory_object_stream(math.inf, item_type=bytes)
        self._msg_stream_buff = BufferedByteReceiveStream(msg_stream_consumer)
        send_producer, self._send_consumer = anyio.create_memory_object_stream(math.inf, item_type=bytes)

        self._machine = TelnetMachine()
        self._machine.register_receive_cb(self._msg_stream_producer.send_nowait)
        self._machine.register_send_cb(send_producer.send_nowait)

    @asynccontextmanager
    async def _make_ctx(self: T) -> AsyncIterator[T]:
        async with anyio.create_task_group() as self._task_group:
            self._task_group.start_soon(self._receive_worker)
            self._task_group.start_soon(self._send_worker)
            try:
                yield self
            finally:
                self._task_group.cancel_scope.cancel()
                await self.aclose()

    async def __aenter__(self: T) -> T:
        self._ctx = self._make_ctx()
        return await self._ctx.__aenter__()

    async def __aexit__(
        self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException], tb: Optional[TracebackType]
    ) -> None:
        await self._ctx.__aexit__(exc_type, exc, tb)

    async def _receive_worker(self) -> None:
        try:
            async for data in self._stream:
                try:
                    self._machine.receive_data(data)
                except anyio.get_cancelled_exc_class():
                    raise
                except Exception as exc:
                    if self._on_receive_error is not None:
                        self._on_receive_error(exc)
                    else:
                        raise
        finally:
            await self.aclose()

    async def _send_worker(self) -> None:
        async for data in self._send_consumer:
            await self._stream.send(data)

    async def aclose(self) -> None:
        await self._msg_stream_producer.aclose()

    async def send_eof(self) -> None:
        await self._stream.send_eof()

    async def receive(self, max_bytes: int = 4096) -> bytes:
        return await self._msg_stream_buff.receive(max_bytes=max_bytes)

    async def send(self, data: bytes) -> None:
        self._machine.send_message(data)

    async def send_command(self, cmd: Opt, opt: Optional[Opt] = None) -> None:
        self._machine.send_command(cmd, opt)


class AnyioTelnetServer(_AnyioTelnet):
    def __init__(self, stream: AnyByteStream, *args: Any, **kwargs: Any) -> None:
        super().__init__(stream, *args, **kwargs)
        self._server = TelnetServer(self._machine)


class AnyioTelnetClient(_AnyioTelnet):
    def __init__(self, stream: AnyByteStream, *args: Any, **kwargs: Any) -> None:
        super().__init__(stream, *args, **kwargs)
        self._client = TelnetClient(self._machine)
