#!/usr/bin/env python3
"""Evaluate the rule-based classifier against the local synthetic document corpus.

Run from the repository root:
    python scripts/evaluate_classifier_corpus.py

This is a diagnostic report, not a pass/fail test. Review every mismatch before
changing expected labels or classifier rules.
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

from AIAnalise import analyze_document


CORPUS_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "realistic_medical_documents.json"


def score_rows(pairs):
    labels = sorted({label for pair in pairs for label in pair})
    matrix = Counter(pairs)
    print(f"Examples evaluated: {len(pairs)}")
    print(f"Exact accuracy: {sum(expected == predicted for expected, predicted in pairs) / len(pairs):.1%}" if pairs else "No examples")
    print("\nPer-class metrics:")
    print("Class | Precision | Recall | F1 | Support")
    for label in labels:
        tp = matrix[(label, label)]
        fp = sum(n for (expected, predicted), n in matrix.items() if predicted == label and expected != label)
        fn = sum(n for (expected, predicted), n in matrix.items() if expected == label and predicted != label)
        support = sum(n for (expected, _), n in matrix.items() if expected == label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        print(f"{label} | {precision:.1%} | {recall:.1%} | {f1:.1%} | {support}")
    print("\nConfusion matrix (rows=expected, columns=predicted):")
    print("Expected \\ Predicted | " + " | ".join(labels))
    for expected in labels:
        print(expected + " | " + " | ".join(str(matrix[(expected, predicted)]) for predicted in labels))
    errors = [(expected, predicted) for expected, predicted in pairs if expected != predicted]
    if errors:
        print("\nMismatches:")
        for expected, predicted in errors:
            print(f"  expected={expected!r}; predicted={predicted!r}")


def main():
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    if not isinstance(corpus, list) or not corpus:
        raise SystemExit("Corpus must be a non-empty JSON array.")

    ids = [item.get("id") for item in corpus]
    if len(ids) != len(set(ids)):
        raise SystemExit("Corpus contains duplicate document IDs.")

    document_pairs = []
    page_pairs = []
    for item in corpus:
        if not item.get("id") or not item.get("text") or not item.get("expected_type"):
            raise SystemExit(f"Missing required field in corpus record: {item.get('id')!r}")
        result = analyze_document(item["text"])
        if item.get("expected_type") != "смешанный документ":
            document_pairs.append((item["expected_type"], result["primary_type"]))
        expected_pages = item.get("expected_page_types")
        if expected_pages:
            actual_pages = {str(page["page"]): page["primary_type"] for page in result["page_types"]}
            for page_number, expected_type in expected_pages.items():
                predicted_type = actual_pages.get(str(page_number), "не определено")
                page_pairs.append((expected_type, predicted_type))
                if expected_type != predicted_type:
                    print(f"PAGE MISMATCH {item['id']} page {page_number}: expected={expected_type!r}, predicted={predicted_type!r}")

    print(f"Loaded {len(corpus)} synthetic documents from {CORPUS_PATH}")
    print("\n=== Document-level evaluation ===")
    score_rows(document_pairs)
    if page_pairs:
        print("\n=== Page-level evaluation for mixed documents ===")
        score_rows(page_pairs)


if __name__ == "__main__":
    main()
