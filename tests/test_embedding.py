from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError

from rag.embedding import EmbeddingError, embed_texts


class FakeEmbeddings:
    def __init__(self, dim: int = 1024, fail_times: int = 0):
        self.dim = dim
        self.fail_times = fail_times
        self.calls: list[list[str]] = []
        self._counter = 0

    def create(self, model: str, input: list[str]):
        self.calls.append(list(input))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise APIConnectionError(
                request=httpx.Request("POST", "https://example.com/v1/embeddings")
            )
        data = []
        for index in range(len(input)):
            self._counter += 1
            data.append(
                SimpleNamespace(
                    index=index,
                    embedding=[float(self._counter)] * self.dim,
                )
            )
        return SimpleNamespace(data=data)


class FakeClient:
    def __init__(self, embeddings: FakeEmbeddings):
        self.embeddings = embeddings


def test_embed_texts_batches_and_keeps_order():
    fake = FakeEmbeddings()
    client = FakeClient(fake)

    vectors = embed_texts(
        ["a", "b", "c", "d", "e"], client=client, batch_size=2
    )

    assert [len(batch) for batch in fake.calls] == [2, 2, 1]
    assert len(vectors) == 5
    assert [vector[0] for vector in vectors] == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_embed_texts_retries_connection_errors():
    fake = FakeEmbeddings(fail_times=1)
    client = FakeClient(fake)

    vectors = embed_texts(
        ["a"], client=client, max_retries=1, retry_delay=0
    )

    assert len(fake.calls) == 2
    assert len(vectors) == 1


def test_embed_texts_rejects_dimension_mismatch():
    fake = FakeEmbeddings(dim=8)
    client = FakeClient(fake)

    with pytest.raises(EmbeddingError, match="维度不匹配"):
        embed_texts(["a"], client=client)


def test_embed_texts_returns_empty_for_empty_input():
    fake = FakeEmbeddings()
    client = FakeClient(fake)

    assert embed_texts([], client=client) == []
    assert fake.calls == []


def test_embed_texts_rejects_blank_text():
    fake = FakeEmbeddings()
    client = FakeClient(fake)

    with pytest.raises(EmbeddingError, match="文本为空"):
        embed_texts(["ok", "  "], client=client)
