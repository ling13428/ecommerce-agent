from types import SimpleNamespace

import pytest

from core.config import get_settings
from rag.search import SearchError, search_knowledge


class FakeEmbeddings:
    def __init__(self):
        self.dim = get_settings().embedding_dim

    def create(self, model: str, input: list[str]):
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=index, embedding=[0.1] * self.dim)
                for index in range(len(input))
            ]
        )


class FakeClient:
    def __init__(self):
        self.embeddings = FakeEmbeddings()


class FakeCursor:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.execute_calls: list[tuple[str, list]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def execute(self, sql: str, params: list):
        self.execute_calls.append((sql, params))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.cursor_obj: FakeCursor | None = None

    def cursor(self, **kwargs):
        self.cursor_obj = FakeCursor(self.rows)
        return self.cursor_obj


def _row(
    chunk_id: str,
    parent_id: str,
    score: float,
    doc_id: str = "P2001-01",
    product_id: str = "P2001",
) -> dict:
    return {
        "chunk_id": chunk_id,
        "parent_id": parent_id,
        "doc_id": doc_id,
        "product_id": product_id,
        "title": "测试商品",
        "section_path": "测试商品 > 参数",
        "unit_kind": "section",
        "chunk_text": "子块内容",
        "chunk_metadata": {"doc_type": "product_faq"},
        "parent_text": "父块内容",
        "parent_metadata": {"source": "模拟商品库", "deprecated": False},
        "score": score,
    }


def test_search_dedupes_by_parent_and_keeps_score_order():
    conn = FakeConnection(
        [
            _row("C1", "P1", 0.91),
            _row("C2", "P1", 0.88),
            _row("C3", "P2", 0.72),
        ]
    )

    result = search_knowledge(
        "耳机续航",
        connection=conn,
        client=FakeClient(),
        min_score=0.3,
    )

    assert [hit.parent_id for hit in result.hits] == ["P1", "P2"]
    assert result.hits[0].chunk_id == "C1"
    assert result.hits[0].score == pytest.approx(0.91)
    assert result.abstained is False


def test_search_abstains_below_min_score():
    conn = FakeConnection([_row("C1", "P1", 0.2)])

    result = search_knowledge(
        "有没有现货", connection=conn, client=FakeClient(), min_score=0.4
    )

    assert result.abstained is True
    assert result.reason and "低于阈值" in result.reason
    assert len(result.hits) == 1


def test_search_abstains_when_nothing_found():
    result = search_knowledge(
        "完全不相关的问题",
        connection=FakeConnection([]),
        client=FakeClient(),
    )

    assert result.abstained is True
    assert result.reason == "无检索结果"
    assert result.hits == []


def test_search_passes_product_filter():
    conn = FakeConnection([_row("C1", "P1", 0.9, product_id="P2041")])

    result = search_knowledge(
        "耳机",
        connection=conn,
        client=FakeClient(),
        product_id="P2041",
    )

    assert result.hits[0].product_id == "P2041"
    assert conn.cursor_obj is not None
    sql, params = conn.cursor_obj.execute_calls[0]
    assert (
        "WHERE (c.product_id = %s OR c.scope_kind IN ('store', 'platform'))"
        in sql
    )
    assert params[1] == "P2041"


def test_search_excludes_deprecated_by_default():
    conn = FakeConnection([_row("C1", "P1", 0.9)])

    result = search_knowledge("退货政策", connection=conn, client=FakeClient())

    assert result.include_deprecated is False
    assert conn.cursor_obj is not None
    sql, _ = conn.cursor_obj.execute_calls[0]
    assert "COALESCE((c.metadata->>'deprecated')::boolean" in sql
    assert sql.count("WHERE") == 1
    assert "'STORE', 'PLATFORM'" not in sql


def test_search_can_include_deprecated_documents():
    conn = FakeConnection([_row("C1", "P1", 0.9)])

    result = search_knowledge(
        "2024 年退货政策",
        connection=conn,
        client=FakeClient(),
        include_deprecated=True,
    )

    assert result.include_deprecated is True
    assert conn.cursor_obj is not None
    sql, _ = conn.cursor_obj.execute_calls[0]
    assert "deprecated" not in sql
    assert "WHERE" not in sql


def test_search_combines_product_scope_and_deprecated_filters():
    conn = FakeConnection([_row("C1", "P1", 0.9, product_id="P2041")])

    search_knowledge(
        "VK75 Pro 的退货运费",
        connection=conn,
        client=FakeClient(),
        product_id="P2041",
    )

    assert conn.cursor_obj is not None
    sql, params = conn.cursor_obj.execute_calls[0]
    assert "c.product_id = %s OR c.scope_kind IN ('store', 'platform')" in sql
    assert "AND COALESCE((c.metadata->>'deprecated')::boolean" in sql
    assert params[1] == "P2041"


def test_search_merges_metadata_and_builds_citation():
    conn = FakeConnection([_row("C1", "P1", 0.9)])

    result = search_knowledge("耳机", connection=conn, client=FakeClient())

    hit = result.hits[0]
    assert hit.metadata["source"] == "模拟商品库"
    assert hit.metadata["doc_type"] == "product_faq"
    assert hit.citation == {
        "doc_id": "P2001-01",
        "parent_id": "P1",
        "title": "测试商品",
        "section": "测试商品 > 参数",
        "source": "模拟商品库",
        "authority_level": None,
        "version": None,
        "effective_date": None,
        "valid_until": None,
        "policy_domain": None,
        "region": None,
        "scope": None,
        "deprecated": False,
    }


def test_search_rejects_blank_query():
    with pytest.raises(SearchError, match="查询不能为空"):
        search_knowledge("   ", connection=FakeConnection([]))


def test_search_rejects_invalid_parameters():
    conn = FakeConnection([])
    with pytest.raises(SearchError, match="top_k"):
        search_knowledge("耳机", connection=conn, top_k=0)
    with pytest.raises(SearchError, match="candidate_k"):
        search_knowledge("耳机", connection=conn, top_k=5, candidate_k=2)
    with pytest.raises(SearchError, match="min_score"):
        search_knowledge("耳机", connection=conn, min_score=1.5)
