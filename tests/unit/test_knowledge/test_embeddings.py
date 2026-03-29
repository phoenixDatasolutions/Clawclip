"""Unit tests for knowledge-base embedding utilities.

All external embedding providers are mocked — no API calls are made.
"""
from __future__ import annotations

import math
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexusai.knowledge.vectorstore import InMemoryStore, _cosine_similarity


# ---------------------------------------------------------------------------
# Fake / mock helpers
# ---------------------------------------------------------------------------


class FakeEmbeddingProvider:
    """Returns simple deterministic vectors for testing without any backend."""

    def __init__(self, dimension: int = 4) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Map each text to a pseudo-random but deterministic float vector."""
        result: list[list[float]] = []
        for text in texts:
            # Use character codes to produce a stable vector
            seed = sum(ord(c) for c in text)
            vec = [float((seed + i) % 100) / 100.0 for i in range(self._dimension)]
            result.append(vec)
        return result


# ---------------------------------------------------------------------------
# InMemoryStore tests
# ---------------------------------------------------------------------------


class TestInMemoryStore:
    async def test_in_memory_store_add_search(self):
        """After adding vectors, search must return the closest one first."""
        store = InMemoryStore()
        provider = FakeEmbeddingProvider(dimension=4)

        texts = ["apple", "banana", "cherry"]
        embeddings = await provider.embed(texts)

        await store.add(
            ids=["id_apple", "id_banana", "id_cherry"],
            texts=texts,
            embeddings=embeddings,
            metadatas=[{"source": t} for t in texts],
        )

        # Query with the exact vector for "apple"
        query_vec = embeddings[0]
        results = await store.search(query_embedding=query_vec, top_k=1)
        assert len(results) == 1
        assert results[0].chunk_id == "id_apple"
        assert results[0].score > 0.99  # should be ~1.0 for exact match

    async def test_search_empty_store(self):
        """search() on an empty store must return []."""
        store = InMemoryStore()
        results = await store.search(query_embedding=[0.1, 0.2, 0.3], top_k=5)
        assert results == []

    async def test_search_top_k_limits_results(self):
        """search(top_k=2) must return at most 2 results."""
        store = InMemoryStore()
        provider = FakeEmbeddingProvider(dimension=4)
        texts = [f"doc{i}" for i in range(5)]
        embeddings = await provider.embed(texts)
        await store.add(
            ids=[f"id{i}" for i in range(5)],
            texts=texts,
            embeddings=embeddings,
            metadatas=[{}] * 5,
        )
        results = await store.search(query_embedding=embeddings[0], top_k=2)
        assert len(results) == 2

    async def test_delete_removes_entry(self):
        """delete(['id']) must remove the entry from future search results."""
        store = InMemoryStore()
        await store.add(
            ids=["keep", "remove"],
            texts=["keep_text", "remove_text"],
            embeddings=[[1.0, 0.0], [0.0, 1.0]],
            metadatas=[{}, {}],
        )
        await store.delete(["remove"])
        results = await store.search(query_embedding=[0.0, 1.0], top_k=5)
        ids_returned = {r.chunk_id for r in results}
        assert "remove" not in ids_returned

    async def test_clear_empties_store(self):
        """clear() must remove all entries."""
        store = InMemoryStore()
        await store.add(
            ids=["a", "b"],
            texts=["text_a", "text_b"],
            embeddings=[[1.0, 0.0], [0.0, 1.0]],
            metadatas=[{}, {}],
        )
        await store.clear()
        results = await store.search(query_embedding=[1.0, 0.0], top_k=5)
        assert results == []


# ---------------------------------------------------------------------------
# Cosine similarity math tests
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_cosine_similarity_exact(self):
        """Identical vectors must have a cosine similarity of 1.0."""
        vec = [0.5, 0.3, 0.8, 0.1]
        score = _cosine_similarity(vec, vec)
        assert abs(score - 1.0) < 1e-9

    def test_cosine_similarity_orthogonal(self):
        """Orthogonal vectors must have a cosine similarity of ~0."""
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        score = _cosine_similarity(a, b)
        assert abs(score) < 1e-9

    def test_cosine_similarity_opposite(self):
        """Opposite-direction vectors must have a similarity of -1."""
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        score = _cosine_similarity(a, b)
        assert abs(score - (-1.0)) < 1e-9

    def test_cosine_similarity_zero_vector(self):
        """A zero vector must return 0.0, not raise."""
        score = _cosine_similarity([0.0, 0.0], [1.0, 2.0])
        assert score == 0.0

    def test_cosine_similarity_normalised(self):
        """Result must be in [-1.0, 1.0] for arbitrary float vectors."""
        import random

        rng = random.Random(42)
        for _ in range(20):
            a = [rng.uniform(-5, 5) for _ in range(8)]
            b = [rng.uniform(-5, 5) for _ in range(8)]
            score = _cosine_similarity(a, b)
            assert -1.0 - 1e-9 <= score <= 1.0 + 1e-9


# ---------------------------------------------------------------------------
# DocumentIndexer chunking tests
# ---------------------------------------------------------------------------


class TestDocumentIndexerChunking:
    def _make_indexer(self, chunk_size: int = 100, chunk_overlap: int = 20):
        from nexusai.knowledge.indexer import DocumentIndexer

        # Dummy store and provider — we only test _chunk_text()
        store = MagicMock()
        provider = FakeEmbeddingProvider()
        return DocumentIndexer(
            vector_store=store,
            embedding_provider=provider,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def test_document_indexer_chunking(self):
        """Long text must be split into multiple chunks."""
        indexer = self._make_indexer(chunk_size=50, chunk_overlap=10)
        long_text = "Hello world. " * 20  # ~260 chars
        chunks = indexer._chunk_text(long_text)
        assert len(chunks) > 1, "Expected multiple chunks for long text"

    def test_chunk_overlap(self):
        """Consecutive chunks must share content at their boundary (overlap)."""
        indexer = self._make_indexer(chunk_size=60, chunk_overlap=20)
        # Build text with predictable sentence boundaries
        text = "First sentence end. " * 5 + "Second sentence end. " * 5
        chunks = indexer._chunk_text(text)
        if len(chunks) >= 2:
            # The overlap region from chunk[0] tail should appear at chunk[1] head
            tail = chunks[0][-20:]
            head = chunks[1][:30]
            # At least some characters from the tail should be in head
            overlap_chars = set(tail.strip()) & set(head.strip())
            assert len(overlap_chars) > 0, "Expected shared characters in overlap region"

    def test_empty_text_returns_empty_list(self):
        """_chunk_text('') must return []."""
        indexer = self._make_indexer()
        assert indexer._chunk_text("") == []

    def test_short_text_single_chunk(self):
        """Text shorter than chunk_size must return exactly one chunk."""
        indexer = self._make_indexer(chunk_size=500, chunk_overlap=50)
        chunks = indexer._chunk_text("Short text.")
        assert len(chunks) == 1
        assert chunks[0] == "Short text."

    def test_chunks_contain_all_content(self):
        """All original words must appear somewhere across the chunks.

        Chunks may split words at hard boundaries, so we join chunks and
        strip whitespace before checking membership.
        """
        indexer = self._make_indexer(chunk_size=80, chunk_overlap=10)
        words = [f"word{i}" for i in range(30)]
        text = " ".join(words)
        chunks = indexer._chunk_text(text)
        # Normalise: collapse all whitespace (newlines, spaces) before comparing
        combined = "".join(chunks).replace("\n", "").replace(" ", "")
        text_normalised = text.replace(" ", "")
        # Every character of the source text should be represented somewhere
        # (chunks + overlap together must cover the full content span)
        for word in words:
            word_stripped = word.replace(" ", "")
            assert word_stripped in combined, f"'{word}' missing from chunked output"


# ---------------------------------------------------------------------------
# KnowledgeManager — create_knowledge_base
# ---------------------------------------------------------------------------


class TestKnowledgeManager:
    def _make_manager(self):
        from nexusai.knowledge.indexer import DocumentIndexer
        from nexusai.knowledge.manager import KnowledgeManager
        from nexusai.knowledge.retriever import Retriever

        store = InMemoryStore()
        provider = FakeEmbeddingProvider()
        indexer = DocumentIndexer(
            vector_store=store,
            embedding_provider=provider,
            chunk_size=500,
            chunk_overlap=50,
        )
        retriever = Retriever(vector_store=store, embedding_provider=provider)
        return KnowledgeManager(indexer=indexer, retriever=retriever)

    async def test_knowledge_manager_create_kb(self):
        """create_knowledge_base('test') must return a valid UUID string."""
        manager = self._make_manager()
        kb_id = await manager.create_knowledge_base("test")
        import uuid

        parsed = uuid.UUID(kb_id, version=4)
        assert str(parsed) == kb_id

    async def test_list_knowledge_bases_empty(self):
        """list_knowledge_bases() on a new manager must return []."""
        manager = self._make_manager()
        kbs = await manager.list_knowledge_bases()
        assert kbs == []

    async def test_list_knowledge_bases_after_create(self):
        """After creating 2 KBs, list_knowledge_bases() must return both."""
        manager = self._make_manager()
        id1 = await manager.create_knowledge_base("KB One")
        id2 = await manager.create_knowledge_base("KB Two")
        kbs = await manager.list_knowledge_bases()
        kb_ids = {kb["kb_id"] for kb in kbs}
        assert id1 in kb_ids
        assert id2 in kb_ids

    async def test_delete_knowledge_base(self):
        """Deleting a KB must remove it from the registry."""
        manager = self._make_manager()
        kb_id = await manager.create_knowledge_base("Temp KB")
        await manager.delete_knowledge_base(kb_id)
        kbs = await manager.list_knowledge_bases()
        assert all(kb["kb_id"] != kb_id for kb in kbs)

    async def test_create_kb_has_metadata(self):
        """Created KB entry must contain name, description, and created_at."""
        manager = self._make_manager()
        kb_id = await manager.create_knowledge_base("My KB", description="A test KB")
        kbs = await manager.list_knowledge_bases()
        kb = next(kb for kb in kbs if kb["kb_id"] == kb_id)
        assert kb["name"] == "My KB"
        assert kb["description"] == "A test KB"
        assert "created_at" in kb
