"""Reproduce aggregate classification-corpus metrics; outputs no patient data."""
from __future__ import annotations
from collections import Counter
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from AIAnalise import CLASSIFICATION_VERSION, classify_document  # noqa: E402
from test_classification_corpus import EDGE_CASES, FIXTURES, PUBLIC_FORMS  # noqa: E402

OUTPUT = ROOT / "public_eval" / "classification_evaluation.json"


def evaluate():
    groups = {"public_templates": [], "synthetic_edge_cases": []}
    for filename, expected in PUBLIC_FORMS.items():
        text = (FIXTURES / filename).read_text(encoding="utf-8", errors="replace")
        actual = classify_document(text)
        groups["public_templates"].append(
            {"case": filename, "expected": expected, "actual": actual, "correct": actual == expected}
        )
    for case_name, expected, text in EDGE_CASES:
        actual = classify_document(text)
        groups["synthetic_edge_cases"].append(
            {"case": case_name, "expected": expected, "actual": actual, "correct": actual == expected}
        )

    rows = groups["public_templates"] + groups["synthetic_edge_cases"]
    confusion = Counter((x["expected"], x["actual"]) for x in rows)
    labels = sorted({x["expected"] for x in rows} | {x["actual"] for x in rows})
    per_class = {}
    f1_values = []
    for label in labels:
        tp = sum(x["expected"] == label and x["actual"] == label for x in rows)
        support = sum(x["expected"] == label for x in rows)
        predicted = sum(x["actual"] == label for x in rows)
        precision = tp / predicted if predicted else 0.0
        recall = tp / support if support else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
        if support:
            f1_values.append(f1)
        per_class[label] = {
            "support": support, "predicted": predicted, "true_positive": tp,
            "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        }
    report = {
        "date": date.today().isoformat(),
        "classification_version": CLASSIFICATION_VERSION,
        "public_templates": {
            "total": len(groups["public_templates"]),
            "correct": sum(x["correct"] for x in groups["public_templates"]),
        },
        "synthetic_edge_cases": {
            "total": len(groups["synthetic_edge_cases"]),
            "correct": sum(x["correct"] for x in groups["synthetic_edge_cases"]),
        },
        "total": len(rows),
        "correct": sum(x["correct"] for x in rows),
        "incorrect": sum(not x["correct"] for x in rows),
        "accuracy_on_curated_cases": round(sum(x["correct"] for x in rows) / len(rows), 4) if rows else 0.0,
        "macro_f1_over_supported_labels": round(sum(f1_values) / len(f1_values), 4) if f1_values else 0.0,
        "abstention_rate": round(sum(x["actual"] == "не определено" for x in rows) / len(rows), 4) if rows else 0.0,
        "per_class_metrics": per_class,
        "confusion_pairs": [
            {"expected": exp, "actual": act, "count": count}
            for (exp, act), count in sorted(confusion.items())
        ],
        "errors": [x for x in rows if not x["correct"]],
        "caveat": (
            "Selected public blank forms/legal-reference page extracts and synthetic text cases only; "
            "these figures are not real-world accuracy estimates for filled or scanned patient records."
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    result = evaluate()
    raise SystemExit(0 if result["incorrect"] == 0 else 1)
