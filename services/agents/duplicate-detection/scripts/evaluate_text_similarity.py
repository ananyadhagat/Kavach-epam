"""Illustrative TF-IDF vs sentence-embedding evaluation for text evidence.

This script is **not** a production benchmark. It uses a small, hand-written,
synthetic set of labelled civic-complaint pairs because the repository has no
labelled duplicate dataset. Results are useful for relative comparison and for
exposing failure modes; they are not estimates of field accuracy.

The evaluation compares the two existing text backends on the *same* pairs:

* TF-IDF: :class:`app.comparators.text_comparator.TextComparator`
* Embeddings: :class:`app.comparators.embedding_text_comparator.EmbeddingTextComparator`
  with ``sentence-transformers/all-MiniLM-L6-v2`` by default.

It reports precision, recall, F1, false positives, a review-band proxy,
threshold-independent ROC-AUC / average precision, and per-pair scores. Run
from the repository root::

    python scripts/evaluate_text_similarity.py
    python scripts/evaluate_text_similarity.py --local-files-only
    python scripts/evaluate_text_similarity.py --json reports/eval.json \
        --markdown reports/eval.md

The model is downloaded on first use unless ``--local-files-only`` is passed and
the Hugging Face cache is already populated.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:  # Allow `python scripts/evaluate_text_similarity.py`.
    sys.path.insert(0, str(_ROOT))

from app.comparators.embedding_text_comparator import (  # noqa: E402
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingTextComparator,
)
from app.comparators.text_comparator import TextComparator  # noqa: E402
from app.schemas.duplicate_response import SignalStatus  # noqa: E402


@dataclass(frozen=True)
class Pair:
    text_a: str
    text_b: str
    label: int
    kind: str


@dataclass(frozen=True)
class Metrics:
    threshold: float
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    precision: float | None
    recall: float | None
    f1: float
    false_positive_rate: float
    review_rate: float


# --------------------------------------------------------------------------- #
# Synthetic labelled pairs (20 duplicate, 20 non-duplicate)
#
# The hard negatives deliberately share most of their wording but describe a
# different location, ward, block or entity. A text-only comparator cannot fully
# resolve them; that is a property of the evidence, not a bug in this script.
# --------------------------------------------------------------------------- #
PAIRS: tuple[Pair, ...] = (
    # -- paraphrases: same incident, little lexical overlap ------------------ #
    Pair(
        "The streetlight outside the central market is broken",
        "Lamp near the market gate is not working",
        1,
        "paraphrase_duplicate",
    ),
    Pair(
        "Garbage has not been collected for three days on MG Road",
        "Trash pile on MG Road has not been picked up in three days",
        1,
        "paraphrase_duplicate",
    ),
    Pair(
        "Water is leaking from a broken pipe near the school",
        "A burst pipe is flooding the road beside the school",
        1,
        "paraphrase_duplicate",
    ),
    Pair(
        "There is a large pothole on the main road damaging vehicles",
        "A big hole in the main road is damaging cars",
        1,
        "paraphrase_duplicate",
    ),
    Pair(
        "Construction waste has been dumped illegally behind the park",
        "Someone dumped construction debris behind the park",
        1,
        "paraphrase_duplicate",
    ),
    Pair(
        "The streetlight at the bus stop keeps flickering at night",
        "The lamp near the bus stop flickers after dark",
        1,
        "paraphrase_duplicate",
    ),
    Pair(
        "Sewage is overflowing onto the footpath near the temple",
        "Drain water is spilling onto the sidewalk near the temple",
        1,
        "paraphrase_duplicate",
    ),
    Pair(
        "Stray dogs are attacking children in the park",
        "Aggressive stray dogs are biting kids at the park",
        1,
        "paraphrase_duplicate",
    ),
    Pair(
        "The public toilet near the railway station is very dirty",
        "The restroom by the station is unclean",
        1,
        "paraphrase_duplicate",
    ),
    Pair(
        "A tree branch fell and is blocking the road",
        "A fallen tree is obstructing traffic on the road",
        1,
        "paraphrase_duplicate",
    ),
    Pair(
        "Residents have had no water supply since this morning",
        "There is no water in the neighborhood since morning",
        1,
        "paraphrase_duplicate",
    ),
    Pair(
        "The manhole cover on the street is broken and dangerous",
        "An open manhole on the road poses a danger",
        1,
        "paraphrase_duplicate",
    ),
    # -- near-duplicates with high lexical overlap -------------------------- #
    Pair(
        "Pothole near central market",
        "Large pothole near central market",
        1,
        "lexical_duplicate",
    ),
    Pair(
        "Garbage bins overflowing at the bus stand",
        "Garbage bins are overflowing at the bus stand",
        1,
        "lexical_duplicate",
    ),
    Pair(
        "Streetlight not working on 5th cross",
        "Streetlight on 5th Cross is not working",
        1,
        "lexical_duplicate",
    ),
    Pair(
        "Broken streetlight near north gate",
        "Broken street light near north gate",
        1,
        "lexical_duplicate",
    ),
    Pair(
        "Water pipe leaking near school",
        "Water pipe is leaking near the school",
        1,
        "lexical_duplicate",
    ),
    Pair(
        "Illegal dumping behind the park",
        "Illegal dumping of waste behind the park",
        1,
        "lexical_duplicate",
    ),
    Pair(
        "Sewage overflow near temple",
        "Sewage overflowing near the temple",
        1,
        "lexical_duplicate",
    ),
    Pair(
        "Stray dog bite in the park",
        "Stray dog bites in the park",
        1,
        "lexical_duplicate",
    ),
    # -- hard negatives: same issue, different place/entity ----------------- #
    Pair(
        "Streetlight is broken near the north gate",
        "Streetlight is broken near the south gate",
        0,
        "hard_negative",
    ),
    Pair(
        "Pothole on main road",
        "Pothole on market road",
        0,
        "hard_negative",
    ),
    Pair(
        "Garbage not collected at ward 5",
        "Garbage not collected at ward 9",
        0,
        "hard_negative",
    ),
    Pair(
        "Water leak near the school",
        "Water leak near the hospital",
        0,
        "hard_negative",
    ),
    Pair(
        "Broken streetlight reported on Monday",
        "Broken streetlight reported on Friday",
        0,
        "hard_negative",
    ),
    Pair(
        "Sewage overflow near the east temple",
        "Sewage overflow near the west temple",
        0,
        "hard_negative",
    ),
    Pair(
        "Stray dogs near the primary school",
        "Stray dogs near the high school",
        0,
        "hard_negative",
    ),
    Pair(
        "Pothole in front of house number 12",
        "Pothole in front of house number 21",
        0,
        "hard_negative",
    ),
    Pair(
        "Garbage bin overflowing on 1st cross",
        "Garbage bin overflowing on 4th cross",
        0,
        "hard_negative",
    ),
    Pair(
        "Water supply interrupted in block A",
        "Water supply interrupted in block B",
        0,
        "hard_negative",
    ),
    # -- easy negatives: different issue ----------------------------------- #
    Pair(
        "Broken streetlight near the market",
        "Garbage overflowing behind the market",
        0,
        "easy_negative",
    ),
    Pair(
        "Pothole on the highway",
        "Stray dog bite in the park",
        0,
        "easy_negative",
    ),
    Pair(
        "No water supply in the morning",
        "Streetlight flickering at night",
        0,
        "easy_negative",
    ),
    Pair(
        "Sewage overflow near the temple",
        "Illegal construction waste behind the park",
        0,
        "easy_negative",
    ),
    Pair(
        "Public toilet is dirty",
        "Broken manhole cover on the road",
        0,
        "easy_negative",
    ),
    Pair(
        "Fallen tree blocking traffic",
        "Loud music from a nearby bar",
        0,
        "easy_negative",
    ),
    Pair(
        "Illegal parking outside the school",
        "Garbage burning near the market",
        0,
        "easy_negative",
    ),
    Pair(
        "Mosquito breeding in stagnant water",
        "Streetlight not working at the bus stop",
        0,
        "easy_negative",
    ),
    Pair(
        "Overflowing drain on 2nd cross",
        "Damaged footpath near the park",
        0,
        "easy_negative",
    ),
    Pair(
        "Stray cattle on the main road",
        "Water pipe leaking near the school",
        0,
        "easy_negative",
    ),
)


def _score_pairs(comparator, pairs: tuple[Pair, ...]) -> list[float]:
    scores: list[float] = []
    for index, pair in enumerate(pairs, start=1):
        result = comparator.compare_texts(pair.text_a, pair.text_b)
        if result.status is not SignalStatus.AVAILABLE or result.score is None:
            raise RuntimeError(
                f"text comparator failed for pair {index}: "
                f"status={result.status.value} reason={result.reason} "
                f"details={result.details}"
            )
        scores.append(float(result.score))
    return scores


def _metrics(
    labels: list[int],
    scores: list[float],
    threshold: float,
    review_margin: float,
) -> Metrics:
    true_positives = false_positives = true_negatives = false_negatives = 0
    for label, score in zip(labels, scores, strict=True):
        predicted = score >= threshold
        if predicted and label == 1:
            true_positives += 1
        elif predicted and label == 0:
            false_positives += 1
        elif not predicted and label == 1:
            false_negatives += 1
        else:
            true_negatives += 1

    precision = (
        true_positives / (true_positives + false_positives)
        if true_positives + false_positives
        else None
    )
    recall = (
        true_positives / (true_positives + false_negatives)
        if true_positives + false_negatives
        else None
    )
    if precision is None or recall is None:
        f1 = 0.0
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    negative_count = true_negatives + false_positives
    false_positive_rate = false_positives / negative_count if negative_count else 0.0

    low = max(0.0, threshold - review_margin)
    high = min(1.0, threshold + review_margin)
    review_count = sum(low <= score <= high for score in scores)
    review_rate = review_count / len(scores)

    return Metrics(
        threshold=threshold,
        true_positives=true_positives,
        false_positives=false_positives,
        true_negatives=true_negatives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        f1=f1,
        false_positive_rate=false_positive_rate,
        review_rate=review_rate,
    )


def _best_f1_threshold(labels: list[int], scores: list[float]) -> tuple[float, Metrics]:
    """Return the best-F1 threshold on this same set (an optimistic upper bound)."""

    candidates = sorted({0.0, 1.0, *scores})
    best_threshold = 0.0
    best = _metrics(labels, scores, best_threshold, review_margin=0.0)
    for threshold in candidates:
        metrics = _metrics(labels, scores, threshold, review_margin=0.0)
        # Prefer higher F1; break ties by higher precision, then lower threshold.
        best_precision = best.precision or 0.0
        candidate_precision = metrics.precision or 0.0
        if (metrics.f1, candidate_precision) > (best.f1, best_precision):
            best_threshold, best = threshold, metrics
    return best_threshold, best


def _score_summary(values: list[float]) -> dict[str, float]:
    return {
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
    }


def _auc(labels: list[int], scores: list[float]) -> tuple[float, float]:
    from sklearn.metrics import average_precision_score, roc_auc_score

    return float(roc_auc_score(labels, scores)), float(
        average_precision_score(labels, scores)
    )


def _fmt(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _fixed_threshold_table(
    results: dict[str, list[float]],
    labels: list[int],
    threshold: float,
    review_margin: float,
) -> list[str]:
    lines = [
        "| Comparator | Precision | Recall | F1 | False positives | FPR | Review-band rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, scores in results.items():
        metrics = _metrics(labels, scores, threshold, review_margin)
        lines.append(
            f"| {name} | {_fmt(metrics.precision)} | {_fmt(metrics.recall)} | "
            f"{_fmt(metrics.f1)} | {metrics.false_positives} | "
            f"{_fmt(metrics.false_positive_rate)} | {_fmt(metrics.review_rate)} |"
        )
    return lines


def _sweep_table(
    results: dict[str, list[float]],
    labels: list[int],
    thresholds: tuple[float, ...],
) -> list[str]:
    lines = [
        "| Threshold | Comparator | Precision | Recall | F1 | False positives |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for threshold in thresholds:
        for name, scores in results.items():
            metrics = _metrics(labels, scores, threshold, review_margin=0.0)
            lines.append(
                f"| {threshold:.2f} | {name} | {_fmt(metrics.precision)} | "
                f"{_fmt(metrics.recall)} | {_fmt(metrics.f1)} | "
                f"{metrics.false_positives} |"
            )
    return lines


def _build_markdown(
    results: dict[str, list[float]],
    labels: list[int],
    threshold: float,
    review_margin: float,
    model_name: str,
) -> str:
    score_rows: list[str] = []
    for index, pair in enumerate(PAIRS):
        tfidf = results.get("TF-IDF", [None] * len(PAIRS))[index]
        embedding = results.get("Embeddings", [None] * len(PAIRS))[index]
        score_rows.append(
            f"| {index + 1} | `{pair.kind}` | {pair.label} | "
            f"{_fmt(tfidf, 4)} | {_fmt(embedding, 4)} |"
        )

    lines: list[str] = [
        "# TF-IDF vs sentence-embedding text similarity (illustrative)",
        "",
        "> **Synthetic data warning.** The repository has no labelled duplicate",
        "> dataset. This is a small hand-written evaluation set, not an estimate of",
        "> production precision or recall. The hard negatives intentionally share",
        "> wording but differ by location/entity; text evidence alone cannot resolve",
        "> them, and the full agent must combine location, category and time.",
        "",
        f"- Embedding model: `{model_name}`",
        f"- Pairs: {len(PAIRS)} ({sum(labels)} duplicate, {len(labels) - sum(labels)} non-duplicate)",
        f"- Primary threshold: `{threshold:.2f}`",
        f"- Review band: `[{max(0.0, threshold - review_margin):.2f}, "
        f"{min(1.0, threshold + review_margin):.2f}]` (inclusive proxy, not the M4 decision policy)",
        "",
        "## Fixed-threshold metrics",
        "",
        *(_fixed_threshold_table(results, labels, threshold, review_margin)),
        "",
        "## Threshold-independent ranking",
        "",
        "| Comparator | ROC-AUC | Average precision |",
        "|---|---:|---:|",
    ]
    for name, scores in results.items():
        auc, average_precision = _auc(labels, scores)
        lines.append(f"| {name} | {auc:.3f} | {average_precision:.3f} |")

    lines.extend(["", "## Threshold sweep", "", *(_sweep_table(results, labels, (0.3, 0.4, 0.5, 0.6, 0.7)))])

    lines.extend(
        [
            "",
            "## Score distribution",
            "",
            "| Comparator | Duplicate mean | Duplicate median | Non-duplicate mean | Non-duplicate median |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for name, scores in results.items():
        positive_scores = [score for score, label in zip(scores, labels) if label == 1]
        negative_scores = [score for score, label in zip(scores, labels) if label == 0]
        positive_summary = _score_summary(positive_scores)
        negative_summary = _score_summary(negative_scores)
        lines.append(
            f"| {name} | {positive_summary['mean']:.3f} | "
            f"{positive_summary['median']:.3f} | "
            f"{negative_summary['mean']:.3f} | "
            f"{negative_summary['median']:.3f} |"
        )

    lines.extend(
        [
            "",
            "## Per-pair scores",
            "",
            "| # | Kind | Label | TF-IDF | Embeddings |",
            "|---:|---|---:|---:|---:|",
            *score_rows,
            "",
            "## Reproduce",
            "",
            "```text",
            "python scripts/evaluate_text_similarity.py --local-files-only",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend",
        choices=("both", "tfidf", "embedding"),
        default="both",
        help="Which text backend(s) to evaluate.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.50,
        help="Pre-declared score threshold used for the primary metrics.",
    )
    parser.add_argument(
        "--review-margin",
        type=float,
        default=0.10,
        help="Half-width of the review-band proxy around the threshold.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_EMBEDDING_MODEL,
        help="Sentence Transformers model identifier.",
    )
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        help="Refuse network access; require the model to be in the local cache.",
    )
    parser.add_argument("--json", type=Path, help="Optional JSON output path.")
    parser.add_argument("--markdown", type=Path, help="Optional Markdown output path.")
    args = parser.parse_args(argv)
    if not 0.0 <= args.threshold <= 1.0:
        parser.error("--threshold must be in [0, 1]")
    if not 0.0 <= args.review_margin <= 1.0:
        parser.error("--review-margin must be in [0, 1]")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    labels = [pair.label for pair in PAIRS]
    results: dict[str, list[float]] = {}

    if args.backend in ("both", "tfidf"):
        results["TF-IDF"] = _score_pairs(TextComparator(), PAIRS)

    if args.backend in ("both", "embedding"):
        def loader(model_name: str):
            from sentence_transformers import SentenceTransformer

            return SentenceTransformer(
                model_name,
                local_files_only=args.local_files_only,
            )

        embedding = EmbeddingTextComparator(model_name=args.model, loader=loader)
        try:
            results["Embeddings"] = _score_pairs(embedding, PAIRS)
        except RuntimeError as exc:
            print(f"Embedding evaluation aborted: {exc}", file=sys.stderr)
            return 2

    markdown = _build_markdown(
        results,
        labels,
        args.threshold,
        args.review_margin,
        args.model,
    )
    print(markdown)

    if args.markdown is not None:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(markdown + "\n", encoding="utf-8")

    if args.json is not None:
        best_f1: dict[str, dict[str, object]] = {}
        ranking: dict[str, dict[str, float]] = {}
        for name, scores in results.items():
            threshold, metrics = _best_f1_threshold(labels, scores)
            auc, average_precision = _auc(labels, scores)
            best_f1[name] = {
                "threshold": threshold,
                "metrics": asdict(metrics),
            }
            ranking[name] = {
                "roc_auc": auc,
                "average_precision": average_precision,
            }

        payload = {
            "warning": (
                "ILLUSTRATIVE SYNTHETIC SET ONLY — not production accuracy. "
                "Hard negatives share wording but differ by location/entity."
            ),
            "model": args.model,
            "threshold": args.threshold,
            "review_margin": args.review_margin,
            "pairs": [asdict(pair) for pair in PAIRS],
            "scores": results,
            "metrics": {
                name: asdict(
                    _metrics(labels, scores, args.threshold, args.review_margin)
                )
                for name, scores in results.items()
            },
            "best_f1": best_f1,
            "roc_auc": ranking,
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
