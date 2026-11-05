from __future__ import annotations

import argparse
from typing import Callable

from mcp.server.fastmcp import FastMCP

from mcp_servers import catalog, commerce, knowledge

SERVERS: dict[str, tuple[Callable[..., FastMCP], int]] = {
    "commerce": (commerce.build, 9101),
    "catalog": (catalog.build, 9102),
    "knowledge": (knowledge.build, 9103),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="运行内部 MCP server")
    parser.add_argument("server", choices=sorted(SERVERS))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    builder, default_port = SERVERS[args.server]
    server = builder(host=args.host, port=args.port or default_port)
    server.run(transport="streamable-http")


if __name__ == "__main__":
    main()
