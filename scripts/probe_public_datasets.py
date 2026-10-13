#!/usr/bin/env python3
"""Aggregate-only probes against public clinical-text datasets.

No patient-level text, source identifiers, or row IDs are printed or written.
These datasets do not provide document-form labels, so results are abstention /
false-positive diagnostics, NOT classification accuracy.
"""
import argparse
import csv
import io
import sys
import zipfile
from collections import Counter

import requests

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from AIAnalise import analyze_document  # noqa: E402

RUMEDPRIME_URL = "https://zenodo.org/records/5765873/files/RuMedPrimeData.zip?download=1"


def summarize(name, texts):
    total = 0
    labels = Counter()
    confidence = Counter()
    nonempty = 0
    for text in texts:
        if not isinstance(text, str) or not text.strip():
            continue
        nonempty += 1
        result = analyze_document(text)
        labels[result.get("primary_type", "не определено")] += 1
        confidence[result.get("confidence", "unknown")] += 1
        total += 1
    print(f"\n[{name}] records_scored={total}; empty_or_skipped={max(0, len(texts) - nonempty)}")
    print("Predicted primary labels (NOT ground-truth accuracy):")
    for label, count in labels.most_common():
        print(f"  {label}: {count} ({count / total:.1%})" if total else f"  {label}: 0")
    print("Confidence distribution:")
    for label, count in sorted(confidence.items()):
        print(f"  {label}: {count}")


def probe_rumedprime():
    print("Downloading RuMedPrimeData from Zenodo (temporary in-memory processing)...")
    response = requests.get(RUMEDPRIME_URL, timeout=(15, 120))
    response.raise_for_status()
    texts = []
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        candidates = [name for name in archive.namelist() if name.lower().endswith((".tsv", ".csv"))]
        if not candidates:
            raise RuntimeError("Zenodo archive contains no TSV/CSV file")
        with archive.open(candidates[0]) as raw:
            stream = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(stream, delimiter="\t" if candidates[0].lower().endswith(".tsv") else ",")
            fields = reader.fieldnames or []
            clinical_fields = [field for field in ("symptoms", "anamnesis") if field in fields]
            if not clinical_fields:
                raise RuntimeError(f"Expected symptoms/anamnesis fields; found {fields!r}")
            for row in reader:
                texts.append("\n".join(str(row.get(field, "") or "") for field in clinical_fields))
    summarize("RuMedPrimeData / symptoms + anamnesis", texts)


def probe_ruclinner():
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError("Install the optional 'datasets' package to probe RuClinNER") from exc
    for config in ("medterm", "drugrel", "covid_rmj"):
        for split in ("train", "test"):
            try:
                dataset = load_dataset("medlinx/RuClinNER", config, split=split, streaming=True)
                def texts():
                    for row in dataset:
                        value = row.get("text")
                        if isinstance(value, str):
                            yield value
                        elif isinstance(row.get("annotation"), str):
                            yield row["annotation"]
                labels = Counter()
                confidence = Counter()
                count = 0
                for text in texts():
                    if not text.strip():
                        continue
                    result = analyze_document(text)
                    labels[result.get("primary_type", "не определено")] += 1
                    confidence[result.get("confidence", "unknown")] += 1
                    count += 1
                if count:
                    print(f"\n[RuClinNER/{config}/{split}] records_scored={count}")
                    print("Predicted primary labels (NOT ground-truth accuracy):")
                    for label, n in labels.most_common():
                        print(f"  {label}: {n} ({n / count:.1%})")
                    print("Confidence distribution: " + str(dict(confidence)))
                else:
                    print(f"\n[RuClinNER/{config}/{split}] no text records found")
            except Exception as exc:
                print(f"\n[RuClinNER/{config}/{split}] SKIPPED: {type(exc).__name__}: {str(exc)[:180]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("all", "rumedprime", "ruclinner"), default="all")
    args = parser.parse_args()
    print("DIAGNOSTIC ONLY: these corpora do not contain gold document-type labels.")
    print("Only aggregate predictions are printed; raw text is not saved as a fixture or artifact.")
    if args.dataset in ("all", "rumedprime"):
        try:
            probe_rumedprime()
        except Exception as exc:
            print(f"\n[RuMedPrimeData] FAILED: {type(exc).__name__}: {str(exc)[:180]}")
            if args.dataset == "rumedprime":
                raise
    if args.dataset in ("all", "ruclinner"):
        probe_ruclinner()


if __name__ == "__main__":
    main()
