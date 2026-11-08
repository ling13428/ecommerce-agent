from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    from agent.session_repo import get_repository
    from core.config import get_settings

    settings = get_settings()
    repository = get_repository()
    if repository is None:
        print("当前未启用 normalized 会话存储，无需清理")
        return 1

    parser = argparse.ArgumentParser(description="清理过期的持久化会话")
    parser.add_argument(
        "--days",
        type=int,
        default=settings.session_retention_days,
        help="保留天数，默认取 SESSION_RETENTION_DAYS",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    cutoff = time.time() - args.days * 24 * 3600
    if args.dry_run:
        pending = [
            meta
            for meta in repository.list_meta()
            if float(meta.get("last_active_at") or 0) < cutoff
        ]
        print(f"待清理 {len(pending)} 个会话（早于 {args.days} 天）")
        return 0
    deleted = repository.delete_older_than(cutoff)
    print(f"已清理 {deleted} 个会话（早于 {args.days} 天）")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main())
