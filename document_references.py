"""Conservative discovery of explicitly referenced companion documents.

The matcher only follows references found in documents already selected for a user's
consented analysis. It does not infer that an unmentioned document is missing.
"""
import re
from typing import Any

_REFERENCE = re.compile(
    r"(?P<context>"
    r"см\.?\s*(?:также\s*)?|смотри(?:те)?\s+|упомянут\w*\s+|"
    r"рекомендован\w*\s+|требуется\s+|необходим\w*\s+|"
    r"для\s+(?:полной\s+)?(?:оценки|интерпретации|решения\s+вопроса)\s+"
    r"|на\s+основании\s+|сопоставить\s+с\s+|сравнить\s+с\s+"
    r")"
    r"(?P<target>(?:заключени[ея]|консультаци[яию]|протокол[аом]?|"
    r"выписк[аиу]?|эпикриз[аом]?|результат[аов]?|исследовани[яию]|осмотр[аом]?)"
    r"(?:\s+(?:врача|специалиста))?"
    r"(?:\s+[а-яёa-z-]{3,}){0,3})",
    re.IGNORECASE,
)
_WORDS = re.compile(r"[а-яёa-z]{4,}", re.IGNORECASE)
_GENERIC = {
    "заключение", "заключения", "консультация", "консультации", "протокол",
    "выписка", "выписки", "эпикриз", "результаты", "результат", "исследование",
    "исследования", "осмотр", "врача", "специалиста", "медицинский", "медицинская",
    "полный", "полная", "нужно", "нужна", "необходимо", "согласно", "также",
}

def _norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("ё", "е").split())

def _target_tokens(target: str) -> list[str]:
    return [
        token for token in _WORDS.findall(_norm(target))
        if token not in _GENERIC and len(token) >= 4
    ]

def discover_referenced_documents(source_rows: list[dict], all_patient_rows: list[dict]) -> dict:
    """Return matched document rows and only high-confidence required missing references."""
    all_by_id = {int(row["id"]): row for row in all_patient_rows}
    found: dict[int, dict] = {}
    missing_required: list[dict] = []
    seen_refs = set()

    for source in source_rows:
        source_id = int(source.get("id") or 0)
        text = str(source.get("text") or "")
        for match in _REFERENCE.finditer(text):
            context = _norm(match.group("context"))
            target = " ".join(match.group("target").split()).strip(" .,:;")
            tokens = _target_tokens(target)
            # Generic references such as "см. заключение" are too ambiguous to match safely.
            if not tokens:
                continue
            key = (source_id, _norm(target))
            if key in seen_refs:
                continue
            seen_refs.add(key)

            candidates = []
            for candidate_id, candidate in all_by_id.items():
                if candidate_id == source_id:
                    continue
                haystack = _norm(
                    str(candidate.get("name") or "") + " "
                    + str(candidate.get("kind") or "") + " "
                    + str(candidate.get("text") or "")[:1800]
                )
                matched = [
                    token for token in tokens
                    if re.search(r"(?<![а-яa-z])" + re.escape(token)[:7], haystack)
                ]
                if matched:
                    candidates.append((len(matched), candidate))

            if candidates:
                candidates.sort(
                    key=lambda pair: (
                        pair[0],
                        str(pair[1].get("date") or ""),
                        int(pair[1].get("id") or 0),
                    ),
                    reverse=True,
                )
                for _, candidate in candidates[:3]:
                    found[int(candidate["id"])] = candidate
                continue

            required = bool(
                re.search(r"для\s+(?:полной\s+)?(?:оценки|интерпретации|решения\s+вопроса)", context)
                or "на основании" in context
                or "сопоставить с" in context
                or "сравнить с" in context
                or "требуется" in context
                or "необходимо" in context
            )
            if required:
                missing_required.append({
                    "target": target,
                    "source": {
                        "document_id": source_id,
                        "name": str(source.get("name") or "Документ без названия"),
                        "date": source.get("date"),
                    },
                    "reason": "explicit_reference_required_for_interpretation",
                })

    return {
        "found_documents": list(found.values()),
        "missing_required": missing_required[:20],
    }
