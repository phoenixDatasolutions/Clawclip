"""Embedding providers for the NexusAI RAG Knowledge Base module.

Supports OpenAI, Ollama (local inference server), and sentence-transformers
(fully local). All providers conform to the EmbeddingProvider Protocol so they
are interchangeable at runtime.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ── Optional heavy dependencies ──────────────────────────────────

try:
    import openai as _openai_module
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False

try:
    from sentence_transformers import SentenceTransformer as _SentenceTransformer
    _HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    _HAS_SENTENCE_TRANSFORMERS = False

try:
    import httpx as _httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False


# ── Protocol ─────────────────────────────────────────────────────


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Interface every embedding backend must satisfy."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        ...

    @property
    def dimension(self) -> int:
        """Dimensionality of the produced embedding vectors."""
        ...


# ── OpenAI ───────────────────────────────────────────────────────


class OpenAIEmbeddings:
    """Embeddings via the OpenAI API (text-embedding-3-small, 1536-dim)."""

    _DIMENSION = 1536

    def __init__(self, api_key: str | None = None, model: str = "text-embedding-3-small") -> None:
        if not _HAS_OPENAI:
            raise ImportError(
                "openai package is required for OpenAIEmbeddings. "
                "Install it with: pip install openai"
            )
        self._model = model
        self._client = _openai_module.AsyncOpenAI(api_key=api_key)

    @property
    def dimension(self) -> int:
        return self._DIMENSION

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        logger.debug("OpenAIEmbeddings.embed: %d texts", len(texts))
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
        )
        return [item.embedding for item in response.data]


# ── Ollama ───────────────────────────────────────────────────────


class OllamaEmbeddings:
    """Embeddings via a local Ollama inference server.

    Sends POST requests to ``http://localhost:11434/api/embeddings`` (or the
    configured base URL) for each text individually, as the Ollama API does not
    support batch embedding natively.
    """

    def __init__(
        self,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
    ) -> None:
        if not _HAS_HTTPX:
            raise ImportError(
                "httpx package is required for OllamaEmbeddings. "
                "Install it with: pip install httpx"
            )
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._dimension: int | None = None  # discovered on first call

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            raise RuntimeError(
                "Dimension not yet known — call embed() at least once first."
            )
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        logger.debug("OllamaEmbeddings.embed: %d texts via %s", len(texts), self._base_url)
        url = f"{self._base_url}/api/embeddings"
        embeddings: list[list[float]] = []
        async with _httpx.AsyncClient(timeout=60.0) as client:
            for text in texts:
                payload = {"model": self._model, "prompt": text}
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                vec: list[float] = data["embedding"]
                embeddings.append(vec)
                if self._dimension is None:
                    self._dimension = len(vec)
        return embeddings


# ── Local (sentence-transformers) ────────────────────────────────


class LocalEmbeddings:
    """Fully local embeddings using the sentence-transformers library.

    Downloads the model on first use if not already cached.
    """

    def __init__(self, model: str = "all-MiniLM-L6-v2") -> None:
        if not _HAS_SENTENCE_TRANSFORMERS:
            raise ImportError(
                "sentence-transformers package is required for LocalEmbeddings. "
                "Install it with: pip install sentence-transformers"
            )
        logger.info("Loading sentence-transformer model: %s", model)
        self._model_name = model
        self._st = _SentenceTransformer(model)

    @property
    def dimension(self) -> int:
        return int(self._st.get_sentence_embedding_dimension())

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        logger.debug("LocalEmbeddings.embed: %d texts", len(texts))
        # SentenceTransformer.encode is synchronous; run inline (CPU-bound but
        # acceptable for moderate batch sizes; callers can wrap in executor if needed).
        vectors = self._st.encode(texts, convert_to_numpy=True)
        return [v.tolist() for v in vectors]


# ── Factory ──────────────────────────────────────────────────────


def create_embedding_provider(config: dict[str, Any]) -> EmbeddingProvider:
    """Create an :class:`EmbeddingProvider` from a configuration dictionary.

    Expected keys:

    - ``provider``: ``"openai"`` | ``"ollama"`` | ``"local"``
    - ``model`` *(optional)*: model name / path
    - ``api_key`` *(optional)*: API key (OpenAI only)
    - ``base_url`` *(optional)*: server URL (Ollama only)
    """
    provider = config.get("provider", "local").lower()
    model: str | None = config.get("model")
    api_key: str | None = config.get("api_key")

    if provider == "openai":
        kwargs: dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        if model:
            kwargs["model"] = model
        return OpenAIEmbeddings(**kwargs)

    if provider == "ollama":
        kwargs = {}
        if model:
            kwargs["model"] = model
        base_url = config.get("base_url")
        if base_url:
            kwargs["base_url"] = base_url
        return OllamaEmbeddings(**kwargs)

    if provider == "local":
        kwargs = {}
        if model:
            kwargs["model"] = model
        return LocalEmbeddings(**kwargs)

    raise ValueError(
        f"Unknown embedding provider: {provider!r}. "
        "Choose from: 'openai', 'ollama', 'local'."
    )
