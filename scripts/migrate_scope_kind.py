from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import get_settings  # noqa: E402

SCOPE_EXPRESSION = """
CASE
    WHEN product_id IN ('STORE', 'PLATFORM') THEN lower(product_id)
    ELSE 'product'
END
"""

STATEMENTS = (
    f"""
    ALTER TABLE knowledge_parents
    ADD COLUMN IF NOT EXISTS scope_kind TEXT GENERATED ALWAYS AS (
        {SCOPE_EXPRESSION}
    ) STORED
    """,
    f"""
    ALTER TABLE knowledge_chunks
    ADD COLUMN IF NOT EXISTS scope_kind TEXT GENERATED ALWAYS AS (
        {SCOPE_EXPRESSION}
    ) STORED
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_parents_scope
    ON knowledge_parents (scope_kind, product_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chunks_scope
    ON knowledge_chunks (scope_kind, product_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS knowledge_state (
        id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        version BIGINT NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    INSERT INTO knowledge_state (id, version)
    VALUES (1, 0)
    ON CONFLICT (id) DO NOTHING
    """,
)


def migrate(database_url: str) -> dict[str, int]:
    with psycopg.connect(database_url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                for statement in STATEMENTS:
                    cur.execute(statement)

        counts = {}
        for table in ("knowledge_parents", "knowledge_chunks"):
            row = conn.execute(
                f"SELECT count(*) FROM {table} WHERE scope_kind = 'product'"
            ).fetchone()
            counts[table] = int(row[0]) if row else 0
    return counts


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="知识库迁移：scope_kind 生成列、索引、索引版本表（可重复执行）"
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="默认读取 DATABASE_URL",
    )
    args = parser.parse_args(argv)

    url = args.database_url or get_settings().database_url
    try:
        counts = migrate(url)
    except psycopg.Error as exc:
        print(f"失败：{type(exc).__name__}: {exc}")
        return 1

    for table, product_rows in counts.items():
        print(f"{table}: scope_kind 已就绪，商品类 {product_rows} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
