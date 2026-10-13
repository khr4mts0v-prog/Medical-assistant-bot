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
from pathlib import Path

import pyarrow.parquet as pq
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from AIAnalise import analyze_document  # noqa: E402

RUMEDPRIME_URL = "https://zenodo.org/records/5765873/files/RuMedPrimeData.zip?download=1"
RUCLINNER_BASE = "https://huggingface.co/datasets/medlinx/RuClinNER/resolve/main/data"


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
    print(f"\n[{name}] records_scored={total}; empty_or_skipped={max(0, len(texts) - nonempty)}", flush=True)
    print("Predicted primary labels (NOT ground-truth accuracy):", flush=True)
    for label, count in labels.most_common():
        print(f"  {label}: {count} ({count / total:.1%})" if total else f"  {label}: 0", flush=True)
    print("Confidence distribution:", flush=True)
    for label, count in sorted(confidence.items()):
        print(f"  {label}: {count}", flush=True)


def probe_rumedprime():
    print("Downloading RuMedPrimeData from Zenodo (temporary in-memory processing)...", flush=True)
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
                raise RuntimeError("Expected symptoms/anamnesis fields in the public TSV")
            for row in reader:
                texts.append("\n".join(str(row.get(field, "") or "") for field in clinical_fields))
    summarize("RuMedPrimeData / symptoms + anamnesis", texts)


def probe_ruclinner(limit_per_split):
    configs = ("medterm", "drugrel", "covid_rmj")
    splits = ("train", "test")
    for config in configs:
        for split in splits:
            url = f"{RUCLINNER_BASE}/{config}/{split}.parquet?download=true"
            try:
                print(f"Downloading RuClinNER {config}/{split}...", flush=True)
                response = requests.get(url, timeout=(15, 90))
                response.raise_for_status()
                parquet = pq.ParquetFile(io.BytesIO(response.content))
                available = set(parquet.schema_arrow.names)
                columns = [field for field in ("text", "annotation") if field in available]
                if not columns:
                    print(f"[RuClinNER/{config}/{split}] SKIPPED: no text/annotation column", flush=True)
                    continue

                labels = Counter()
                confidence = Counter()
                count = 0
                stopped_at_limit = False
                for batch in parquet.iter_batches(batch_size=128, columns=columns):
                    for row in batch.to_pylist():
                        text = row.get("text") or row.get("annotation") or ""
                        if not isinstance(text, str) or not text.strip():
                            continue
                        result = analyze_document(text)
                        labels[result.get("primary_type", "не определено")] += 1
                        confidence[result.get("confidence", "unknown")] += 1
                        count += 1
                        if limit_per_split and count >= limit_per_split:
                            stopped_at_limit = True
                            break
                    if stopped_at_limit:
                        break
                print(f"\n[RuClinNER/{config}/{split}] records_scored={count}; sampled={stopped_at_limit}", flush=True)
                print("Predicted primary labels (NOT ground-truth accuracy):", flush=True)
                for label, n in labels.most_common():
                    print(f"  {label}: {n} ({n / count:.1%})" if count else f"  {label}: 0", flush=True)
                print("Confidence distribution: " + str(dict(confidence)), flush=True)
            except Exception as exc:
                # Do not print record contents, request URLs with tokens, or environment data.
                print(f"\n[RuClinNER/{config}/{split}] SKIPPED: {type(exc).__name__}: {str(exc)[:180]}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("all", "rumedprime", "ruclinner"), default="all")
    parser.add_argument("--limit-per-split", type=int, default=500,
                        help="RuClinNER rows per split; 0 means all rows (default: 500)")
    args = parser.parse_args()
    if args.limit_per_split < 0:
        parser.error("--limit-per-split cannot be negative")
    print("DIAGNOSTIC ONLY: these corpora do not contain gold document-type labels.", flush=True)
    print("Only aggregate predictions are printed; raw text is not saved as a fixture or artifact.", flush=True)
    if args.dataset in ("all", "rumedprime"):
        try:
            probe_rumedprime()
        except Exception as exc:
            print(f"\n[RuMedPrimeData] FAILED: {type(exc).__name__}: {str(exc)[:180]}", flush=True)
            if args.dataset == "rumedprime":
                raise
    if args.dataset in ("all", "ruclinner"):
        probe_ruclinner(args.limit_per_split)


if __name__ == "__main__":
    main()
