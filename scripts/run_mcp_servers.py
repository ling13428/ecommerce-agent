from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVERS = (("commerce", 9101), ("catalog", 9102), ("knowledge", 9103))


def main() -> None:
    parser = argparse.ArgumentParser(description="本地启动全部内部 MCP server")
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    processes: list[tuple[str, subprocess.Popen]] = []
    try:
        for name, port in SERVERS:
            command = [
                sys.executable,
                "-m",
                "mcp_servers.run",
                name,
                "--host",
                args.host,
                "--port",
                str(port),
            ]
            processes.append((name, subprocess.Popen(command, cwd=ROOT)))
            print(f"[mcp] {name} -> http://{args.host}:{port}/mcp")
        while True:
            for name, process in processes:
                code = process.poll()
                if code is not None:
                    raise SystemExit(f"[mcp] {name} 已退出，code={code}")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[mcp] 正在停止...")
    finally:
        for _, process in processes:
            process.terminate()
        for _, process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
