"""Vector store backends for the ClawClip RAG Knowledge Base module.

Provides two implementations:

- :class:`ChromaDBStore` — persistent store backed by ChromaDB.
- :class:`InMemoryStore` — pure-Python cosine-similarity store (no deps,
  ideal for development and testing).

Both conform to the :class:`VectorStore` Protocol.
"""

from __future__ import annotations

import logging
import math
import uuid
from typing import Any, Protocol, runtime_checkable

from clawclip.core.types import DocumentChunkResult

logger = logging.getLogger(__name__)

# ── Optional dependency: chromadb ────────────────────────────────

try:
    import chromadb as _chromadb
    _HAS_CHROMADB = True
except ImportError:
    _HAS_CHROMADB = False


# ── Protocol ─────────────────────────────────────────────────────


@runtime_checkable
class VectorStore(Protocol):
    """Interface every vector store backend must satisfy."""

    async def add(
        self,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Persist a batch of embedded document chunks."""
        ...

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[DocumentChunkResult]:
        """Return the *top_k* most similar chunks for *query_embedding*."""
        ...

    async def delete(self, ids: list[str]) -> None:
        """Remove chunks by their IDs."""
        ...

    async def clear(self) -> None:
        """Remove all chunks from the store."""
        ...


# ── ChromaDB ─────────────────────────────────────────────────────


class ChromaDBStore:
    """Persistent vector store backed by ChromaDB.

    Parameters
    ----------
    collection_name:
        Name of the ChromaDB collection to use / create.
    persist_dir:
        Directory on disk where ChromaDB persists its data.
    """

    def __init__(
        self,
        collection_name: str,
        persist_dir: str = "./data/chroma",
    ) -> None:
        if not _HAS_CHROMADB:
            raise ImportError(
                "chromadb package is required for ChromaDBStore. "
                "Install it with: pip install chromadb"
            )
        self._collection_name = collection_name
        self._persist_dir = persist_dir
        self._client = _chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "ChromaDBStore initialised: collection=%s persist_dir=%s",
            collection_name,
            persist_dir,
        )

    async def add(
        self,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        if not ids:
            return
        logger.debug("ChromaDBStore.add: %d chunks", len(ids))
        # ChromaDB requires metadata values to be str/int/float/bool.
        safe_metas = [_sanitise_metadata(m) for m in metadatas]
        self._collection.upsert(
            ids=ids,
            documents=texts,
            embeddings=embeddings,
            metadatas=safe_metas,
        )

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[DocumentChunkResult]:
        logger.debug("ChromaDBStore.search: top_k=%d", top_k)
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        chunks: list[DocumentChunkResult] = []
        ids = results.get("ids", [[]])[0]
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        for chunk_id, doc, meta, dist in zip(ids, documents, metadatas, distances):
            # ChromaDB returns L2/cosine distance; convert to similarity score.
            score = max(0.0, 1.0 - float(dist))
            chunks.append(
                DocumentChunkResult(
                    chunk_id=chunk_id,
                    document_id=str(meta.get("document_id", "")),
                    content=doc or "",
                    metadata=dict(meta),
                    score=score,
                    source=str(meta.get("source", "")),
                )
            )
        return chunks

    async def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        logger.debug("ChromaDBStore.delete: %d ids", len(ids))
        self._collection.delete(ids=ids)

    async def clear(self) -> None:
        logger.info("ChromaDBStore.clear: deleting collection %s", self._collection_name)
        self._client.delete_collection(self._collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )


# ── In-Memory ────────────────────────────────────────────────────


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return the cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryStore:
    """Pure-Python in-memory vector store using cosine similarity.

    No external dependencies. Intended for development and testing; all data
    is lost when the process exits.
    """

    def __init__(self) -> None:
        # id -> (text, embedding, metadata)
        self._store: dict[str, tuple[str, list[float], dict[str, Any]]] = {}
        logger.info("InMemoryStore initialised")

    async def add(
        self,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        for chunk_id, text, embedding, metadata in zip(ids, texts, embeddings, metadatas):
            self._store[chunk_id] = (text, embedding, metadata)
        logger.debug("InMemoryStore.add: store size now %d", len(self._store))

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[DocumentChunkResult]:
        if not self._store:
            return []
        scored: list[tuple[float, str, str, dict[str, Any]]] = []
        for chunk_id, (text, embedding, metadata) in self._store.items():
            score = _cosine_similarity(query_embedding, embedding)
            scored.append((score, chunk_id, text, metadata))
        scored.sort(key=lambda x: x[0], reverse=True)
        results: list[DocumentChunkResult] = []
        for score, chunk_id, text, metadata in scored[:top_k]:
            results.append(
                DocumentChunkResult(
                    chunk_id=chunk_id,
                    document_id=str(metadata.get("document_id", "")),
                    content=text,
                    metadata=metadata,
                    score=score,
                    source=str(metadata.get("source", "")),
                )
            )
        return results

    async def delete(self, ids: list[str]) -> None:
        for chunk_id in ids:
            self._store.pop(chunk_id, None)
        logger.debug("InMemoryStore.delete: store size now %d", len(self._store))

    async def clear(self) -> None:
        self._store.clear()
        logger.info("InMemoryStore.clear: all chunks removed")


# ── Helpers ──────────────────────────────────────────────────────


def _sanitise_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Flatten metadata to ChromaDB-compatible scalar types."""
    safe: dict[str, Any] = {}
    for k, v in meta.items():
        if isinstance(v, (str, int, float, bool)):
            safe[k] = v
        elif v is None:
            safe[k] = ""
        else:
            safe[k] = str(v)
    return safe


# ── Factory ──────────────────────────────────────────────────────


def create_vector_store(config: dict[str, Any]) -> VectorStore:
    """Create a :class:`VectorStore` from a configuration dictionary.

    Expected keys:

    - ``backend``: ``"chromadb"`` | ``"memory"``
    - ``collection_name`` *(optional, chromadb)*
    - ``persist_dir`` *(optional, chromadb)*
    """
    backend = config.get("backend", "memory").lower()

    if backend == "chromadb":
        kwargs: dict[str, Any] = {}
        collection_name = config.get("collection_name", "clawclip_knowledge")
        kwargs["collection_name"] = collection_name
        persist_dir = config.get("persist_dir")
        if persist_dir:
            kwargs["persist_dir"] = persist_dir
        return ChromaDBStore(**kwargs)

    if backend == "memory":
        return InMemoryStore()

    raise ValueError(
        f"Unknown vector store backend: {backend!r}. "
        "Choose from: 'chromadb', 'memory'."
    )
