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
from AIAnalise import (  # noqa: E402
    analyze_document,
    _classify_segment,
    _score_types,
    _fuzzy_header_matches,
)


def compact_scores(scores):
    return ", ".join(
        f"{label}={score}"
        for label, score in sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    ) or "(нет)"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", nargs="?", help="UTF-8 text file; omit to read stdin")
    parser.add_argument("--show-lines", action="store_true", help="print input lines (may contain personal data)")
    parser.add_argument("--max-lines", type=int, default=120,
                        help="maximum number of line prefixes to probe (default: 120)")
    parser.add_argument("--json", action="store_true", help="emit structured diagnostic JSON")
    args = parser.parse_args()
    if args.max_lines < 1:
        parser.error("--max-lines must be positive")

    text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
    result = analyze_document(text)
    raw_scores, raw_evidence = _score_types(text)
    segment_result = _classify_segment(text)
    fuzzy = _fuzzy_header_matches(text)
    final_scores = result.get("type_scores", {})
    lines = text.splitlines()
    probe_count = min(len(lines), args.max_lines)

    changed_lines = []
    previous = None
    for index in range(1, probe_count + 1):
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
            "prefix_lines_checked": probe_count,
            "prefix_probe_truncated": probe_count < len(lines),
            "raw_rule_scores": raw_scores,
            "raw_rule_evidence": raw_evidence,
            "fuzzy_header_matches": fuzzy,
            "segment_primary_type": segment_result.get("primary_type"),
            "segment_confidence": segment_result.get("confidence"),
            "segment_type_scores": segment_result.get("type_scores", {}),
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
    print(f"Финальные баллы документа: {compact_scores(final_scores)}")
    print("\n=== Этап 1: совпадения базовых правил ===")
    print(compact_scores(raw_scores))
    for label, hits in raw_evidence.items():
        print(f"  {label}: " + "; ".join(f"{h['reason']} (+{h['weight']})" for h in hits))
    print("\n=== Этап 2: заголовок и сегментные фильтры ===")
    print(f"Нечёткие совпадения заголовка: {fuzzy or '(нет)'}")
    print(f"Тип после обработки одного сегмента: {segment_result.get('primary_type')}")
    print(f"Баллы сегмента: {compact_scores(segment_result.get('type_scores', {}))}")
    print(f"Уверенность сегмента: {segment_result.get('confidence')}")
    print("\n=== Этап 3: агрегация документа/страниц ===")
    print(f"Тип документа: {result.get('primary_type')}")
    print(f"Баллы документа: {compact_scores(final_scores)}")
    removed = {label: score for label, score in raw_scores.items() if label not in segment_result.get("type_scores", {})}
    if removed:
        print("Базовые кандидаты, отсутствующие после сегментных фильтров/порогов:",
              compact_scores(removed))
    if segment_result.get("primary_type") != result.get("primary_type"):
        print("ВНИМАНИЕ: итог изменился между обработкой одного сегмента и агрегацией документа/страниц.")
    print("\n=== Этап 4: построчная локализация ===")
    print(f"Проверено префиксов строк: {probe_count}/{len(lines)}")
    for item in changed_lines:
        print(f"  после строки {item['line']}: тип={item['primary_type']}; "
              f"баллы={compact_scores(item['type_scores'])}")
        if args.show_lines:
            print(f"    текст: {lines[item['line'] - 1]}")
    if probe_count < len(lines):
        print("Остальные строки не проверялись; увеличьте --max-lines для более длинного документа.")
    print("\nБез --show-lines исходный текст не выводится. Диагностика не меняет правила классификатора.")


if __name__ == "__main__":
    main()
