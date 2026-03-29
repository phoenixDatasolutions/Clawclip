"""Vector store backends for the ClawClip RAG Knowledge Base module.

Provides four implementations:

- :class:`ChromaDBStore` — persistent store backed by ChromaDB.
- :class:`InMemoryStore` — pure-Python cosine-similarity store (no deps,
  ideal for development and testing).
- :class:`PineconeVectorStore` — cloud-hosted store backed by Pinecone.
- :class:`WeaviateVectorStore` — self-hosted or cloud store backed by Weaviate.

All four conform to the :class:`VectorStore` Protocol.
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

# ── Optional dependency: pinecone ────────────────────────────────

try:
    from pinecone import Pinecone as _Pinecone  # pinecone-client >= 3
    _HAS_PINECONE = True
except ImportError:
    _HAS_PINECONE = False

# ── Optional dependency: weaviate ────────────────────────────────

try:
    import weaviate as _weaviate  # weaviate-client >= 4
    _HAS_WEAVIATE = True
except ImportError:
    _HAS_WEAVIATE = False


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


# ── Pinecone ─────────────────────────────────────────────────────


class PineconeVectorStore:
    """Cloud-hosted vector store backed by Pinecone.

    Parameters
    ----------
    api_key:
        Pinecone API key.
    index_name:
        Name of the target Pinecone index (must already exist).
    environment:
        Pinecone environment string (legacy gcp-starter accounts).
        Ignored for serverless indexes — pass an empty string.
    """

    def __init__(
        self,
        api_key: str,
        index_name: str,
        environment: str = "gcp-starter",
    ) -> None:
        if not _HAS_PINECONE:
            raise ImportError(
                "pinecone-client package is required for PineconeVectorStore. "
                "Install it with: pip install 'pinecone-client>=3.0,<4'"
            )
        self._index_name = index_name
        pc = _Pinecone(api_key=api_key)
        self._index = pc.Index(index_name)
        logger.info("PineconeVectorStore initialised: index=%s", index_name)

    async def add(
        self,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        if not ids:
            return
        logger.debug("PineconeVectorStore.add: %d chunks", len(ids))
        vectors = []
        for chunk_id, embedding, meta, text in zip(ids, embeddings, metadatas, texts):
            safe_meta = _sanitise_metadata(meta)
            safe_meta["_text"] = text  # store text in metadata for retrieval
            vectors.append({"id": chunk_id, "values": embedding, "metadata": safe_meta})
        # Upsert in batches of 100 (Pinecone limit)
        batch_size = 100
        for i in range(0, len(vectors), batch_size):
            self._index.upsert(vectors=vectors[i : i + batch_size])

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[DocumentChunkResult]:
        logger.debug("PineconeVectorStore.search: top_k=%d", top_k)
        response = self._index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True,
        )
        results: list[DocumentChunkResult] = []
        for match in response.get("matches", []):
            meta = dict(match.get("metadata", {}))
            text = str(meta.pop("_text", ""))
            score = float(match.get("score", 0.0))
            results.append(
                DocumentChunkResult(
                    chunk_id=str(match.get("id", "")),
                    document_id=str(meta.get("document_id", "")),
                    content=text,
                    metadata=meta,
                    score=score,
                    source=str(meta.get("source", "")),
                )
            )
        return results

    async def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        logger.debug("PineconeVectorStore.delete: %d ids", len(ids))
        self._index.delete(ids=ids)

    async def clear(self) -> None:
        logger.info("PineconeVectorStore.clear: deleting all vectors in %s", self._index_name)
        self._index.delete(delete_all=True)

    async def count(self) -> int:
        stats = self._index.describe_index_stats()
        return int(stats.get("total_vector_count", 0))

    async def delete_document(self, document_id: str) -> None:
        """Delete all chunks that belong to *document_id*."""
        logger.debug("PineconeVectorStore.delete_document: %s", document_id)
        # Pinecone supports filter-based delete on paid tiers; fall back to a
        # metadata query + id delete for compatibility.
        response = self._index.query(
            vector=[0.0] * 1,  # dummy — we only care about filter
            top_k=10_000,
            filter={"document_id": {"$eq": document_id}},
            include_metadata=False,
        )
        ids = [m["id"] for m in response.get("matches", [])]
        if ids:
            self._index.delete(ids=ids)


# ── Weaviate ──────────────────────────────────────────────────────


class WeaviateVectorStore:
    """Self-hosted or cloud vector store backed by Weaviate.

    Parameters
    ----------
    url:
        Weaviate instance URL, e.g. ``http://localhost:8080``.
    api_key:
        Optional Weaviate API key (for Weaviate Cloud Services).
    class_name:
        Weaviate class (collection) to use; created if it does not exist.
    """

    def __init__(
        self,
        url: str = "http://localhost:8080",
        api_key: str = "",
        class_name: str = "ClawClipDoc",
    ) -> None:
        if not _HAS_WEAVIATE:
            raise ImportError(
                "weaviate-client package is required for WeaviateVectorStore. "
                "Install it with: pip install 'weaviate-client>=4.0,<5'"
            )
        self._class_name = class_name
        auth = _weaviate.auth.AuthApiKey(api_key) if api_key else None
        self._client = _weaviate.connect_to_custom(
            http_host=url.split("://", 1)[-1].split(":")[0],
            http_port=int(url.split(":")[-1]) if ":" in url.split("://", 1)[-1] else 8080,
            http_secure=url.startswith("https"),
            grpc_host=url.split("://", 1)[-1].split(":")[0],
            grpc_port=50051,
            grpc_secure=False,
            auth_credentials=auth,
        )
        self._collection = self._client.collections.get_or_create(
            name=class_name,
            vectorizer_config=_weaviate.classes.config.Configure.Vectorizer.none(),
        )
        logger.info("WeaviateVectorStore initialised: class=%s url=%s", class_name, url)

    async def add(
        self,
        ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        if not ids:
            return
        logger.debug("WeaviateVectorStore.add: %d chunks", len(ids))
        from weaviate.classes.data import DataObject
        objects = []
        for chunk_id, text, embedding, meta in zip(ids, texts, embeddings, metadatas):
            props = _sanitise_metadata(meta)
            props["_text"] = text
            props["chunk_id"] = chunk_id
            objects.append(
                DataObject(
                    properties=props,
                    vector=embedding,
                    uuid=_uuid_from_id(chunk_id),
                )
            )
        self._collection.data.insert_many(objects)

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[DocumentChunkResult]:
        logger.debug("WeaviateVectorStore.search: top_k=%d", top_k)
        from weaviate.classes.query import MetadataQuery
        response = self._collection.query.near_vector(
            near_vector=query_embedding,
            limit=top_k,
            return_metadata=MetadataQuery(distance=True),
        )
        results: list[DocumentChunkResult] = []
        for obj in response.objects:
            props = dict(obj.properties)
            text = str(props.pop("_text", ""))
            chunk_id = str(props.pop("chunk_id", str(obj.uuid)))
            distance = float(obj.metadata.distance) if obj.metadata and obj.metadata.distance is not None else 1.0
            score = max(0.0, 1.0 - distance)
            results.append(
                DocumentChunkResult(
                    chunk_id=chunk_id,
                    document_id=str(props.get("document_id", "")),
                    content=text,
                    metadata=props,
                    score=score,
                    source=str(props.get("source", "")),
                )
            )
        return results

    async def delete(self, ids: list[str]) -> None:
        if not ids:
            return
        logger.debug("WeaviateVectorStore.delete: %d ids", len(ids))
        for chunk_id in ids:
            self._collection.data.delete_by_id(_uuid_from_id(chunk_id))

    async def clear(self) -> None:
        logger.info("WeaviateVectorStore.clear: deleting class %s", self._class_name)
        self._client.collections.delete(self._class_name)
        from weaviate.classes.config import Configure
        self._collection = self._client.collections.get_or_create(
            name=self._class_name,
            vectorizer_config=Configure.Vectorizer.none(),
        )

    async def count(self) -> int:
        agg = self._collection.aggregate.over_all(total_count=True)
        return int(agg.total_count or 0)

    async def delete_document(self, document_id: str) -> None:
        """Delete all chunks that belong to *document_id*."""
        logger.debug("WeaviateVectorStore.delete_document: %s", document_id)
        from weaviate.classes.query import Filter
        self._collection.data.delete_many(
            where=Filter.by_property("document_id").equal(document_id)
        )


# ── Helpers ──────────────────────────────────────────────────────


def _uuid_from_id(chunk_id: str) -> str:
    """Derive a deterministic UUID from an arbitrary string chunk_id."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk_id))


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

    - ``backend``: ``"chromadb"`` | ``"memory"`` | ``"pinecone"`` | ``"weaviate"``

    **ChromaDB keys** *(optional)*:

    - ``collection_name``
    - ``persist_dir``

    **Pinecone keys**:

    - ``api_key`` *(required)*
    - ``index_name`` *(required)*
    - ``environment`` *(optional, default* ``"gcp-starter"`` *)*

    **Weaviate keys** *(optional)*:

    - ``url`` *(default* ``"http://localhost:8080"`` *)*
    - ``api_key``
    - ``class_name`` *(default* ``"ClawClipDoc"`` *)*
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

    if backend == "pinecone":
        return PineconeVectorStore(
            api_key=config["api_key"],
            index_name=config["index_name"],
            environment=config.get("environment", "gcp-starter"),
        )

    if backend == "weaviate":
        return WeaviateVectorStore(
            url=config.get("url", "http://localhost:8080"),
            api_key=config.get("api_key", ""),
            class_name=config.get("class_name", "ClawClipDoc"),
        )

    raise ValueError(
        f"Unknown vector store backend: {backend!r}. "
        "Choose from: 'chromadb', 'memory', 'pinecone', 'weaviate'."
    )
