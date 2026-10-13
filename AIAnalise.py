"""Explainable rule-based classification for Russian family medical archives.
Document form is separated from clinical content tags. Weak evidence yields "не определено".
Extracted values/snippets are search aids only, never clinical conclusions.
"""
import os
import re
import requests

CLASSIFICATION_VERSION = "2.0"
DOCUMENT_TYPE_RULES = {
    "выписной эпикриз": [
        (r"\bвыписн\w*\s+эпикриз\b", 10, "заголовок: выписной эпикриз"),
        (r"\bэпикриз\b", 8, "термин «эпикриз»"),
        (r"\bвыписк\w+\s+из\s+(?:стационар\w+|истори\w+\s+болезни)\b", 9, "выписка из стационара/истории болезни"),
        (r"\bвыписан\w*\s+(?:из|со)\s+стационар\w*", 5, "указание на выписку"),
        (r"\bрекомендаци\w+\s+при\s+выписк\w*", 3, "рекомендации при выписке"),
    ],
    "лабораторный отчёт": [
        (r"\b(?:результат\w*\s+)?лабораторн\w+\s+исследован\w*", 9, "заголовок лабораторного исследования"),
        (r"\b(?:общ\w+\s+|клиническ\w+\s+)?анализ\w*\s+крови\b", 9, "анализ крови"),
        (r"\b(?:общ\w+\s+)?анализ\w*\s+мочи\b", 9, "анализ мочи"),
        (r"\bбиохимическ\w+\s+анализ\b", 9, "биохимический анализ"),
        (r"\bгемограмм\w*\b", 7, "гемограмма"),
        (r"\bрезультат\w*\s+(?:анализ\w*|исследовани\w*)\b", 6, "результаты анализов"),
        (r"\bреференсн\w+\s+значени\w*", 4, "референсные значения"),
        (r"\b(?:гемоглобин|ферритин|лейкоцит\w*|эритроцит\w*|тромбоцит\w*|гематокрит|креатинин|билирубин)\b", 1, "лабораторный показатель"),
    ],
    "заключение УЗИ": [
        (r"\b(?:протокол|заключение)\w*\s+(?:узи|ультразвуков\w+\s+исследовани\w*)", 10, "заголовок/заключение УЗИ"),
        (r"\bультразвуков\w+\s+исследовани\w*", 9, "ультразвуковое исследование"),
        (r"\bузи\b", 8, "маркер УЗИ"),
        (r"\bэхографи\w*\b|\bдопплерографи\w*\b", 7, "эхография/допплерография"),
    ],
    "заключение ЭКГ": [
        (r"\b(?:заключение|протокол)\w*\s+(?:экг|электрокардиограмм\w*)", 10, "заголовок ЭКГ"),
        (r"\bэлектрокардиограмм\w*\b", 9, "электрокардиограмма"),
        (r"\bэкг\b", 8, "маркер ЭКГ"),
        (r"\bэлектрокардиографическ\w+\s+заключени\w*", 9, "электрокардиографическое заключение"),
    ],
    "рентгенологическое заключение": [
        (r"\b(?:заключение|протокол)\w*\s+(?:рентген\w*|рентгенографи\w*)", 10, "заголовок рентгенологического исследования"),
        (r"\bрентгенографи\w*\b|\bрентгенограмм\w*\b|\bрентгенологическ\w+\s+исследовани\w*", 9, "рентгенологическое исследование"),
        (r"\bрентген\w*\b", 7, "маркер рентгена"),
    ],
    "заключение КТ": [
        (r"\b(?:заключение|протокол)\w*\s+(?:кт|компьютерн\w+\s+томографи\w*)", 10, "заголовок КТ"),
        (r"\bкомпьютерн\w+\s+томографи\w*", 9, "компьютерная томография"),
        (r"\bкт\s+(?:исследовани\w*|орган\w*|голов\w*|грудн\w*|брюшн\w*|позвоночник\w*)", 8, "контекстный маркер КТ"),
    ],
    "заключение МРТ": [
        (r"\b(?:заключение|протокол)\w*\s+(?:мрт|магнитно[- ]резонансн\w+\s+томографи\w*)", 10, "заголовок МРТ"),
        (r"\bмагнитно[- ]резонансн\w+\s+томографи\w*", 9, "магнитно-резонансная томография"),
        (r"\bмрт\b", 8, "маркер МРТ"),
    ],
    "консультация специалиста": [
        (r"\bконсультаци\w+\s+(?:врач\w+|невролог\w*|кардиолог\w*|педиатр\w*|терапевт\w*|офтальмолог\w*|эндокринолог\w*|хирург\w*|ортопед\w*|гинеколог\w*|уролог\w*|логопед\w*)", 9, "заголовок консультации специалиста"),
        (r"\bзаключение\s+(?:врача|специалиста|невролога|кардиолога|педиатра|терапевта|офтальмолога|эндокринолога|хирурга|ортопеда|гинеколога|уролога)\b", 8, "заключение специалиста"),
        (r"\bосмотр\s+(?:врача|невролога|кардиолога|педиатра|терапевта|офтальмолога|эндокринолога|хирурга|ортопеда|гинеколога|уролога)\b", 7, "осмотр специалиста"),
        (r"\bпри[её]м\s+(?:врача|невролога|кардиолога|педиатра|терапевта|специалиста)\b", 7, "приём специалиста"),
    ],
    "назначение или рецепт": [
        (r"\bлист\s+назначени\w*\b", 10, "лист назначений"),
        (r"\bрецепт\b|\bрецептурн\w+\s+бланк", 10, "рецепт"),
        (r"\bназначени\w+\s+(?:лекарственн\w+|препарат\w+)\b", 9, "назначение лекарств"),
        (r"\bсхема\s+лечени\w*\b", 7, "схема лечения"),
        (r"\bназначен\w*\s+(?:препарат|лекарств|принимать|приём|дозировк)", 6, "формулировка назначения"),
    ],
    "медицинская справка": [
        (r"\bмедицинск\w+\s+справк\w*\b", 10, "медицинская справка"),
        (r"\bсправк\w+\s+(?:выдана|выдан|о\s+состоянии|для\s+предъявления|об\s+отсутствии)", 8, "формуляр справки"),
        (r"\bмедицинск\w+\s+заключени\w+\s+для\b", 6, "медицинское заключение для предъявления"),
    ],
    "вакцинальный документ": [
        (r"\b(?:сертификат|паспорт|календарь)\w*\s+(?:профилактическ\w+\s+)?привив\w*", 10, "вакцинальный сертификат/паспорт"),
        (r"\bсертификат\s+(?:о\s+)?вакцинаци\w*", 10, "сертификат вакцинации"),
        (r"\bпрививочн\w+\s+карт\w*", 10, "прививочная карта"),
        (r"\bлист\s+профилактическ\w+\s+привив\w*", 8, "лист прививок"),
    ],
    "документ по беременности и родам": [
        (r"\bобменн\w+\s+карт\w*\b", 10, "обменная карта"),
        (r"\bистори\w+\s+родов\b|\bродов\w+\s+истори\w*", 10, "история родов"),
        (r"\bпротокол\s+родоразрешени\w*", 10, "протокол родоразрешения"),
        (r"\bбеременност\w+\s+и\s+роды\b", 9, "документ о беременности и родах"),
        (r"\bакушерск\w+\s+заключени\w*", 8, "акушерское заключение"),
        (r"\bкарта\s+беременн\w*", 8, "карта беременной"),
    ],
    "операционный протокол": [
        (r"\bпротокол\s+(?:операци\w*|хирургическ\w+\s+вмешательств\w*)\b", 10, "операционный протокол"),
        (r"\bоперационн\w+\s+протокол\w*", 10, "операционный протокол"),
        (r"\bпротокол\s+оперативн\w+\s+лечени\w*", 9, "протокол оперативного лечения"),
    ],
    "эндоскопическое заключение": [
        (r"\b(?:протокол|заключение)\w*\s+(?:гастроскопи\w*|колоноскопи\w*|эндоскопи\w*)", 10, "эндоскопическое заключение"),
        (r"\b(?:фгдс|эзофагогастродуоденоскопи\w*|колоноскопи\w*|бронхоскопи\w*)\b", 9, "эндоскопическое исследование"),
        (r"\bэндоскопическ\w+\s+исследовани\w*", 9, "эндоскопическое исследование"),
    ],
    "патоморфологическое заключение": [
        (r"\b(?:гистологическ\w+|патоморфологическ\w+|цитологическ\w+)\s+заключени\w*", 10, "морфологическое заключение"),
        (r"\bрезультат\w*\s+гистологическ\w+\s+исследовани\w*", 10, "гистологическое исследование"),
        (r"\bбиопси\w+\s+(?:материал|результат|заключени)", 8, "биопсия"),
    ],
    "направление": [
        (r"\bнаправлени\w+\s+(?:на|к)\s+(?:исследовани\w*|консультаци\w*|госпитализаци\w*|при[её]м\w*|рентген\w*|узи\b|мрт\b|кт\b)", 10, "направление на исследование/консультацию"),
        (r"\bмедицинск\w+\s+направлени\w*", 10, "медицинское направление"),
        (r"\bнаправление\s+на\s+анализ\w*", 9, "направление на анализы"),
    ],
    "протокол осмотра или приёма": [
        (r"\bпротокол\s+(?:осмотра|при[её]ма)\b", 9, "протокол осмотра/приёма"),
        (r"\bпервичн\w+\s+при[её]м\w*\b|\bповторн\w+\s+при[её]м\w*\b", 8, "первичный/повторный приём"),
        (r"\bамбулаторн\w+\s+при[её]м\b", 8, "амбулаторный приём"),
    ],
    "медицинская карта или наблюдение": [
        (r"\bмедицинск\w+\s+карт\w*\b", 9, "медицинская карта"),
        (r"\bдневник\s+(?:наблюдени\w*|пациент\w*)\b", 8, "дневник наблюдения"),
        (r"\bлист\s+динамическ\w+\s+наблюдени\w*", 8, "лист динамического наблюдения"),
    ],
}
CONTENT_RULES = {
    "диагнозы": [r"\bдиагноз\b", r"\bосновное\s+заболевание\b", r"\bзаключительный\s+диагноз\b"],
    "лекарства и назначения": [r"\bназначен\w*\b", r"\bпринимать\b", r"\bпрепарат\w*\b", r"\bлекарственн\w+\s+средств\w*\b", r"\bдозировк\w*\b", r"\bрецепт\b"],
    "вакцинация": [r"\bвакцин\w*\b", r"\bпривив\w*\b", r"\bиммунизац\w*\b"],
    "беременность и роды": [r"\bбеременност\w*\b", r"\bгестационн\w+\s+срок\b", r"\bакушер\w*\b", r"\bродов\w*\b"],
    "аллергии": [r"\bаллерги\w*\b", r"\bнепереносимост\w*\b"],
    "диагностические исследования": [r"\bузи\b", r"\bультразвуков\w+\s+исследовани\w*\b", r"\bэкг\b", r"\bэлектрокардиограмм\w*\b", r"\bрентген\w*\b", r"\bмрт\b", r"\bкт\b", r"\bтомографи\w*\b", r"\bэндоскопи\w*\b"],
    "операции и процедуры": [r"\bопераци\w*\b", r"\bхирургическ\w+\s+вмешательств\w*\b", r"\bпроцедур\w*\b"],
    "детское развитие и реабилитация": [r"\bреабилитаци\w*\b", r"\bпсихомоторн\w*\b", r"\bречев\w+\s+развити\w*\b", r"\bдвигательн\w+\s+развити\w*\b", r"\bшкал\w+\s+апгар\b"],
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
VALUE_RE = re.compile(
    r"(?<![A-Za-zА-Яа-яЁё])([<>≤≥]?\s*-?\d+(?:[.,]\d+)?)\s*"
    r"(мкмоль\s*/\s*л|ммоль\s*/\s*л|г\s*/\s*л|г/дл|мг/дл|мг/л|мкг/л|нг/мл|нг/л|пг/мл|пг/л|"
    r"млн/мкл|тыс/мкл|10\^?9/л|10\^?12/л|мЕд/л|мМЕ/л|МЕ/л|фл|пг|%|ед/л|U/L|mg/dL|mmol/L|µmol/L|ng/mL|pg/mL)?",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\b(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}-\d{2}-\d{2})\b")
PAGE_RE = re.compile(r"---\s*Страница\s+(\d+)\s*---", re.IGNORECASE)


def _normalize(text):
    return re.sub(r"\s+", " ", (text or "").replace("Ё", "Е").replace("ё", "е").lower()).strip()


def _page_chunks(text):
    matches = list(PAGE_RE.finditer(text or ""))
    if not matches:
        return [{"page": 1, "text": text or ""}] if (text or "").strip() else []
    chunks = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chunks.append({"page": int(match.group(1)), "text": text[match.end():end]})
    return chunks


def _score_types(text):
    normalized = _normalize(text)
    scores, evidence = {}, {}
    for label, rules in DOCUMENT_TYPE_RULES.items():
        hits, score = [], 0
        for pattern, weight, description in rules:
            if re.search(pattern, normalized, re.IGNORECASE):
                score += weight
                hits.append({"weight": weight, "reason": description})
        if score:
            scores[label] = score
            evidence[label] = hits
    return scores, evidence


def _classify_segment(text):
    scores, evidence = _score_types(text)
    normalized = _normalize(text)

    # A modality mentioned as a recommendation/referral is not itself a report.
    # Without report-form evidence, avoid classifying "get an MRI/US" as a result.
    mention_context = bool(re.search(
        r"\\b(?:рекомендован\\w*|рекомендовал\\w*|направлен\\w*|направление|"
        r"выполнить|пройти|записаться|при\\s+необходимости|планируется|"
        r"назначено\\s+(?:провести|выполнить))\\b", normalized))
    report_context = bool(re.search(
        r"\\b(?:протокол\\w*|заключение\\w*|результат\\w*|описание\\w*|"
        r"проведено|выполнено|данные\\s+исследования|ход\\s+исследования)\\b", normalized))
    if mention_context and not report_context:
        for label in (
            "заключение УЗИ", "заключение ЭКГ", "рентгенологическое заключение",
            "заключение КТ", "заключение МРТ", "эндоскопическое заключение",
        ):
            scores.pop(label, None)
            evidence.pop(label, None)

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    if not ranked or ranked[0][1] < 6:
        primary, confidence, document_types, margin = "не определено", "low", [], 0
    else:
        primary, top_score = ranked[0]
        second_score = ranked[1][1] if len(ranked) > 1 else 0
        margin = top_score - second_score
        if top_score >= 9 and margin >= 3:
            confidence = "high"
        elif top_score >= 7 and margin >= 2:
            confidence = "medium"
        else:
            confidence = "low"
        document_types = [label for label, score in ranked if score >= 6 and (score >= 8 or score >= top_score - 2)]
        if primary not in document_types:
            document_types.insert(0, primary)
        if confidence == "low" and top_score < 8:
            primary, document_types = "не определено", []
    normalized = _normalize(text)
    content_tags = []
    for tag, patterns in CONTENT_RULES.items():
        if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns):
            content_tags.append(tag)
    lab_hits = sum(bool(re.search(pattern, normalized, re.IGNORECASE)) for pattern in LAB_MARKERS.values())
    has_lab_heading = bool(re.search(r"\b(?:анализ\w*\s+(?:крови|мочи)|биохимическ\w+\s+анализ|результат\w*\s+лабораторн\w+)\b", normalized))
    if (lab_hits >= 2 or has_lab_heading) and "лабораторные показатели" not in content_tags:
        content_tags.append("лабораторные показатели")
    return {
        "primary_type": primary, "document_types": document_types, "content_tags": content_tags,
        "confidence": confidence, "score": ranked[0][1] if ranked else 0, "margin": margin,
        "evidence": evidence.get(primary, []) if primary != "не определено" else [],
        "type_scores": {label: score for label, score in ranked},
    }


