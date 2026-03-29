"""Document indexer for the NexusAI RAG Knowledge Base module.

Chunks raw documents, generates embeddings, and stores them in the configured
vector store.  Re-uses :class:`~nexusai.knowledge.loaders.file_loader` for
reading files/directories from disk.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from nexusai.knowledge.embeddings import EmbeddingProvider
from nexusai.knowledge.vectorstore import VectorStore

logger = logging.getLogger(__name__)


# ── DocumentIndexer ───────────────────────────────────────────────


class DocumentIndexer:
    """Chunk documents and store their embeddings in a vector store.

    Parameters
    ----------
    vector_store:
        Backend to persist embeddings.
    embedding_provider:
        Provider used to generate embedding vectors.
    chunk_size:
        Approximate maximum number of characters per chunk.
    chunk_overlap:
        Number of characters to overlap between consecutive chunks.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
    ) -> None:
        self._store = vector_store
        self._embedder = embedding_provider
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    # ── Chunking ──────────────────────────────────────────────────

    def _chunk_text(self, text: str) -> list[str]:
        """Split *text* into overlapping chunks of at most *chunk_size* chars.

        Strategy:
        1. Split on double-newline (paragraph) boundaries.
        2. If a paragraph exceeds *chunk_size*, split further on sentence
           boundaries (``[.!?]\\s``).
        3. Accumulate segments into chunks, adding *chunk_overlap* chars of
           the previous chunk at the start of each new one.
        """
        if not text:
            return []

        # Step 1 — paragraph splits.
        paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]

        # Step 2 — sentence splits for oversized paragraphs.
        segments: list[str] = []
        for para in paragraphs:
            if len(para) <= self._chunk_size:
                segments.append(para)
            else:
                # Split on sentence-ending punctuation followed by whitespace.
                sentences = re.split(r"(?<=[.!?])\s+", para)
                current = ""
                for sentence in sentences:
                    if len(current) + len(sentence) + 1 <= self._chunk_size:
                        current = f"{current} {sentence}".strip() if current else sentence
                    else:
                        if current:
                            segments.append(current)
                        # If a single sentence still exceeds chunk_size, hard-split.
                        if len(sentence) > self._chunk_size:
                            for i in range(0, len(sentence), self._chunk_size):
                                segments.append(sentence[i : i + self._chunk_size])
                        else:
                            current = sentence
                if current:
                    segments.append(current)

        if not segments:
            return []

        # Step 3 — accumulate into chunks with overlap.
        chunks: list[str] = []
        current_chunk = ""
        for seg in segments:
            if not current_chunk:
                current_chunk = seg
                continue
            candidate = current_chunk + "\n\n" + seg
            if len(candidate) <= self._chunk_size:
                current_chunk = candidate
            else:
                chunks.append(current_chunk)
                # Build overlap: take the tail of the previous chunk.
                overlap_text = current_chunk[-self._chunk_overlap :] if self._chunk_overlap else ""
                current_chunk = (overlap_text + "\n\n" + seg).strip() if overlap_text else seg
        if current_chunk:
            chunks.append(current_chunk)

        return [c for c in chunks if c.strip()]

    # ── Internal helpers ──────────────────────────────────────────

    def _make_chunk_id(self, knowledge_base_id: str, content: str, index: int) -> str:
        digest = hashlib.sha256(content.encode()).hexdigest()[:12]
        return f"{knowledge_base_id}:{digest}:{index}"

    async def _index_raw_documents(
        self,
        documents: list[dict[str, Any]],
        knowledge_base_id: str,
    ) -> int:
        """Chunk, embed, and store *documents*. Returns number of chunks indexed."""
        all_ids: list[str] = []
        all_texts: list[str] = []
        all_metas: list[dict[str, Any]] = []

        for doc in documents:
            content: str = doc.get("content", "")
            base_meta: dict[str, Any] = dict(doc.get("metadata", {}))
            base_meta["knowledge_base_id"] = knowledge_base_id
            base_meta["document_id"] = base_meta.get(
                "source", base_meta.get("file_path", base_meta.get("url", ""))
            )

            chunks = self._chunk_text(content)
            for idx, chunk in enumerate(chunks):
                chunk_id = self._make_chunk_id(knowledge_base_id, chunk, idx)
                meta = {**base_meta, "chunk_index": idx, "total_chunks": len(chunks)}
                all_ids.append(chunk_id)
                all_texts.append(chunk)
                all_metas.append(meta)

        if not all_ids:
            return 0

        logger.info(
            "DocumentIndexer: embedding %d chunks for kb=%s", len(all_ids), knowledge_base_id
        )
        embeddings = await self._embedder.embed(all_texts)

        await self._store.add(
            ids=all_ids,
            texts=all_texts,
            embeddings=embeddings,
            metadatas=all_metas,
        )
        logger.info(
            "DocumentIndexer: indexed %d chunks for kb=%s", len(all_ids), knowledge_base_id
        )
        return len(all_ids)

    # ── Public API ────────────────────────────────────────────────

    async def index_documents(
        self,
        documents: list[dict[str, Any]],
        knowledge_base_id: str,
    ) -> int:
        """Index a list of pre-loaded document dicts.

        Parameters
        ----------
        documents:
            Each element must have ``content`` (str) and ``metadata`` (dict).
        knowledge_base_id:
            Identifier for the knowledge base being populated.

        Returns
        -------
        int
            Number of chunks indexed.
        """
        return await self._index_raw_documents(documents, knowledge_base_id)

    async def index_file(self, path: str, knowledge_base_id: str) -> int:
        """Load *path* and index its content.

        Returns
        -------
        int
            Number of chunks indexed.
        """
        from nexusai.knowledge.loaders.file_loader import load_file

        documents = await load_file(path)
        return await self._index_raw_documents(documents, knowledge_base_id)

    async def index_directory(self, path: str, knowledge_base_id: str) -> int:
        """Recursively load all supported files under *path* and index them.

        Returns
        -------
        int
            Number of chunks indexed.
        """
        from nexusai.knowledge.loaders.file_loader import load_directory

        documents = await load_directory(path)
        return await self._index_raw_documents(documents, knowledge_base_id)

    async def delete_documents(self, knowledge_base_id: str) -> None:
        """Remove all chunks belonging to *knowledge_base_id*.

        .. note::
            For :class:`~nexusai.knowledge.vectorstore.InMemoryStore` and
            :class:`~nexusai.knowledge.vectorstore.ChromaDBStore` this uses
            a filtered delete based on the ``knowledge_base_id`` metadata
            field.  ChromaDB supports ``where`` filtering; for the in-memory
            store we delete by iterating stored IDs.
        """
        logger.info("DocumentIndexer.delete_documents: kb=%s", knowledge_base_id)
        # Attempt ChromaDB-style where-filter delete first.
        try:
            # Access the underlying ChromaDB collection if available.
            collection = getattr(self._store, "_collection", None)
            if collection is not None:
                collection.delete(
                    where={"knowledge_base_id": knowledge_base_id}
                )
                return
        except Exception as exc:
            logger.debug("ChromaDB where-delete failed, falling back: %s", exc)

        # Fallback: scan the in-memory store.
        inner_store = getattr(self._store, "_store", None)
        if inner_store is not None:
            ids_to_delete = [
                cid
                for cid, (_, _, meta) in list(inner_store.items())
                if meta.get("knowledge_base_id") == knowledge_base_id
            ]
            await self._store.delete(ids_to_delete)
            return

        logger.warning(
            "DocumentIndexer.delete_documents: could not delete by kb_id — "
            "falling back to full clear for store type %s",
            type(self._store).__name__,
        )
