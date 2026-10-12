"""Explainable multi-label medical document analysis.
The analyzer extracts search aids, not diagnoses or treatment recommendations.
"""
import os
import re
import requests

TYPE_PATTERNS = {
    "выписка": [r"\bвыпис(?:ка|ной эпикриз)\b", r"\bэпикриз\b", r"выписан[аоы]?\s+из\s+стационар", r"история болезни", r"стационарн\w+\s+лечени"],
    "лабораторные анализы": [r"общ(?:ий|его)\s+анализ\s+крови", r"клиническ\w+\s+анализ\s+крови", r"общ(?:ий|его)\s+анализ\s+мочи", r"биохимическ\w+\s+анализ", r"\bферритин\b", r"\bгемоглобин\b", r"\bлейкоцит\w*\b", r"\bтромбоцит\w*\b", r"референсн\w+\s+знач", r"результат\w*\s+исследован", r"\bттг\b", r"\bалт\b", r"\bаст\b", r"\bбилирубин\b", r"\bкреатинин\b"],
    "УЗИ": [r"\bузи\b", r"ультразвуков\w+\s+исследован", r"эхографи", r"допплерограф"],
    "ЭКГ": [r"\bэкг\b", r"электрокардиограмм", r"синусов\w+\s+ритм"],
    "рентген": [r"\bрентген\w*\b", r"рентгенограф", r"рентгенограмм"],
    "КТ": [r"\bкт\b", r"компьютерн\w+\s+томограф"],
    "МРТ": [r"\bмрт\b", r"магнитно[- ]резонансн\w+\s+томограф"],
    "заключение специалиста": [r"заключение\s+(?:врача|специалиста|невролога|кардиолога|педиатра|терапевта)", r"консультаци\w+\s+(?:врача|невролога|кардиолога|педиатра|терапевта|офтальмолога|лора)", r"осмотр\s+(?:врача|невролога|кардиолога|педиатра|терапевта)"],
    "назначения и лечение": [r"\bназначен\w*\b", r"рекомендован\w+\s+(?:лечение|приём|принимать)", r"\bдозировк\w*\b", r"\bсхема\s+лечени[яе]\b", r"принимать\s+по", r"\bрецепт\b", r"\bмг\s*/\s*сут"],
    "вакцинация": [r"\bвакцин\w*\b", r"\bпрививк\w*\b", r"иммунизац"],
    "беременность и роды": [r"\bбеременност\w*\b", r"\bгестационн\w*\s+срок\b", r"\bакушер\w*\b", r"\bродов\w*\b", r"\bскрининг\s+(?:1|2|перв|втор)"],
    "справка или сертификат": [r"\bмедицинск\w+\s+справк", r"\bсертификат\b", r"допущен\w+\s+к"],
}
LAB_MARKERS = {
    "гемоглобин": r"гемоглобин|\bhgb\b|\bhb\b", "ферритин": r"ферритин",
    "лейкоциты": r"лейкоцит", "эритроциты": r"эритроцит", "тромбоциты": r"тромбоцит",
    "гематокрит": r"гематокрит", "глюкоза": r"глюкоз", "креатинин": r"креатинин",
    "мочевина": r"мочевин", "АЛТ": r"\bалт\b|аланинаминотрансфераз", "АСТ": r"\bаст\b|аспартатаминотрансфераз",
    "билирубин": r"билирубин", "ТТГ": r"\bттг\b|тиреотропн\w+\s+гормон", "Т4 свободный": r"\bт4\s+свободн",
    "С-реактивный белок": r"с-реактивн\w+\s+белок|\bсрб\b", "СОЭ": r"\bсоэ\b|скорость\s+оседания\s+эритроцитов",
    "витамин B12": r"витамин\s*b?12|цианокобаламин", "витамин D": r"витамин\s*d\b|25-он\s+d",
    "холестерин": r"холестерин", "общий белок": r"общий\s+белок", "альбумин": r"альбумин",
    "мочевая кислота": r"мочевая\s+кислота",
}
VALUE_RE = re.compile(r"(?<![A-Za-zА-Яа-яЁё])([<>≤≥]?\s*-?\d+(?:[.,]\d+)?)\s*(мкмоль\s*/\s*л|ммоль\s*/\s*л|г\s*/\s*л|г/дл|мг/дл|мг/л|мкг/л|нг/мл|нг/л|пг/мл|пг/л|млн/мкл|тыс/мкл|10\^?9/л|10\^?12/л|мЕд/л|мМЕ/л|МЕ/л|фл|пг|%|ед/л|U/L|mg/dL|mmol/L|µmol/L|ng/mL|pg/mL)?", re.IGNORECASE)
DATE_RE = re.compile(r"\b(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2})\b")
PAGE_RE = re.compile(r"---\s*Страница\s+(\d+)\s*---", re.IGNORECASE)


def _matched_types(text):
    lowered = (text or "").lower()
    scores = {label: sum(len(re.findall(pattern, lowered, re.IGNORECASE)) for pattern in patterns)
              for label, patterns in TYPE_PATTERNS.items()}
    scores = {label: score for label, score in scores.items() if score}
    return sorted(scores, key=lambda label: (-scores[label], list(TYPE_PATTERNS).index(label))), scores


def _analyse_pages(text):
    matches = list(PAGE_RE.finditer(text or ""))
    if not matches:
        types, _ = _matched_types(text)
        return [{"page": 1, "types": types}] if (text or "").strip() else []
    result = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        types, _ = _matched_types(text[match.end():end])
        if types:
            result.append({"page": int(match.group(1)), "types": types})
    return result


