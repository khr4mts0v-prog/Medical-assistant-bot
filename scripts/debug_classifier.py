#!/usr/bin/env python3
"""Explainable, privacy-conscious diagnostics for the rule-based document classifier.

By default, this prints scores and line numbers only, never source text. Use
--show-lines only when the input is safe to display in the current terminal.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from AIAnalise import analyze_document, _score_types, _fuzzy_header_matches  # noqa: E402


def compact_scores(scores):
    return ", ".join(f"{label}={score}" for label, score in sorted(scores.items(), key=lambda x: (-x[1], x[0]))) or "(нет)"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", help="UTF-8 text file; omit to read stdin")
    parser.add_argument("--show-lines", action="store_true", help="print input lines (may contain personal data)")
    parser.add_argument("--json", action="store_true", help="emit structured diagnostic JSON")
    args = parser.parse_args()

    text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    result = analyze_document(text)
    raw_scores, raw_evidence = _score_types(text)
    fuzzy = _fuzzy_header_matches(text)
    final_scores = result.get("type_scores", {})
    lines = text.splitlines()

    changed_lines = []
    previous = None
    for index in range(1, len(lines) + 1):
        prefix_result = analyze_document("\n".join(lines[:index]))
        signature = (prefix_result.get("primary_type"), tuple(sorted(prefix_result.get("type_scores", {}).items())))
        if signature != previous:
            changed_lines.append({
                "line": index,
                "primary_type": prefix_result.get("primary_type"),
                "type_scores": prefix_result.get("type_scores", {}),
            })
            previous = signature

    if args.json:
        payload = {
            "input_lines": len(lines),
            "raw_rule_scores": raw_scores,
            "raw_rule_evidence": raw_evidence,
            "fuzzy_header_matches": fuzzy,
            "final_type_scores": final_scores,
            "primary_type": result.get("primary_type"),
            "confidence": result.get("confidence"),
            "margin": result.get("margin"),
            "evidence_for_primary": result.get("evidence"),
            "page_types": result.get("page_types", []),
            "prefix_changes": changed_lines,
        }
        if args.show_lines:
            payload["lines"] = [{"line": i, "text": line} for i, line in enumerate(lines, 1)]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print("=== Итог классификации ===")
    print(f"Основной тип: {result.get('primary_type')}")
    print(f"Уверенность: {result.get('confidence')}; margin={result.get('margin')}")
    print(f"Финальные баллы: {compact_scores(final_scores)}")
    print("\n=== Этап 1: совпадения базовых правил ===")
    print(compact_scores(raw_scores))
    for label, hits in raw_evidence.items():
        print(f"  {label}: " + "; ".join(f"{h['reason']} (+{h['weight']})" for h in hits))
    print("\n=== Этап 2: нечёткое совпадение заголовка ===")
    print(fuzzy or "(совпадений нет)")
    print("\n=== Этап 3: сравнение базовых и финальных баллов ===")
    removed = {label: score for label, score in raw_scores.items() if label not in final_scores}
    reduced = {label: (score, final_scores[label]) for label, score in raw_scores.items()
               if label in final_scores and final_scores[label] != score}
    if removed:
        print("Кандидаты, исчезнувшие после фильтров/контекстных правил:", compact_scores(removed))
    if reduced:
        print("Изменённые баллы:", reduced)
    if not removed and not reduced:
        print("Явных отличий между базовыми и финальными баллами нет.")
    print("\n=== Этап 4: построчная локализация ===")
    print("Строки, после добавления которых меняется итог/набор баллов:")
    for item in changed_lines:
        print(f"  строка {item['line']}: тип={item['primary_type']}; баллы={compact_scores(item['type_scores'])}")
        if args.show_lines:
            print(f"    текст: {lines[item['line'] - 1]}")
    print("\nПримечание: исчезновение кандидата между этапами указывает на контекстный фильтр/подавление;")
    print("этот отчёт не исполняет и не меняет правила классификатора.")


if __name__ == "__main__":
    main()
