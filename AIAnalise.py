"""Explainable rule-based classification for Russian family medical archives.
Document form is separated from clinical content tags. Weak evidence yields "не определено".
Extracted values/snippets are search aids only, never clinical conclusions.
"""
import os
import re
from difflib import SequenceMatcher
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
        (r"\bмрт\b", 3, "слабый маркер МРТ"),
    ],
    "заключение функциональной диагностики": [
        (r"\b(?:заключение|протокол|результат\w*|результаты)\s+(?:ээг|электроэнцефалограмм\w*|эхокг|эхокардиографи\w*|холтеровск\w+\s+мониторировани\w*|суточн\w+\s+мониторировани\w*|спирометр\w*|спирографи\w*)", 10, "заголовок функционального исследования"),
        (r"\b(?:электроэнцефалограмм\w*|эхокардиографи\w*|холтеровск\w+\s+мониторировани\w*|спирометр\w*|спирографи\w*)\b", 9, "метод функциональной диагностики"),
        (r"\b(?:ээг|эхокг)\b", 8, "сокращение функционального исследования"),
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
        (r"\bнаправлени\w+\s+на\s+медицинск\w+\s+обследовани\w*", 11, "направление на медицинское обследование"),
        (r"\bнаправлени\w+\s+на\s+диагностическ\w+\s+исследовани\w*", 11, "направление на диагностическое исследование"),
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
        (r"\bдневник\s+(?:наблюдени\w*|пациент\w*|динамическ\w+\s+наблюдени\w*)\b", 8, "дневник наблюдения или динамического наблюдения"),
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


# Conservative typo tolerance applies only to the opening lines, where form
# headings usually live. It must not "correct" clinical values or body text.
FUZZY_HEADER_ANCHORS = {
    "выписной эпикриз": ("выписной эпикриз", "выписка из стационара"),
    "лабораторный отчёт": ("результаты лабораторных исследований", "общий анализ крови",
                           "общий анализ мочи", "биохимический анализ"),
    "заключение УЗИ": ("заключение узи", "протокол узи", "протокол ультразвукового исследования"),
    "заключение ЭКГ": ("заключение экг", "протокол экг", "электрокардиограмма"),
    "рентгенологическое заключение": ("заключение рентгена", "протокол рентгена",
                                      "рентгенологическое исследование"),
    "заключение КТ": ("заключение кт", "протокол кт", "компьютерная томография"),
    "заключение МРТ": ("заключение мрт", "протокол мрт", "магнитно-резонансная томография"),
    "заключение функциональной диагностики": (
        "заключение ээг", "протокол ээг", "заключение эхокг",
        "протокол эхокг", "заключение спирометрии",
    ),
    "консультация специалиста": ("консультация врача", "консультация невролога",
                                  "консультация педиатра", "заключение специалиста"),
    "назначение или рецепт": ("лист назначений", "рецептурный бланк", "схема лечения"),
    "медицинская справка": ("медицинская справка",),
    "вакцинальный документ": ("прививочная карта", "сертификат вакцинации"),
    "операционный протокол": ("операционный протокол", "протокол операции"),
    "эндоскопическое заключение": ("заключение эндоскопии", "протокол эндоскопии",
                                   "протокол гастроскопии", "протокол колоноскопии"),
    "патоморфологическое заключение": ("патоморфологическое заключение",
                                       "гистологическое заключение"),
    "направление": ("медицинское направление", "направление на обследование",
                    "направление на исследование"),
    "протокол осмотра или приёма": ("протокол осмотра", "протокол приёма",
                                    "первичный приём врача"),
}


def _fuzzy_header_matches(text):
    header = _normalize((text or "").splitlines()[0] if (text or "").splitlines() else "")
    if not header:
        return []
    # OCR/keyboarding can mix visually identical Latin and Cyrillic glyphs.
    # Apply this only to heading comparison; never mutate source text or values.
    confusables = str.maketrans({
        "a": "а", "c": "с", "e": "е", "o": "о", "p": "р",
        "x": "х", "y": "у", "k": "к", "m": "м", "r": "р", "t": "т",
        "b": "в", "h": "н",
    })
    header = header.translate(confusables)

    # Strong, modality-anchored recovery: tolerate OCR damage in "заключение"
    # or "протокол" only when a modality token occurs in the same short heading.
    # This avoids confusing "направление на МРТ" with an MRI report.
    modality_headers = (
        ("заключение УЗИ", r"\bузи\b"),
        ("заключение ЭКГ", r"\bэкг\b"),
        ("рентгенологическое заключение", r"\bрентген\w*\b"),
        ("заключение КТ", r"\bкт\b"),
        ("заключение МРТ", r"\bмрт\b"),
        ("эндоскопическое заключение", r"\b(?:фгдс|гастроскопи\w*|колоноскопи\w*|эндоскопи\w*)\b"),
    )
    for label, modality_pattern in modality_headers:
        modality = re.search(modality_pattern, header)
        if not modality:
            continue
        prefix = re.sub(r"[^а-я]", "", header[:modality.start()])
        for marker in ("заключение", "протокол"):
            # Prefix length is bounded so "заключение врача ... МРТ" cannot
            # accidentally masquerade as a radiology-report heading.
            if len(marker) - 2 <= len(prefix) <= len(marker) + 2:
                similarity = SequenceMatcher(None, prefix, marker).ratio()
                if similarity >= 0.80:
                    return [(label, similarity)]
    # OCR can split a word with an accidental space. Generate a second,
    # conservative comparison form only for the heading matcher.
    compact_header = re.sub(r"(?<=[а-я])\s+(?=[а-я])", "", header)
    # Compare contiguous 1-5 word spans, not arbitrary body text. A minimum
    # length and high threshold reduce accidental matches on short abbreviations.
    words = re.findall(r"[а-яa-z0-9-]+", header)
    spans = []
    for start in range(len(words)):
        for width in range(1, min(5, len(words) - start) + 1):
            span = " ".join(words[start:start + width])
            if len(span.replace(" ", "")) >= 9:
                spans.append(span)
    compact_words = re.findall(r"[а-яa-z0-9-]+", compact_header)
    for start in range(len(compact_words)):
        for width in range(1, min(5, len(compact_words) - start) + 1):
            span = " ".join(compact_words[start:start + width])
            if len(span.replace(" ", "")) >= 9:
                spans.append(span)
    matches = []
    for label, anchors in FUZZY_HEADER_ANCHORS.items():
        normalized_anchors = [_normalize(anchor).translate(confusables) for anchor in anchors]
        best = max((SequenceMatcher(None, span, anchor).ratio()
                    for span in spans for anchor in normalized_anchors), default=0)
        if best >= 0.88:
            matches.append((label, best))
    # Similar long headings can make a shorter label look almost as close
    # (e.g. "заключение МРТ" vs "заключение КТ"). Keep only a clear winner;
    # ambiguous fuzzy matches must abstain rather than add both document types.
    matches.sort(key=lambda item: item[1], reverse=True)
    if len(matches) > 1 and matches[0][1] - matches[1][1] < 0.05:
        return []
    return matches[:1]


def _classify_segment(text):
    scores, evidence = _score_types(text)
    normalized = _normalize(text)

    # Fuzzy OCR matching is a fallback. Do not add a competing imaging type
    # when the opening lines already contain a clear exact imaging heading.
    exact_header_text = _normalize("\n".join((text or "").splitlines()[:2]))
    exact_header_scores, _ = _score_types(exact_header_text)
    imaging_labels = (
        "заключение УЗИ", "заключение ЭКГ", "рентгенологическое заключение",
        "заключение КТ", "заключение МРТ", "эндоскопическое заключение",
    )
    exact_imaging_heading = any(exact_header_scores.get(label, 0) >= 9 for label in imaging_labels)
    for label, similarity in _fuzzy_header_matches(text):
        if similarity >= 0.88 and not (exact_imaging_heading and label in imaging_labels
                                       and exact_header_scores.get(label, 0) < 9):
            scores[label] = max(scores.get(label, 0), 10)
            evidence.setdefault(label, []).append({
                "weight": 10,
                "reason": f"приближённое совпадение заголовка ({similarity:.2f})",
            })

    # Classify the document's form, not every medical topic mentioned in its body.
    # In particular, a requested future investigation is not its resulting report.
    referral_context = bool(re.search(
        r"\b(?:направлени\w*\s+(?:на|к)\b|направляется\s+на\b|"
        r"просим\s+(?:выполнить|провести)\b|цель\s+направлени\w*|"
        r"для\s+прохождения\s+(?:узи|мрт|кт|рентген\w*))", normalized))
    future_test_context = bool(re.search(
        r"\b(?:рекомендован\w*|рекомендовал\w*|направлен\w*|"
        r"выполнить|пройти|записаться|при\s+необходимости|планируется|"
        r"просим\s+(?:выполнить|провести)|назначено\s+(?:провести|выполнить))\b",
        normalized))
    # "Просим выдать протокол" in a referral is not evidence that a protocol exists.
    report_heading = bool(re.search(
        r"\b(?:заключение|протокол)\s+(?:узи|ультразвуков\w+\s+исследовани\w*|"
        r"экг|электрокардиограмм\w*|мрт|магнитно[- ]резонансн\w+\s+томографи\w*|"
        r"кт|компьютерн\w+\s+томографи\w*|рентген\w*|рентгенографи\w*|"
        r"гастроскопи\w*|колоноскопи\w*|эндоскопи\w*)\b",
        exact_header_text))
    fuzzy_imaging_heading = any(
        label in (
            "заключение УЗИ", "заключение ЭКГ", "рентгенологическое заключение",
            "заключение КТ", "заключение МРТ", "эндоскопическое заключение",
        )
        for label, _ in _fuzzy_header_matches(text)
    )
    standalone_imaging_title = (
        len((text or "").splitlines()) == 1
        and bool(re.fullmatch(
            r"\s*(?:узи|мрт|кт|экг)\s+[\w-]+(?:\s+[\w-]+){0,5}\s*",
            (text or "").strip(), re.IGNORECASE
        ))
    )
    report_content_signal = bool(re.search(
        r"\b(?:результат\w*\s+исследовани\w*|описание\s+(?:исследовани\w*|снимк\w*)|"
        r"исследовани\w*\s+(?:выполнено|проведено)|"
        r"(?:выполнено|проведено)\s+(?:узи|мрт|кт|рентген\w*|исследовани\w*)|"
        r"заключение\s*:\s*(?:признак\w*|данных\s+за|без\s+особенностей|"
        r"эхографическ\w*|кт-картин\w*|мр-картин\w*|синусов\w+\s+ритм))",
        normalized))
    report_context = report_heading or fuzzy_imaging_heading or standalone_imaging_title or (report_content_signal and not referral_context)
    imaging_labels = (
        "заключение УЗИ", "заключение ЭКГ", "рентгенологическое заключение",
        "заключение КТ", "заключение МРТ", "эндоскопическое заключение",
    )
    # An explicit modality in the opening lines wins over incidental references
    # to other modalities in the body.
    explicit_header_modalities = [
        label for label in imaging_labels if exact_header_scores.get(label, 0) >= 9
    ]
    if explicit_header_modalities:
        winner = max(explicit_header_modalities, key=lambda label: exact_header_scores[label])
        for label in imaging_labels:
            if label != winner:
                scores.pop(label, None)
                evidence.pop(label, None)
    elif not report_context and not any(score >= 9 for score in exact_header_scores.values()):
        # Bare lists of medical terms are not imaging reports; abstain unless
        # there is a report heading, result-like context, or strong exact title.
        for label in imaging_labels:
            scores.pop(label, None)
            evidence.pop(label, None)
    if referral_context and not report_context:
        scores["направление"] = max(scores.get("направление", 0), 12)
        evidence.setdefault("направление", []).append(
            {"weight": 12, "reason": "контекст направления на будущее исследование"})
    if future_test_context and not report_context:
        for label in (
            "заключение УЗИ", "заключение ЭКГ", "рентгенологическое заключение",
            "заключение КТ", "заключение МРТ", "эндоскопическое заключение",
        ):
            scores.pop(label, None)
            evidence.pop(label, None)

    # A planned lab test in the plan section must not turn a visit note into a lab report.
    visit_heading = bool(re.search(
        r"\b(?:протокол\s+)?(?:первичн\w*|повторн\w*)\s+при[её]м\w*|"
        r"протокол\s+осмотра|амбулаторн\w+\s+при[её]м", normalized))
    # Only the document's opening lines can establish its form. A test listed
    # later in a visit plan is not a laboratory result document.
    header_text = _normalize("\n".join((text or "").splitlines()[:2]))
    lab_report_heading = bool(re.search(
        r"\b(?:общ\w+\s+анализ\w*\s+(?:крови|мочи)|"
        r"биохимическ\w+\s+анализ|результат\w*\s+лабораторн\w+\s+исследовани\w*)\b",
        header_text))
    if visit_heading and not lab_report_heading:
        scores.pop("лабораторный отчёт", None)
        evidence.pop("лабораторный отчёт", None)

    # A planned or explicitly absent histology result is not a pathology report.
    # Keep a genuine pathology-report heading authoritative, but do not let a
    # consultation mention of a missing future/past result win by keyword score.
    pathology_report_heading = bool(re.search(
        r"\b(?:патоморфологическ\w+\s+заключени\w*|гистологическ\w+\s+заключени\w*|"
        r"цитологическ\w+\s+заключени\w*)\b",
        header_text))
    pathology_result_absent = bool(re.search(
        r"(?:результат\w*\s+гистологическ\w+\s+исследовани\w*|"
        r"гистологическ\w+\s+результат\w*|результат\w*\s+биопси\w*)"
        r".{0,100}\b(?:отсутств\w*|не\s+(?:получен\w*|готов\w*|выполнен\w*|провед\w*)|"
        r"ожидает\w*|ожидается|будет\s+(?:выполнен\w*|готов\w*|получен\w*))\b",
        normalized))
    if pathology_result_absent and not pathology_report_heading:
        scores.pop("патоморфологическое заключение", None)
        evidence.pop("патоморфологическое заключение", None)

    # A document-type mention explicitly negated in a disclaimer is not evidence
    # that the current file belongs to that type.
    negative_type_patterns = {
        "выписной эпикриз": r"не\s+(?:(?:является|содержит|представляет)\b.{0,200}\b)?(?:выписн\w*\s+эпикриз|эпикриз)\b",
        "медицинская справка": r"не\s+(?:(?:является|содержит|представляет)\b.{0,200}\b)?медицинск\w*\s+справк",
        "направление": r"не\s+(?:(?:является|содержит|представляет)\b.{0,200}\b)?направлени\w*",
        "заключение УЗИ": r"не\s+(?:(?:является|содержит|представляет)\b.{0,200}\b)?(?:заключени\w*|протокол\w*)\s+(?:узи|ультразвуков\w*)",
        "заключение МРТ": r"не\s+(?:(?:является|содержит|представляет)\b.{0,200}\b)?(?:заключени\w*|протокол\w*)\s+(?:мрт|магнитно[- ]резонансн\w*)",
                "назначение или рецепт": r"\bне\s+(?:(?:является|содержит|представляет|оформля\w*|составля\w*|выдава\w*)\b.{0,160}\b)?(?:рецепт\w*|лист\s+назначени\w*|назначени\w+\s+(?:лекарственн\w+|препарат\w*))\b",
"лабораторный отчёт": r"\bне\s+(?:(?:является|содержит|представляет|оформля\w*|составля\w*)\b.{0,200}\b)?(?:лабораторн\w+\s+отч[её]т|(?:отдельн\w+\s+)?результат\w*\s+(?:анализ\w*|лабораторн\w+\s+исследовани\w*))",
    }
    for label, pattern in negative_type_patterns.items():
        if re.search(pattern, normalized):
            scores.pop(label, None)
            evidence.pop(label, None)

    # Instructions that mention an existing prescription are not prescriptions.
    prescription_heading = bool(re.search(
        r"\b(?:рецепт|лист\s+назначени\w*|назначени\w+\s+(?:лекарственн\w+|препарат\w+))\b",
        header_text))
    advice_about_existing_meds = bool(re.search(
        r"\b(?:не\s+отменяйте|не\s+прекращайте|не\s+меняйте|не\s+изменяйте|обсудите\s+с\s+врачом)\b.{0,100}\b"
        r"(?:назначенн\w*\s+препарат\w*|лекарств\w*|препарат\w*)",
        normalized))
    if advice_about_existing_meds and not prescription_heading:
        scores.pop("назначение или рецепт", None)
        evidence.pop("назначение или рецепт", None)

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
