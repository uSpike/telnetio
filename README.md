telnetio
========

A Sans-IO implementation of a telnet parser.

Includes an `anyio` server implementation.  To install use the `anyio` extra, such as `pip install telnetio[anyio]`.
An example echo server:

```python
import anyio
from anyio.abc import AnyByteStream

from telnetio import AnyioTelnetServer

async def handler(stream: AnyByteStream) -> None:
    async with AnyioTelnetServer(stream) as telnet:
        async for data in telnet:
            await telnet.send(data)

async def main() -> None:
    listener = await anyio.create_tcp_listener(local_port=1234)
    await listener.serve(handler)

anyio.run(main)
```
