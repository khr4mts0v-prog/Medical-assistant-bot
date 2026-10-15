#!/usr/bin/env python3
"""Diagnostic evaluation of synthetic and publicly published anonymized examples."""
import json
from collections import Counter, defaultdict, defaultdict
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from AIAnalise import analyze_document

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
CORPORA = [
    FIXTURES / "realistic_medical_documents.json",
    FIXTURES / "public_anonymized_examples.json",
    FIXTURES / "adversarial_medical_documents.json",
    FIXTURES / "adversarial_medical_documents_round2.json",
    FIXTURES / "realistic_medical_documents_round2.json",
    FIXTURES / "russian_public_template_examples.json",
    FIXTURES / "public_official_forms_round2.json",
]


def print_metrics(pairs):
    labels = sorted({label for expected, predicted in pairs for label in (expected, predicted)})
    matrix = Counter(pairs)
    correct = sum(expected == predicted for expected, predicted in pairs)
    print(f"Examples: {len(pairs)}; exact accuracy: {correct / len(pairs):.1%}" if pairs else "No examples")
    print("\nClass | Precision | Recall | F1 | Support")
    for label in labels:
        tp = matrix[(label, label)]
        fp = sum(n for (expected, predicted), n in matrix.items() if predicted == label and expected != label)
        fn = sum(n for (expected, predicted), n in matrix.items() if expected == label and predicted != label)
        support = sum(n for (expected, _), n in matrix.items() if expected == label)
        p = tp / (tp + fp) if tp + fp else 0
        r = tp / (tp + fn) if tp + fn else 0
        f = 2 * p * r / (p + r) if p + r else 0
        print(f"{label} | {p:.1%} | {r:.1%} | {f:.1%} | {support}")
    print("\nConfusion matrix (rows=expected, columns=predicted)")
    print("Expected \\ Predicted | " + " | ".join(labels))
    for expected in labels:
        print(expected + " | " + " | ".join(str(matrix[(expected, predicted)]) for predicted in labels))


def main():
    records = []
    for path in CORPORA:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise SystemExit(f"Expected a JSON array in {path}")
        records.extend((path.name, item) for item in data)

    ids = [item.get("id") for _, item in records]
    if any(not item_id for item_id in ids) or len(ids) != len(set(ids)):
        raise SystemExit("Missing or duplicate document IDs")

    pairs = []
    page_pairs = []
    group_pairs = defaultdict(list)
    group_unknown = Counter()
    group_total = Counter()
    mismatches = []
    for filename, item in records:
        result = analyze_document(item["text"])
        expected = item["expected_type"]
        if expected != "смешанный документ":
            predicted = result["primary_type"]
            record_kind = item.get("record_kind") or item.get("source_type") or "synthetic_fixture"
            pairs.append((expected, predicted))
            group_pairs[record_kind].append((expected, predicted))
            group_total[record_kind] += 1
            if predicted == "не определено":
                group_unknown[record_kind] += 1
            if expected != predicted:
                mismatches.append("document mismatch: " + item["id"])
                print(f"DOCUMENT MISMATCH {item['id']} [{filename}]: expected={expected!r}, predicted={predicted!r}, scores={result.get('type_scores', {})}")
        for page_number, page_type in item.get("expected_page_types", {}).items():
            actual = {str(page["page"]): page["primary_type"] for page in result["page_types"]}
            predicted = actual.get(str(page_number), "не определено")
            page_pairs.append((page_type, predicted))
            if page_type != predicted:
                mismatches.append("page mismatch: " + item["id"])
                print(f"PAGE MISMATCH {item['id']} page {page_number}: expected={page_type!r}, predicted={predicted!r}")

    print(f"Loaded {len(records)} documents:")
    for path in CORPORA:
        print(f"  - {path.name}")
    print("\n=== Document-level evaluation ===")
    print_metrics(pairs)
    print("\n=== Results by source/record kind ===")
    print("Record kind | N | Exact accuracy | Unknown predicted | Unknown rate")
    for kind in sorted(group_pairs):
        group = group_pairs[kind]
        n = len(group)
        correct = sum(expected == predicted for expected, predicted in group)
        unknown = group_unknown[kind]
        print(f"{kind} | {n} | {correct / n:.1%} | {unknown} | {unknown / n:.1%}")
    if page_pairs:
        print("\n=== Page-level evaluation ===")
        print_metrics(page_pairs)
    if len(pairs) < 40:
        mismatches.append("corpus has fewer than 40 document examples")
    if mismatches:
        print("\nREGRESSION GATE FAILED: " + str(len(mismatches)) + " issue(s)")
        raise SystemExit(1)
    print("\nREGRESSION GATE PASSED")


if __name__ == "__main__":
    main()
