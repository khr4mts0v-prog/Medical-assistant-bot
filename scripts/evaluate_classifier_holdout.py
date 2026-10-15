#!/usr/bin/env python3
"""Evaluate the independent synthetic classifier holdout; never tunes rules.

All records in tests/fixtures/classifier_holdout_v1.json are synthetic. This
diagnostic reports every mismatch and per-class precision/recall/F1. It does
not change labels or gate CI based on a target accuracy.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from AIAnalise import CLASSIFICATION_VERSION, analyze_document  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "classifier_holdout_v1.json"


def evaluate() -> dict:
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ids = [row.get("id") for row in rows]
    if len(ids) != len(set(ids)) or any(not value for value in ids):
        raise ValueError("Holdout IDs must be present and unique")
    if any(row.get("source_kind") != "synthetic_holdout" for row in rows):
        raise ValueError("Every holdout record must be explicitly marked synthetic_holdout")

    scored = []
    for row in rows:
        result = analyze_document(row["text"])
        actual = result.get("primary_type", "не определено")
        scored.append({
            "id": row["id"],
            "expected": row["expected_type"],
            "actual": actual,
            "correct": actual == row["expected_type"],
            "confidence": result.get("confidence"),
            "review_required": result.get("review_required"),
            "note": row.get("note", ""),
        })

    labels = sorted({r["expected"] for r in scored} | {r["actual"] for r in scored})
    metrics = {}
    f1s = []
    for label in labels:
        tp = sum(r["expected"] == label and r["actual"] == label for r in scored)
        fp = sum(r["expected"] != label and r["actual"] == label for r in scored)
        fn = sum(r["expected"] == label and r["actual"] != label for r in scored)
        support = sum(r["expected"] == label for r in scored)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        if support:
            f1s.append(f1)
        metrics[label] = {
            "support": support, "predicted": tp + fp, "true_positive": tp,
            "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

    correct = sum(r["correct"] for r in scored)
    report = {
        "evaluation_kind": "independent_synthetic_holdout",
        "fixture": str(FIXTURE.relative_to(ROOT)),
        "classification_version": CLASSIFICATION_VERSION,
        "total": len(scored),
        "correct": correct,
        "incorrect": len(scored) - correct,
        "accuracy": round(correct / len(scored), 4) if scored else 0.0,
        "macro_f1_over_supported_labels": round(sum(f1s) / len(f1s), 4) if f1s else 0.0,
        "per_class_metrics": metrics,
        "mismatches": [r for r in scored if not r["correct"]],
        "caveat": (
            "Synthetic, curated holdout only. It is not a real-world estimate and "
            "does not test OCR quality, handwriting, image quality, or clinical correctness."
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    evaluate()
