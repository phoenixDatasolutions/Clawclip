"""NexusAI RAG Knowledge Base module.

Provides a high-level :class:`KnowledgeManager` that wraps document loading,
chunking, embedding, vector-store persistence, and similarity retrieval.

Quick-start
-----------
::

    from nexusai.knowledge import KnowledgeManager
    from nexusai.knowledge.embeddings import create_embedding_provider
    from nexusai.knowledge.vectorstore import create_vector_store
    from nexusai.knowledge.indexer import DocumentIndexer
    from nexusai.knowledge.retriever import Retriever

    store = create_vector_store({"backend": "memory"})
    embedder = create_embedding_provider({"provider": "local"})
    indexer = DocumentIndexer(store, embedder)
    retriever = Retriever(store, embedder)
    manager = KnowledgeManager(indexer, retriever)
"""

from __future__ import annotations

from nexusai.knowledge.manager import KnowledgeManager

__all__ = ["KnowledgeManager"]
