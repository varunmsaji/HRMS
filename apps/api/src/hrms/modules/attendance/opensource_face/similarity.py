"""Pure embedding maths - no OpenCV, no I/O, so thresholds and edge cases are unit-testable."""

import math
from collections.abc import Sequence
from decimal import Decimal

EMBEDDING_DIM = 128


class InvalidEmbeddingError(ValueError):
    """An embedding is the wrong length, non-finite, or has (near) zero norm."""


def normalise(vector: Sequence[float], *, dim: int = EMBEDDING_DIM) -> tuple[float, ...]:
    """L2-normalises `vector`; rejects anything that is not a finite `dim`-vector with a usable
    norm rather than letting a garbage model output turn into a similarity."""
    if len(vector) != dim:
        raise InvalidEmbeddingError("embedding has the wrong dimension")
    if not all(math.isfinite(v) for v in vector):
        raise InvalidEmbeddingError("embedding contains non-finite values")
    norm = math.sqrt(sum(v * v for v in vector))
    if norm < 1e-6:
        raise InvalidEmbeddingError("embedding has no magnitude")
    return tuple(v / norm for v in vector)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two already-normalised vectors, clamped to [-1, 1]."""
    if len(a) != len(b):
        raise InvalidEmbeddingError("embeddings differ in dimension")
    return max(-1.0, min(1.0, sum(x * y for x, y in zip(a, b, strict=True))))


def best_similarity(probe: Sequence[float], references: Sequence[Sequence[float]]) -> float:
    """Highest cosine between `probe` and any reference of ONE person (1:1 verification - never
    a search across people)."""
    if not references:
        raise InvalidEmbeddingError("no reference embeddings")
    return max(cosine(probe, ref) for ref in references)


def to_score(value: float) -> Decimal:
    """The 0..1, 4-decimal form stored in `face_verification_attempt.similarity` (NUMERIC(5,4)):
    negative cosines clamp to 0."""
    return Decimal(f"{min(max(value, 0.0), 1.0):.4f}")
