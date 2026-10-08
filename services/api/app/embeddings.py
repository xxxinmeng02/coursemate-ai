"""Embedding provider boundary and the identity of its vector space.

No database, router, parsing, or chunking dependencies belong here.
"""
from dataclasses import dataclass
import math
from numbers import Real
import os
import re
import struct

import httpx

EMBEDDING_DIMENSIONS = 1536
SUPPORTED_MODELS = {"text-embedding-3-small", "text-embedding-3-large"}


class EmbeddingError(RuntimeError):
    """Safe embedding error; provider payloads/secrets must not escape here."""


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str = "text-embedding-3-small"
    revision: str = "v1"

    def __post_init__(self) -> None:
        if self.model not in SUPPORTED_MODELS:
            raise EmbeddingError("Unsupported embedding model")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", self.revision):
            raise EmbeddingError("Invalid embedding revision")

    @property
    def identifier(self) -> str:
        return f"openai:{self.model}:{EMBEDDING_DIMENSIONS}:{self.revision}"


def get_embedding_config() -> EmbeddingConfig:
    return EmbeddingConfig(
        model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        revision=os.getenv("EMBEDDING_REVISION", "v1"),
    )


def validate_embedding(vector: list[float]) -> list[float]:
    """Validate actual float32 storage values, including under/overflow."""
    try:
        if len(vector) != EMBEDDING_DIMENSIONS:
            raise ValueError
        stored = []
        for value in vector:
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError
            number = float(value)
            if not math.isfinite(number):
                raise ValueError
            rounded = struct.unpack("f", struct.pack("f", number))[0]
            if not math.isfinite(rounded):
                raise ValueError
            stored.append(rounded)
        if not any(stored):
            raise ValueError
        return stored
    except (TypeError, ValueError, OverflowError, struct.error):
        raise EmbeddingError("Invalid embedding vector") from None


def embed_text(text: str, *, config: EmbeddingConfig | None = None) -> list[float]:
    """Embed one nonblank text in a captured, fixed-dimensional vector space."""
    if not isinstance(text, str) or not text.strip():
        raise EmbeddingError("Embedding input must not be blank")
    config = config or get_embedding_config()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise EmbeddingError("Embedding provider is not configured")
    try:
        response = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"input": text, "model": config.model,
                  "dimensions": EMBEDDING_DIMENSIONS, "encoding_format": "float"},
            timeout=30.0,
        )
        response.raise_for_status()
        return validate_embedding(response.json()["data"][0]["embedding"])
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, EmbeddingError):
        # Do not chain or log exceptions: HTTP errors can contain provider bodies.
        raise EmbeddingError("Could not generate embedding") from None
