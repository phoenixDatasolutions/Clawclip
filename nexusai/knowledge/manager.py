"""High-level KnowledgeManager for the NexusAI RAG Knowledge Base module.

Provides CRUD operations on named knowledge bases and delegates the heavy
lifting to :class:`~nexusai.knowledge.indexer.DocumentIndexer` and
:class:`~nexusai.knowledge.retriever.Retriever`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from nexusai.core.types import DocumentChunkResult
from nexusai.knowledge.indexer import DocumentIndexer
from nexusai.knowledge.retriever import Retriever

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeManager:
    """High-level interface for managing knowledge bases.

    Parameters
    ----------
    indexer:
        :class:`~nexusai.knowledge.indexer.DocumentIndexer` instance used
        to index new content.
    retriever:
        :class:`~nexusai.knowledge.retriever.Retriever` instance used to
        search existing content.
    """

    def __init__(
        self,
        indexer: DocumentIndexer,
        retriever: Retriever,
    ) -> None:
        self._indexer = indexer
        self._retriever = retriever
        # In-process registry: kb_id -> {name, description, created_at, ...}
        self._registry: dict[str, dict[str, Any]] = {}

    # ── Knowledge base lifecycle ──────────────────────────────────

    async def create_knowledge_base(
        self,
        name: str,
        description: str = "",
    ) -> str:
        """Create a new knowledge base and return its ID.

        Parameters
        ----------
        name:
            Human-readable name for the knowledge base.
        description:
            Optional description.

        Returns
        -------
        str
            Unique knowledge base ID (UUID-4).
        """
        kb_id = str(uuid.uuid4())
        self._registry[kb_id] = {
            "kb_id": kb_id,
            "name": name,
            "description": description,
            "created_at": _utcnow_iso(),
            "chunk_count": 0,
        }
        logger.info("KnowledgeManager: created kb id=%s name=%r", kb_id, name)
        return kb_id

    async def delete_knowledge_base(self, kb_id: str) -> None:
        """Delete a knowledge base and all its indexed content.

        Parameters
        ----------
        kb_id:
            ID returned by :meth:`create_knowledge_base`.
        """
        if kb_id not in self._registry:
            logger.warning("KnowledgeManager.delete_knowledge_base: unknown kb_id=%s", kb_id)
        await self._indexer.delete_documents(kb_id)
        self._registry.pop(kb_id, None)
        logger.info("KnowledgeManager: deleted kb_id=%s", kb_id)

    async def list_knowledge_bases(self) -> list[dict[str, Any]]:
        """Return metadata for all registered knowledge bases.

        Returns
        -------
        list of dicts with keys: ``kb_id``, ``name``, ``description``,
        ``created_at``, ``chunk_count``.
        """
        return list(self._registry.values())

    # ── Content ingestion ─────────────────────────────────────────

    def _ensure_kb(self, kb_id: str) -> None:
        if kb_id not in self._registry:
            raise ValueError(
                f"Knowledge base {kb_id!r} not found. "
                "Create it first with create_knowledge_base()."
            )

    def _increment_chunks(self, kb_id: str, count: int) -> None:
        if kb_id in self._registry:
            self._registry[kb_id]["chunk_count"] = (
                self._registry[kb_id].get("chunk_count", 0) + count
            )

    async def add_file(self, kb_id: str, file_path: str) -> int:
        """Index a single file into *kb_id*.

        Returns
        -------
        int
            Number of chunks indexed.
        """
        self._ensure_kb(kb_id)
        logger.info("KnowledgeManager.add_file: kb=%s path=%s", kb_id, file_path)
        count = await self._indexer.index_file(file_path, kb_id)
        self._increment_chunks(kb_id, count)
        return count

    async def add_directory(self, kb_id: str, dir_path: str) -> int:
        """Recursively index all supported files in *dir_path*.

        Returns
        -------
        int
            Number of chunks indexed.
        """
        self._ensure_kb(kb_id)
        logger.info("KnowledgeManager.add_directory: kb=%s path=%s", kb_id, dir_path)
        count = await self._indexer.index_directory(dir_path, kb_id)
        self._increment_chunks(kb_id, count)
        return count

    async def add_url(self, kb_id: str, url: str) -> int:
        """Fetch a web page and index its content.

        Returns
        -------
        int
            Number of chunks indexed.
        """
        self._ensure_kb(kb_id)
        from nexusai.knowledge.loaders.web_loader import load_url

        logger.info("KnowledgeManager.add_url: kb=%s url=%s", kb_id, url)
        doc = await load_url(url)
        if not doc:
            logger.warning("KnowledgeManager.add_url: no content from %s", url)
            return 0
        count = await self._indexer.index_documents([doc], kb_id)
        self._increment_chunks(kb_id, count)
        return count

    async def add_git_repo(self, kb_id: str, repo_path: str) -> int:
        """Index all tracked files in a git repository.

        Returns
        -------
        int
            Number of chunks indexed.
        """
        self._ensure_kb(kb_id)
        from nexusai.knowledge.loaders.git_loader import load_repo

        logger.info("KnowledgeManager.add_git_repo: kb=%s path=%s", kb_id, repo_path)
        documents = await load_repo(repo_path)
        count = await self._indexer.index_documents(documents, kb_id)
        self._increment_chunks(kb_id, count)
        return count

    # ── Retrieval ─────────────────────────────────────────────────

    async def search(
        self,
        kb_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[DocumentChunkResult]:
        """Search a specific knowledge base.

        Parameters
        ----------
        kb_id:
            Knowledge base to search.
        query:
            Natural-language query string.
        top_k:
            Maximum results to return.

        Returns
        -------
        list of :class:`~nexusai.core.types.DocumentChunkResult`
        """
        self._ensure_kb(kb_id)
        return await self._retriever.search(
            query=query,
            knowledge_base_id=kb_id,
            top_k=top_k,
        )

    async def get_context_for_query(
        self,
        query: str,
        kb_ids: list[str] | None = None,
        top_k: int = 5,
    ) -> str:
        """Return a formatted context string by searching one or more knowledge bases.

        When *kb_ids* is ``None`` all registered knowledge bases are searched
        and results are merged and re-ranked by score.

        Parameters
        ----------
        query:
            Natural-language question or statement.
        kb_ids:
            Specific knowledge base IDs to search, or ``None`` for all.
        top_k:
            Maximum results to include in the context.

        Returns
        -------
        str
            Formatted context block ready for LLM injection, or empty string
            if nothing relevant was found.
        """
        target_ids: list[str] = kb_ids if kb_ids is not None else list(self._registry.keys())
        if not target_ids:
            return ""

        # Fan out searches across all target KBs concurrently.
        search_tasks = [
            self._retriever.search(query=query, knowledge_base_id=kb_id, top_k=top_k)
            for kb_id in target_ids
        ]
        all_results_nested: list[Any] = await asyncio.gather(
            *search_tasks, return_exceptions=True
        )

        merged: list[DocumentChunkResult] = []
        for kb_id, result in zip(target_ids, all_results_nested):
            if isinstance(result, Exception):
                logger.error(
                    "KnowledgeManager.get_context_for_query: search failed for kb=%s: %s",
                    kb_id,
                    result,
                )
                continue
            merged.extend(result)

        if not merged:
            return ""

        # Re-rank by score and keep top_k.
        merged.sort(key=lambda r: r.score, reverse=True)
        top_results = merged[:top_k]

        # Format.
        parts: list[str] = ["Relevant context from knowledge base:\n"]
        for i, chunk in enumerate(top_results, start=1):
            source = chunk.source or chunk.metadata.get("file_path", "unknown")
            kb_name = ""
            kb_id_meta = chunk.metadata.get("knowledge_base_id", "")
            if kb_id_meta and kb_id_meta in self._registry:
                kb_name = f" [{self._registry[kb_id_meta]['name']}]"
            score_pct = f"{chunk.score * 100:.1f}%"
            parts.append(f"[{i}] Source: {source}{kb_name} (relevance: {score_pct})")
            parts.append(chunk.content.strip())
            parts.append("")

        return "\n".join(parts).strip()
