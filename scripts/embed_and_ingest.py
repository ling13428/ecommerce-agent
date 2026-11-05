from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.config import get_settings  # noqa: E402
from rag.embedding import EmbeddingError, embed_texts  # noqa: E402
from rag.store import (  # noqa: E402
    IngestError,
    load_jsonl,
    upsert_knowledge,
    validate_inputs,
)


def run(
    input_dir: Path,
    database_url: str,
    batch_size: int | None = None,
    prune: bool = False,
) -> dict[str, int]:
    parents = load_jsonl(input_dir / "parents.jsonl")
    children = load_jsonl(input_dir / "chunks.jsonl")
    validate_inputs(parents, children)

    print(f"读取：{len(parents)} 个父块 / {len(children)} 个子块")

    started = time.perf_counter()
    vectors = embed_texts(
        [str(child["text"]) for child in children],
        batch_size=batch_size,
    )
    elapsed = time.perf_counter() - started
    print(f"向量化：{len(vectors)} 条，耗时 {elapsed:.2f}s")

    result = upsert_knowledge(
        parents=parents,
        children=children,
        embeddings=vectors,
        database_url=database_url,
        prune=prune,
    )
    print(
        "写入完成："
        f"本次父块 {result['input_parents']} / 子块 {result['input_chunks']}，"
        f"数据库总计 {result['parents']} / {result['chunks']}"
    )
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="生成 embedding 并写入 PostgreSQL + pgvector")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data" / "processed",
        help="包含 parents.jsonl 和 chunks.jsonl 的目录",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="默认读取 DATABASE_URL",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="每批 embedding 条数，默认读取 EMBEDDING_BATCH_SIZE",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="删除数据库中不在本次输入里的旧父块和子块",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.embedding_configured:
        print("EMBEDDING_API_KEY 未配置，无法生成向量")
        return 2

    try:
        run(
            input_dir=args.input,
            database_url=args.database_url or settings.database_url,
            batch_size=args.batch_size,
            prune=args.prune,
        )
    except (EmbeddingError, IngestError, psycopg.Error, FileNotFoundError) as exc:
        print(f"失败：{type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