def _extract_lab_results(text):
    results, seen, page = [], set(), 1
    for line in (text or "").splitlines():
        marker = PAGE_RE.search(line)
        if marker:
            page = int(marker.group(1))
            continue
        clean = " ".join(line.split()).strip(" \t•·-")
        if not clean or len(clean) > 500:
            continue
        for label, pattern in LAB_MARKERS.items():
            if not re.search(pattern, clean, re.IGNORECASE):
                continue
            match = VALUE_RE.search(clean)
            value = match.group(1).replace(" ", "") if match else None
            unit = match.group(2) if match and match.group(2) else None
            key = (label, value, unit, page, clean)
            if key not in seen:
                seen.add(key)
                results.append({"name": label, "value": value, "unit": unit, "page": page, "source": clean[:240]})
            break
        if len(results) >= 150:
            break
    return results


def _extract_lines(text, patterns, limit=30):
    found, seen, page = [], set(), 1
    for line in (text or "").splitlines():
        marker = PAGE_RE.search(line)
        if marker:
            page = int(marker.group(1))
            continue
        clean = " ".join(line.split()).strip(" \t•·-")
        if not clean or len(clean) > 500:
            continue
        if any(re.search(pattern, clean, re.IGNORECASE) for pattern in patterns):
            key = (page, clean.lower())
            if key not in seen:
                seen.add(key)
                found.append({"page": page, "text": clean[:240]})
        if len(found) >= limit:
            break
    return found


def analyze_document(text):
    """Classify the whole file and pages; extract candidate facts with source page/line."""
    text = text or ""
    types, scores = _matched_types(text)
    page_markers = list(PAGE_RE.finditer(text))
    if page_markers:
        page_start = page_markers[0].end()
        page_end = page_markers[1].start() if len(page_markers) > 1 else len(text)
        header_text = text[page_start:min(page_end, page_start + 1800)]
    else:
        header_text = text[:1800]
    head_types, _ = _matched_types(header_text)
    primary = head_types[0] if head_types else (types[0] if types else "документ")
    labs = _extract_lab_results(text)
    diagnoses = _extract_lines(text, [r"\bдиагноз\b", r"\bосновной диагноз\b", r"\bзаключительный диагноз\b"])
    medications = _extract_lines(text, [r"\bназначен\w*\b", r"\bпринимать\b", r"\bпрепарат\b", r"\bлекарственн\w+\s+средств", r"\bдозировк\w*\b", r"\bмг\s*/\s*сут\b"])
    dates = list(dict.fromkeys(DATE_RE.findall(text)))[:50]
    page_types = _analyse_pages(text)
    confidence = "low" if len(text.strip()) < 40 or primary == "документ" else "medium"
    summary = []
    if labs:
        summary.append(f"строк лабораторных показателей: {len(labs)}")
    if diagnoses:
        summary.append(f"строк с диагнозами: {len(diagnoses)}")
    if medications:
        summary.append(f"строк о назначениях/препаратах: {len(medications)}")
    return {"schema_version": 1, "primary_type": primary, "types": types, "page_types": page_types,
            "lab_results": labs, "diagnoses": diagnoses, "medications": medications, "dates": dates,
            "confidence": confidence, "signals": scores, "summary": "; ".join(summary)}


def classify_document(text, hf_token=None):
    """Backwards-compatible API."""
    return analyze_document(text)["primary_type"]


def extract_keywords(text, analysis=None):
    analysis = analysis or analyze_document(text)
    candidates = list(analysis.get("types", []))
    candidates += [item.get("name", "") for item in analysis.get("lab_results", [])]
    candidates += [item.get("text", "") for item in analysis.get("diagnoses", [])]
    candidates += [item.get("text", "") for item in analysis.get("medications", [])]
    if not candidates:
        candidates = re.findall(r"[\wА-Яа-яЁё-]{5,}", (text or "").lower())
    stop = {"этого", "этот", "того", "при", "для", "или", "что", "также", "который"}
    result, seen = [], set()
    for candidate in candidates:
        for word in re.findall(r"[\wА-Яа-яЁё-]{4,}", str(candidate).lower()):
            if word not in stop and word not in seen:
                seen.add(word)
                result.append(word)
                if len(result) >= 80:
                    return result
    return result


def answer_question(query, patient, hf_token, context=""):
    """Answer from selected archive context only; this is not medical advice."""
    if not context:
        return "В архиве нет подходящих документов. Сначала загрузите документы пациента."
    if not hf_token:
        return "Не задан HF_API_TOKEN. Поиск работает, но ИИ не настроен."
    system = ("Ты медицинский информационный помощник. Отвечай по-русски только на основе предоставленных "
              "источников. Не ставь диагнозов и не выдумывай значения, даты или назначения. Указывай имя источника, "
              "страницу и дату, если доступны. Разделяй факты и предположения. Не назначай, не отменяй и не меняй "
              "лечение; предложи обсудить лечебные решения с врачом. Если данных недостаточно, сообщи об этом.")
    model = os.getenv("HF_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    url = os.getenv("HF_CHAT_COMPLETIONS_URL", "https://router.huggingface.co/v1/chat/completions")
    try:
        response = requests.post(url, headers={"Authorization": f"Bearer {hf_token}"}, json={
            "model": model, "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"Вопрос: {query}\nДокументы из выбранного семейного архива:\n{context[:18000]}"},
            ], "temperature": 0.1, "max_tokens": 1200
        }, timeout=90)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        return f"Не удалось получить ответ ИИ ({type(exc).__name__}). Проверьте настройки модели."
