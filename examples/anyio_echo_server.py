"""
This is a simple telnet echo server on port 1234
"""
import logging

import anyio
from anyio.abc import AnyByteStream

from telnetio import AnyioTelnetServer

LOG = logging.getLogger(__name__)


async def handler(stream: AnyByteStream) -> None:
    async with stream, AnyioTelnetServer(stream, on_receive_error=LOG.exception) as telnet:
        await telnet.send(b"Welcome to Zombocom!\r\n")
        await telnet.send(b"You can do anything at Zombocom!\r\n")
        async for data in telnet:
            await telnet.send(data)


async def main() -> None:
    listener = await anyio.create_tcp_listener(local_port=1234)
    await listener.serve(handler)


anyio.run(main)
