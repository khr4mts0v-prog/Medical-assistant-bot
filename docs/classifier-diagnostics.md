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

The GitHub Actions workflow **Public dataset diagnostics** can also be started manually from the Actions tab, or runs weekly. It downloads the public data at runtime and prints only aggregate predicted-label counts. It does not commit the source data, create an artifact, or print individual record text/IDs.

Important limitations:
- RuMedPrimeData contains de-identified visit-level symptoms and anamnesis, not document-form labels. Treat it as a false-positive/abstention probe, not an accuracy benchmark.
- RuClinNER is licensed CC BY-NC-SA 4.0. It is used only as a runtime diagnostic; do not redistribute its content or incorporate it into public fixtures without checking license compatibility.
- These probes cannot produce document-type accuracy, precision, or recall because there is no gold label for document form.
- External dataset failures are reported as skipped/failed diagnostics, not as a classifier regression. The curated fixture suite remains the deterministic regression gate.
