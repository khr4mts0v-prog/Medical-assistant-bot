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
import time
import zipfile
from collections import Counter
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from AIAnalise import analyze_document  # noqa: E402

RUMEDPRIME_URL = "https://zenodo.org/records/5765873/files/RuMedPrimeData.zip?download=1"
RUCLINNER_BASE = "https://huggingface.co/datasets/medlinx/RuClinNER/resolve/main/data"
CONNECT_TIMEOUT_SECONDS = 10
READ_TIMEOUT_SECONDS = 45


def build_retry_session():
    """Retry transient download failures such as Zenodo/Hugging Face HTTP 504s."""
    retry = Retry(
        total=3,
        connect=3,
        read=2,
        status=3,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = build_retry_session()


def describe_error(exc):
    """Return a concise error summary without echoing URLs or response bodies."""
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return f"{type(exc).__name__} (HTTP {status})" if status else type(exc).__name__


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


def probe_rumedprime(limit_records):
    started = time.monotonic()
    print("START source=RuMedPrimeData; downloading archive (in-memory only)...", flush=True)
    response = SESSION.get(
        RUMEDPRIME_URL,
        timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
    )
    response.raise_for_status()
    print(f"RuMedPrimeData download complete; bytes={len(response.content)}; parsing records...", flush=True)
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
                if len(texts) % 100 == 0:
                    print(f"RuMedPrimeData progress: records_read={len(texts)}", flush=True)
                if limit_records and len(texts) >= limit_records:
                    break
    print(f"RuMedPrimeData: collected {len(texts)} records; limit={limit_records or 'all'}", flush=True)
    summarize("RuMedPrimeData / symptoms + anamnesis", texts)
    print(f"END source=RuMedPrimeData; elapsed_seconds={time.monotonic() - started:.1f}", flush=True)


def probe_ruclinner(limit_per_split):
    import pyarrow.parquet as pq

    had_failures = False
    configs = ("medterm", "drugrel", "covid_rmj")
    splits = ("train", "test")
    for config in configs:
        for split in splits:
            source_started = time.monotonic()
            url = f"{RUCLINNER_BASE}/{config}/{split}.parquet?download=true"
            try:
                print(f"START source=RuClinNER/{config}/{split}; downloading parquet...", flush=True)
                response = SESSION.get(
                    url,
                    timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
                )
                response.raise_for_status()
                parquet = pq.ParquetFile(io.BytesIO(response.content))
                available = set(parquet.schema_arrow.names)
                columns = [field for field in ("text", "annotation") if field in available]
                if not columns:
                    print(f"[RuClinNER/{config}/{split}] FAILED: no text/annotation column", flush=True)
                    had_failures = True
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
                        if count % 100 == 0:
                            print(f"[RuClinNER/{config}/{split}] progress: scored={count}", flush=True)
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
                print(f"END source=RuClinNER/{config}/{split}; elapsed_seconds={time.monotonic() - source_started:.1f}", flush=True)
            except Exception as exc:
                # Do not print record contents, request URLs with tokens, or environment data.
                print(f"\n[RuClinNER/{config}/{split}] FAILED: {describe_error(exc)}; elapsed_seconds={time.monotonic() - source_started:.1f}", flush=True)
                had_failures = True
    return not had_failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("all", "rumedprime", "ruclinner"), default="all")
    parser.add_argument("--limit-per-split", type=int, default=300,
                        help="RuClinNER rows per split; 0 means all rows (default: 300)")
    parser.add_argument("--limit-rumedprime", type=int, default=500,
                        help="Maximum RuMedPrimeData records; 0 means all rows (default: 500)")
    args = parser.parse_args()
    if args.limit_per_split < 0 or args.limit_rumedprime < 0:
        parser.error("record limits cannot be negative")
    print("DIAGNOSTIC ONLY: these corpora do not contain gold document-type labels.", flush=True)
    print("Only aggregate predictions are printed; raw text is not saved as a fixture or artifact.", flush=True)
    print(f"CONFIG dataset={args.dataset}; rumedprime_limit={args.limit_rumedprime}; ruclinner_limit_per_split={args.limit_per_split}; request_timeout_connect={CONNECT_TIMEOUT_SECONDS}s; request_timeout_read={READ_TIMEOUT_SECONDS}s", flush=True)
    failed_sources = []
    if args.dataset in ("all", "rumedprime"):
        source_started = time.monotonic()
        try:
            print("BEGIN source=RuMedPrimeData", flush=True)
            probe_rumedprime(args.limit_rumedprime)
        except Exception as exc:
            print(f"\n[RuMedPrimeData] FAILED: {describe_error(exc)}; elapsed_seconds={time.monotonic() - source_started:.1f}", flush=True)
            failed_sources.append("RuMedPrimeData")
    if args.dataset in ("all", "ruclinner"):
        print("BEGIN source=RuClinNER", flush=True)
        if not probe_ruclinner(args.limit_per_split):
            failed_sources.append("RuClinNER")

    if failed_sources:
        print("\nDIAGNOSTIC FAILED: one or more selected data sources could not be processed: "
              + ", ".join(failed_sources), flush=True)
        return 1
    print("\nDIAGNOSTIC COMPLETE: all selected data sources processed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