def _analyse_pages(text):
    pages = []
    for chunk in _page_chunks(text):
        result = _classify_segment(chunk["text"])
        if result["primary_type"] != "не определено" or result["content_tags"]:
            pages.append({"page": chunk["page"], "primary_type": result["primary_type"],
                          "document_types": result["document_types"], "content_tags": result["content_tags"],
                          "confidence": result["confidence"], "evidence": result["evidence"],
                          "type_scores": result["type_scores"]})
    return pages


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
    text = text or ""
    pages = _page_chunks(text)
    page_results = [_classify_segment(p["text"]) for p in pages]
    aggregate = {}
    for result in page_results:
        for label, score in result["type_scores"].items():
            aggregate[label] = aggregate.get(label, 0) + min(score, 12)
    ranked = sorted(aggregate.items(), key=lambda item: (-item[1], item[0]))
    first = page_results[0] if page_results else _classify_segment(text)
    primary = first["primary_type"] if first["primary_type"] != "не определено" else (
        ranked[0][0] if ranked and ranked[0][1] >= 6 else "не определено")
    document_types = [label for label, score in ranked if score >= 8]
    if primary != "не определено" and primary not in document_types:
        document_types.insert(0, primary)
    content_tags = []
    for result in page_results:
        for tag in result["content_tags"]:
            if tag not in content_tags:
                content_tags.append(tag)
    labs = _extract_lab_results(text)
    diagnoses = _extract_lines(text, [r"\bдиагноз\b", r"\bосновной диагноз\b", r"\bзаключительный диагноз\b"])
    medications = _extract_lines(text, [r"\bназначен\w*\b", r"\bпринимать\b", r"\bпрепарат\w*\b",
                                        r"\bлекарственн\w+\s+средств", r"\bдозировк\w*\b", r"\bмг\s*/\s*сут\b"])
    dates = list(dict.fromkeys(DATE_RE.findall(text)))[:50]
    page_types = _analyse_pages(text)
    if primary == "не определено":
        confidence = "low"
    elif len(document_types) > 1:
        confidence = "medium" if first["confidence"] != "low" else "low"
    else:
        confidence = first["confidence"] if first["primary_type"] == primary else "medium"
    summary = []
    if labs: summary.append(f"строк лабораторных показателей: {len(labs)}")
    if diagnoses: summary.append(f"строк с диагнозами: {len(diagnoses)}")
    if medications: summary.append(f"строк о назначениях/препаратах: {len(medications)}")
    types = list(document_types)
    for tag in content_tags:
        if tag not in types: types.append(tag)
    return {
        "schema_version": 2, "classification_version": CLASSIFICATION_VERSION,
        "primary_type": primary, "document_types": document_types, "types": types,
        "content_tags": content_tags, "page_types": page_types, "lab_results": labs,
        "diagnoses": diagnoses, "medications": medications, "dates": dates,
        "confidence": confidence, "review_required": confidence == "low" or primary == "не определено",
        "type_scores": dict(ranked), "signals": {label: score for label, score in ranked},
        "summary": "; ".join(summary),
    }


def classify_document(text, hf_token=None):
    """Backward-compatible API; no external AI is used for classification."""
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
    """Optional archive Q&A; independent from document classification."""
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
