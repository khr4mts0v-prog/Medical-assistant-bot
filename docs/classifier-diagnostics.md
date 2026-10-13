# Classifier diagnostics and public-data probes

## Local debugging

Run the classifier diagnostic against a UTF-8 text export. By default, the tool does not print document text:

\`\`\`bash
python scripts/debug_classifier.py path/to/document.txt
\`\`\`

It reports:
- the final primary type, confidence, margin, and final scores;
- matches from the base scoring rules;
- fuzzy header candidates;
- candidates present in raw scores but missing from final scores (usually a context filter or suppression stage);
- line prefixes that change the primary type or score set;
- per-page classification returned by the existing classifier.

For structured output:

\`\`\`bash
python scripts/debug_classifier.py path/to/document.txt --json
\`\`\`

Only use \`--show-lines\` if the terminal/session is trusted and the file contains no data you must keep private. Without that flag, the tool prints no source lines or clinical snippets. Do not paste raw medical documents into public issues or CI logs.

This is diagnostic instrumentation only. It does not change the classifier rules. It uses private helper functions in \`AIAnalise.py\`, so update the diagnostic if those internals are renamed.

## Public clinical-text probes

Run the public datasets probe locally:

\`\`\`bash
python scripts/probe_public_datasets.py --dataset rumedprime
python scripts/probe_public_datasets.py --dataset ruclinner
python scripts/probe_public_datasets.py --dataset all
\`\`\`

The GitHub Actions workflow **Public dataset diagnostics** can also be started manually from the Actions tab, or runs weekly. By default, the RuClinNER probe checks up to 300 rows per split; the RuMedPrimeData probe checks up to 500 records. Pass `--limit-per-split 0` or `--limit-rumedprime 0` to process every row. It downloads the public data at runtime and prints only aggregate predicted-label counts. It does not commit the source data, create an artifact, or print individual record text/IDs.

Downloads retry transient HTTP errors (including 429 and 5xx responses) with backoff. Each HTTP request has a 10-second connect timeout and a 45-second read timeout. The script prints source start/end markers, elapsed time, and aggregate progress counts (never record text or IDs). The GitHub Actions probe step has an 8-minute timeout and the job has a 10-minute timeout, so a stalled source cannot keep the workflow running indefinitely. If a selected source still cannot be processed, the script exits non-zero so CI cannot silently report a green probe. The diagnostic prints aggregate counts only and does not include record text, row IDs, or response bodies.

Important limitations:
- RuMedPrimeData contains de-identified visit-level symptoms and anamnesis, not document-form labels. Treat it as a false-positive/abstention probe, not an accuracy benchmark.
- RuClinNER is licensed CC BY-NC-SA 4.0. It is used only as a runtime diagnostic; do not redistribute its content or incorporate it into public fixtures without checking license compatibility.
- These probes cannot produce document-type accuracy, precision, or recall because there is no gold label for document form.
- External dataset availability failures make the probe job fail, but they are not evidence of a classifier regression; inspect the log to distinguish source/network errors from code errors. The curated fixture suite remains the deterministic regression gate.

## Labeled fixture evaluation

Run `python scripts/evaluate_classifier_corpus.py` to calculate document-level and page-level precision, recall, F1, and confusion matrices against the repository's labeled fixtures. Most fixtures are synthetic documents drafted from public form structures; the public-example subset currently contains only two published laboratory examples. This is useful for regression tracking, but it is not a statistically representative real-world validation set. For a stronger benchmark, collect a sufficiently diverse set of publicly shareable documents with known document-form labels, document provenance and licensing, then independently review the gold labels before using the results to tune classifier rules.
