from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    from core.config import get_settings
    from core.db import get_pool

    settings = get_settings()
    if (settings.session_store_backend or "").strip().lower() != "postgres":
        print("当前 SESSION_STORE_BACKEND 不是 postgres，无需清理")
        return 1

    parser = argparse.ArgumentParser(description="清理过期的 Postgres 会话")
    parser.add_argument(
        "--days",
        type=int,
        default=settings.session_retention_days,
        help="保留天数，默认取 SESSION_RETENTION_DAYS",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cutoff = time.time() - args.days * 24 * 3600
    with get_pool().connection() as connection:
        if args.dry_run:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM chat_sessions "
                "WHERE updated_at < %s",
                (cutoff,),
            ).fetchone()
            print(f"待清理 {row['total']} 个会话（早于 {args.days} 天）")
            return 0
        cursor = connection.execute(
            "DELETE FROM chat_sessions WHERE updated_at < %s",
            (cutoff,),
        )
        print(f"已清理 {cursor.rowcount} 个会话（早于 {args.days} 天）")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
