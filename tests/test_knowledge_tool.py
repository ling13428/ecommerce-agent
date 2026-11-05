import tools.knowledge as knowledge
from rag.search import SearchHit, SearchResult
from tools.registry import execute_tool


def _hit(parent_id: str = "P2001-02_P001", score: float = 0.72) -> SearchHit:
    return SearchHit(
        chunk_id=f"{parent_id}_C001",
        parent_id=parent_id,
        doc_id="P2001-02",
        product_id="P2001",
        title="烬狐 VK75 Pro 磁轴键盘",
        section_path="P2001 烬狐 VK75 Pro 磁轴键盘 > 规格参数",
        unit_kind="section",
        text="键盘支持 8000Hz 回报率。",
        parent_text="## 规格参数\n\n键盘支持 8000Hz 回报率。",
        score=score,
        metadata={"source": "模拟商品库", "version": "v1"},
    )


def _result(
    hits: list[SearchHit],
    abstained: bool = False,
    reason: str | None = None,
) -> SearchResult:
    return SearchResult(
        query="键盘续航多久",
        hits=hits,
        abstained=abstained,
        reason=reason,
        min_score=0.35,
    )


def test_search_tool_returns_parent_content_and_citation(monkeypatch):
    monkeypatch.setattr(
        knowledge, "_search_rag", lambda query, **kwargs: _result([_hit()])
    )

    result = execute_tool("search_knowledge", {"query": "键盘续航多久"})

    assert result["ok"] is True
    payload = result["result"]
    assert payload["found"] is True
    assert payload["abstained"] is False
    assert payload["results"][0]["doc_id"] == "P2001-02"
    assert payload["results"][0]["section"] == "P2001 烬狐 VK75 Pro 磁轴键盘 > 规格参数"
    assert payload["results"][0]["source"] == "模拟商品库"
    assert payload["results"][0]["content"].startswith("## 规格参数")


def test_search_tool_forwards_product_and_top_k(monkeypatch):
    captured = {}

    def fake(query, **kwargs):
        captured.update(query=query, **kwargs)
        return _result([_hit()])

    monkeypatch.setattr(knowledge, "_search_rag", fake)

    execute_tool(
        "search_knowledge",
        {"query": "续航", "product_id": "P2001", "top_k": 3},
    )

    assert captured == {
        "query": "续航",
        "product_id": "P2001",
        "top_k": 3,
        "include_deprecated": False,
    }


def test_search_tool_forwards_include_deprecated(monkeypatch):
    captured = {}

    def fake(query, **kwargs):
        captured.update(query=query, **kwargs)
        return _result([_hit()])

    monkeypatch.setattr(knowledge, "_search_rag", fake)

    execute_tool(
        "search_knowledge",
        {"query": "2024 年退货政策", "include_deprecated": True},
    )

    assert captured["include_deprecated"] is True


def test_search_tool_infers_product_id_from_query(monkeypatch):
    captured = {}

    def fake(query, **kwargs):
        captured.update(query=query, **kwargs)
        return _result([_hit()])

    monkeypatch.setattr(knowledge, "_search_rag", fake)

    result = execute_tool(
        "search_knowledge", {"query": "VK75 Pro 怎么配对"}
    )

    assert captured["product_id"] == "P2001"
    assert result["result"]["product_id"] == "P2001"


def test_search_tool_keeps_explicit_product_id_over_inference(monkeypatch):
    captured = {}

    def fake(query, **kwargs):
        captured.update(query=query, **kwargs)
        return _result([_hit()])

    monkeypatch.setattr(knowledge, "_search_rag", fake)

    execute_tool(
        "search_knowledge", {"query": "VK75 Pro", "product_id": "P2041"}
    )

    assert captured["product_id"] == "P2041"


def test_search_tool_leaves_product_id_none_without_match(monkeypatch):
    captured = {}

    def fake(query, **kwargs):
        captured.update(query=query, **kwargs)
        return _result([_hit()])

    monkeypatch.setattr(knowledge, "_search_rag", fake)

    execute_tool("search_knowledge", {"query": "退货政策是什么"})

    assert captured["product_id"] is None


def test_low_score_triggers_handoff(monkeypatch):
    monkeypatch.setattr(
        knowledge,
        "_search_rag",
        lambda query, **kwargs: _result(
            [_hit(score=0.21)], abstained=True, reason="最高相似度 0.210 低于阈值 0.35"
        ),
    )

    result = execute_tool("search_knowledge", {"query": "能便宜点吗"})

    assert result["ok"] is True
    assert result["status"] == "handoff"
    assert "知识库无可靠答案" in result["reason"]
    assert result["abstained"] is True


def test_empty_result_triggers_handoff(monkeypatch):
    monkeypatch.setattr(
        knowledge,
        "_search_rag",
        lambda query, **kwargs: _result([], abstained=True, reason="无检索结果"),
    )

    result = execute_tool("search_knowledge", {"query": "今天天气"})

    assert result["status"] == "handoff"
    assert result["found"] is False


def test_search_tool_rejects_blank_and_oversized_args():
    blank = execute_tool("search_knowledge", {"query": "   "})
    assert blank["ok"] is False
    assert "参数校验失败" in blank["error"]

    too_many = execute_tool("search_knowledge", {"query": "键盘", "top_k": 9})
    assert too_many["ok"] is False
    assert "参数校验失败" in too_many["error"]
