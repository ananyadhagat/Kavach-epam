"""Construction seam for the four core comparators.

The internal ``DuplicateDetectionService`` uses this module for its default
comparator wiring; comparators are otherwise instantiated ad hoc. It exists so
the text backend can be selected **once**, keeping exactly one ``text`` signal:

* ``text_backend="embedding"`` (default) -> semantic
  :class:`~app.comparators.embedding_text_comparator.EmbeddingTextComparator`;
* ``text_backend="tfidf"`` -> lexical
  :class:`~app.comparators.text_comparator.TextComparator` retained as the
  baseline/fallback.

Location, category and time comparators are unchanged and are always built from
the same configuration values they used before. This module does not score,
decide, retrieve candidates or persist anything.
"""

from __future__ import annotations

from app.comparators.base import Comparator
from app.comparators.category_comparator import CategoryComparator
from app.comparators.embedding_text_comparator import EmbeddingTextComparator
from app.comparators.location_comparator import LocationComparator
from app.comparators.text_comparator import TextComparator
from app.comparators.time_comparator import TimeComparator
from app.config.settings import DEFAULT_SETTINGS, Settings


def build_text_comparator(settings: Settings | None = None) -> Comparator:
    """Build exactly one text comparator for the configured backend.

    The returned comparator always has ``name == "text"``; callers must not
    combine it with another text comparator, because TF-IDF and embeddings are
    alternative measurements of the same evidence, not independent signals.
    """

    resolved = DEFAULT_SETTINGS if settings is None else settings
    config = resolved.comparators

    if config.text_backend == "tfidf":
        return TextComparator()
    return EmbeddingTextComparator(model_name=config.embedding_model)


def build_core_comparators(settings: Settings | None = None) -> dict[str, Comparator]:
    """Build the four core comparators keyed by their canonical signal name.

    The mapping can be passed through a loop to produce ``SignalResult`` values
    for :class:`~app.scoring.engine.WeightedScoringEngine`. The text backend is
    resolved once by :func:`build_text_comparator`.
    """

    resolved = DEFAULT_SETTINGS if settings is None else settings
    config = resolved.comparators

    return {
        "text": build_text_comparator(resolved),
        "location": LocationComparator(
            distance_scale_m=config.location_distance_scale_m,
        ),
        "category": CategoryComparator(
            compatibility_map=config.category_map,
            compatible_score=config.category_compatible_score,
        ),
        "time": TimeComparator(
            decay_scale_seconds=config.time_decay_scale_seconds,
        ),
    }


__all__ = ["build_core_comparators", "build_text_comparator"]
