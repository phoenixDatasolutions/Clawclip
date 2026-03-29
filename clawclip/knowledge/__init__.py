"""ClawClip RAG Knowledge Base module.

Provides a high-level :class:`KnowledgeManager` that wraps document loading,
chunking, embedding, vector-store persistence, and similarity retrieval.

Quick-start
-----------
::

    from clawclip.knowledge import KnowledgeManager
    from clawclip.knowledge.embeddings import create_embedding_provider
    from clawclip.knowledge.vectorstore import create_vector_store
    from clawclip.knowledge.indexer import DocumentIndexer
    from clawclip.knowledge.retriever import Retriever

    store = create_vector_store({"backend": "memory"})
    embedder = create_embedding_provider({"provider": "local"})
    indexer = DocumentIndexer(store, embedder)
    retriever = Retriever(store, embedder)
    manager = KnowledgeManager(indexer, retriever)
"""

from __future__ import annotations

from clawclip.knowledge.manager import KnowledgeManager

__all__ = ["KnowledgeManager"]
