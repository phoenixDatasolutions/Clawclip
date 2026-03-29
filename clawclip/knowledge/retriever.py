"""Retriever for the ClawClip RAG Knowledge Base module.

Performs similarity search against the configured vector store and
formats results as context strings suitable for injection into LLM prompts.
"""

from __future__ import annotations

import logging
from typing import Any

from clawclip.core.types import DocumentChunkResult
from clawclip.knowledge.embeddings import EmbeddingProvider
from clawclip.knowledge.vectorstore import VectorStore

logger = logging.getLogger(__name__)


class Retriever:
    """Search the vector store for chunks relevant to a query.

    Parameters
    ----------
    vector_store:
        The backend to search.
    embedding_provider:
        Provider used to embed the query string.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._store = vector_store
        self._embedder = embedding_provider

    async def search(
        self,
        query: str,
        knowledge_base_id: str | None = None,
        top_k: int = 5,
    ) -> list[DocumentChunkResult]:
        """Return the *top_k* most relevant chunks for *query*.

        Parameters
        ----------
        query:
            Natural-language question or statement to search for.
        knowledge_base_id:
            When provided, only chunks belonging to this knowledge base are
            returned (post-filter, since not all stores support where-filters).
        top_k:
            Maximum number of results to return.

        Returns
        -------
        list of :class:`~clawclip.core.types.DocumentChunkResult`
        """
        if not query.strip():
            return []

        logger.debug("Retriever.search: query=%r kb=%s top_k=%d", query, knowledge_base_id, top_k)

        # Retrieve more candidates when filtering by kb_id so we can still
        # return *top_k* results after the filter.
        fetch_k = top_k if knowledge_base_id is None else top_k * 4

        try:
            query_embedding = await self._embedder.embed([query])
        except Exception as exc:
            logger.error("Retriever.search: embedding failed: %s", exc)
            return []

        if not query_embedding:
            return []

        try:
            raw_results = await self._store.search(
                query_embedding=query_embedding[0],
                top_k=fetch_k,
            )
        except Exception as exc:
            logger.error("Retriever.search: vector store search failed: %s", exc)
            return []

        if knowledge_base_id is not None:
            raw_results = [
                r for r in raw_results
                if r.metadata.get("knowledge_base_id") == knowledge_base_id
            ]

        results = raw_results[:top_k]
        logger.debug("Retriever.search: returning %d results", len(results))
        return results

    async def search_and_format(
        self,
        query: str,
        top_k: int = 5,
        knowledge_base_id: str | None = None,
    ) -> str:
        """Search and return a formatted context string for LLM injection.

        The returned string lists each relevant chunk with its source and
        similarity score, ready to be placed in a system/user prompt.

        Returns
        -------
        str
            Formatted context block, or an empty string if no results found.
        """
        results = await self.search(
            query=query,
            knowledge_base_id=knowledge_base_id,
            top_k=top_k,
        )

        if not results:
            return ""

        parts: list[str] = ["Relevant context from knowledge base:\n"]
        for i, chunk in enumerate(results, start=1):
            source = chunk.source or chunk.metadata.get("file_path", "unknown")
            score_pct = f"{chunk.score * 100:.1f}%"
            parts.append(f"[{i}] Source: {source} (relevance: {score_pct})")
            parts.append(chunk.content.strip())
            parts.append("")  # blank separator

        return "\n".join(parts).strip()
