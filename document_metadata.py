"""Metadata extraction for safe automatic medical-archive filing."""
import datetime
import re
from pathlib import Path

_DATE = r"(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})"
_DATE_RE = re.compile(rf"(?<!\d)(?P<date>{_DATE})(?!\d)")
_FINAL_DATE_RE = re.compile(
    rf"(?P<label>дата\s+(?:заключения|оформления|выдачи|составления|документа|подписания|"
    rf"формирования|готовности|печати|регистрации|подготовки|результата|отчёта|отчета|"
    rf"при[её]ма|осмотра|консультации|посещения|выписки)|"
    rf"документ\s+от|заключение\s+от|протокол\s+от|результат(?:ы)?\s+от|отч[её]т\s+от|выдано?\s*[:\-]?)"
    rf"[^\d]{{0,35}}(?P<date>{_DATE})", re.IGNORECASE)
_GENERIC_DATE_RE = re.compile(rf"дата\s*[:\-]\s*(?P<date>{_DATE})", re.IGNORECASE)
_NON_DOCUMENT_DATE_RE = re.compile(
    r"дата\s+(?:исследовани[яе]|проведения|выполнения|узи|экг|мрт|кт|рентгенографии|"
    r"рождения|забора|взятия|сдачи|госпитализации|поступления|вакцинации|прививки|начала лечения)|"
    r"исследование\s+от|исследовани[ея]\s+(?:выполнен[аоы]?|проведен[аоы]?|проводил[аоось]*|выполнение)|"
    r"(?:узи|экг|мрт|кт|рентгенографи\w*|исследовани\w*)\s+(?:выполнен[аоы]?|проведен[аоы]?|проводил[аоось]*)|(?:выполнен[аоы]?|проведен[аоы]?|проводил[аоось]*)\s+(?:узи|экг|мрт|кт|рентгенографи\w*|исследовани\w*)|"
    r"забор\s+(?:крови|материала)|дата\s+последн[ейя]\s+менструации", re.IGNORECASE)

def _normalise_date(raw):
    raw = (raw or "").strip()
    try:
        if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", raw):
            year, month, day = map(int, raw.split("-"))
        else:
            day, month, year = map(int, re.split(r"[./-]", raw))
            if year < 100:
                year += 2000
        return datetime.date(year, month, day).strftime("%d-%m-%Y")
    except (ValueError, TypeError):
        return None

def extract_document_date(text):
    """Extract date of the final document, not the date of the study."""
    text = text or ""
    labelled = {}
    for match in _FINAL_DATE_RE.finditer(text):
        date = _normalise_date(match.group("date"))
        if not date:
            continue
        label = match.group("label").lower()
        if "заключен" in label or "документ" in label:
            score = 12
        elif any(word in label for word in ("оформлен", "составлен", "подписан")):
            score = 10
        elif any(word in label for word in ("выдач", "выдан", "формирован", "готовност", "печати", "регистрац", "подготовк")):
            score = 9
        else:
            score = 7
        labelled.setdefault(date, []).append(score)
    for match in _GENERIC_DATE_RE.finditer(text):
        date = _normalise_date(match.group("date"))
        if not date:
            continue
        # This expression matches the literal generic label "Дата:", not
        # labels such as "Дата исследования". Previous fields on the same page
        # must not suppress an explicit later document date.
        labelled.setdefault(date, []).append(5)
    if labelled:
        best = max(max(scores) for scores in labelled.values())
        winners = [date for date, scores in labelled.items() if max(scores) == best]
        return winners[0] if len(winners) == 1 else None
    candidates = set()
    for match in _DATE_RE.finditer(text):
        date = _normalise_date(match.group("date"))
        if not date:
            continue
        context = text[max(0, match.start()-70):min(len(text), match.end()+25)]
        if not _NON_DOCUMENT_DATE_RE.search(context):
            candidates.add(date)
    return next(iter(candidates)) if len(candidates) == 1 else None

def _normalise_words(value):
    value = (value or "").casefold().replace("ё", "е")
    return re.sub(r"[^\w]+", " ", value, flags=re.UNICODE).strip()

def _patient_alias_variants(alias):
    normalized = _normalise_words(alias)
    words = normalized.split()
    variants = set()
    if not words:
        return variants
    variants.add(normalized)
    if len(words) >= 3:
        surname, given, patronymic = words[0], words[1], words[2]
        first_initial, patronymic_initial = given[:1], patronymic[:1]
        variants.update({
            f"{surname} {given}", f"{surname} {given} {patronymic_initial}",
            f"{surname} {first_initial} {patronymic_initial}",
            f"{surname} {first_initial}", f"{surname} {first_initial} {patronymic}",
            f"{given} {surname}", given,
        })
    elif len(words) == 2:
        first, second = words
        variants.update({f"{first} {second[:1]}", f"{first[:1]} {second}", f"{second} {first}", first})
    return {v for v in variants if v}

def extract_registered_patient(text, patients):
    """Resolve a registered patient label from full/abbreviated names conservatively.

    patients accepts legacy strings or records containing name and aliases.
    Stored aliases should be encrypted at rest; only the short display name is returned.
    Single first names match only in a patient-labelled field or as a standalone
    line in the header, never from incidental narrative mentions.
    """
    raw = text or ""
    normalized = _normalise_words(raw)
    header_lines = {
        _normalise_words(line)
        for line in raw.splitlines()[:12]
        if _normalise_words(line) and len(line) < 120
    }
    patient_scores = {}
    for entry in patients or []:
        if isinstance(entry, dict):
            display_name = str(entry.get("name") or "").strip()
            aliases = list(entry.get("aliases") or []) + [display_name]
        else:
            display_name = str(entry or "").strip()
            aliases = [display_name]
        if not display_name:
            continue
        best = None
        seen_variants = set()
        for alias in aliases:
            for variant in _patient_alias_variants(str(alias)):
                if variant in seen_variants:
                    continue
                seen_variants.add(variant)
                words = variant.split()
                pattern = r"(?<!\w)" + r"\s+".join(re.escape(part) for part in words) + r"(?!\w)"
                for match in re.finditer(pattern, normalized):
                    before = normalized[max(0, match.start()-100):match.start()]
                    after = normalized[match.end():min(len(normalized), match.end()+55)]
                    explicit = bool(re.search(
                        r"(?:пациент(?:а|ка)?|фио пациента|данные пациента|пациентское имя)\s*$",
                        before))
                    nonpatient = bool(re.search(
                        r"(?:мать|отец|мама|папа|родител[а-я]*|представител[а-я]*|"
                        r"врач[а-я]*|специалист[а-я]*|медицинск[а-я]* сестр[а-я]*|"
                        r"подписал[а-я]*|фио матери|фио отца)\s*$", before))
                    nonpatient = nonpatient or bool(re.match(
                        r"\s*(?:врач|специалист|мать|отец|родител|представител)", after))
                    if nonpatient and not explicit:
                        continue
                    standalone = len(words) == 1 and variant in header_lines
                    if len(words) == 1 and not (explicit or standalone):
                        continue
                    score = len(words)*20 + (100 if explicit else 0) + (30 if standalone else 0)
                    if best is None or score > best["score"]:
                        best = {"score": score, "explicit": explicit, "variant": variant}
        if best:
            patient_scores[display_name] = max(best["score"], patient_scores.get(display_name, 0))
    if not patient_scores:
        return None
    best_score = max(patient_scores.values())
    winners = [name for name, score in patient_scores.items() if score == best_score]
    return winners[0] if len(winners) == 1 else None

_UZI_SUBJECTS = [
    (r"\bмалого\s+таза\b", "УЗИ малого таза"),
    (r"\bщитовидн[а-яё]*\s+желез[аыы]\b", "УЗИ щитовидной железы"),
    (r"\bбрюшн[а-яё]*\s+полост[иь]\b", "УЗИ брюшной полости"),
    (r"\bмолочн[а-яё]*\s+желез[аыы]\b", "УЗИ молочных желёз"),
    (r"\bпочек\b", "УЗИ почек"), (r"\bсердц[ао]\b", "УЗИ сердца"),
    (r"\bсустав[а-яё]*\b", "УЗИ суставов"), (r"\bсосуд[а-яё]*\b", "УЗИ сосудов"),
    (r"\bмошонк[а-яё]*\b", "УЗИ мошонки"),
    (r"\bтазобедренн[а-яё]*\s+сустав[а-яё]*\b", "УЗИ тазобедренных суставов"),
]
_BODY_REGIONS = [
    (r"\bпояснично[- ]крестцов[а-яё]*\s+отдел[а-яё]*\b|\bпоясничн[а-яё]*\s+отдел[а-яё]*\b", "поясничного отдела"),
    (r"\bшейн[а-яё]*\s+отдел[а-яё]*\b", "шейного отдела"),
    (r"\bгрудн[а-яё]*\s+отдел[а-яё]*\b", "грудного отдела"),
    (r"\bпозвоночник[а-яё]*\b", "позвоночника"),
    (r"\bголовн[а-яё]*\s+мозг[а-яё]*\b", "головного мозга"),
    (r"\bорган[а-яё]*\s+малого\s+таза\b|\bмалого\s+таза\b", "органов малого таза"),
    (r"\bбрюшн[а-яё]*\s+полост[иь]\b", "органов брюшной полости"),
    (r"\bгрудн[а-яё]*\s+клетк[иу]\b", "органов грудной клетки"),
    (r"\bоколоносов[а-яё]*\s+пазух[и]\b", "околоносовых пазух"),
    (r"\bтазобедренн[а-яё]*\s+сустав[а-яё]*\b", "тазобедренного сустава"),
    (r"\bколенн[а-яё]*\s+сустав[а-яё]*\b", "коленного сустава"),
    (r"\bстоп[а-яё]*\b", "стопы"),
    (r"\bкист[иь]\b", "кисти"),
]
_TYPE_TITLES = {
    "заключение УЗИ": "УЗИ", "заключение ЭКГ": "ЭКГ",
    "рентгенологическое заключение": "Рентген",
    "заключение КТ": "КТ", "заключение МРТ": "МРТ",
    "лабораторный отчёт": "Лабораторный анализ",
    "выписной эпикриз": "Выписной эпикриз",
    "выписка из медицинской карты": "Выписка из медицинской карты",
    "консультация специалиста": "Консультация специалиста",
    "назначение или рецепт": "Назначение или рецепт",
    "медицинская справка": "Медицинская справка",
    "направление": "Направление",
    "эндоскопическое заключение": "Эндоскопия",
    "патоморфологическое заключение": "Патоморфология",
    "операционный протокол": "Протокол операции",
}

def infer_document_title(text, kind):
    """Compact file label with a recognised modality, anatomical region or specialty."""
    head = (text or "")[:2200].replace("ё", "е")
    if kind == "заключение УЗИ":
        for pattern, title in _UZI_SUBJECTS:
            if re.search(pattern, head, re.IGNORECASE):
                return title
        return "УЗИ"
    if kind == "лабораторный отчёт":
        lab_titles = [
            (r"общ[а-яё]*\s+анализ[а-яё]*\s+крови", "Общий анализ крови"),
            (r"общ[а-яё]*\s+анализ[а-яё]*\s+мочи", "Общий анализ мочи"),
            (r"биохимическ[а-яё]*\s+анализ[а-яё]*\s+крови", "Биохимический анализ крови"),
            (r"коагулограмм[а-яё]*", "Коагулограмма"),
            (r"\bпцр\b|\bполимеразн[а-яё]*\s+цепн[а-яё]*\s+реакц[а-яё]*", "ПЦР-анализ"),
            (r"\bферритин\b", "Анализ на ферритин"),
        ]
        for pattern, title in lab_titles:
            if re.search(pattern, head, re.IGNORECASE):
                return title
        return "Лабораторный анализ"
    if kind in {"заключение КТ", "заключение МРТ", "рентгенологическое заключение"}:
        prefix = {"заключение КТ": "КТ", "заключение МРТ": "МРТ",
                  "рентгенологическое заключение": "Рентген"}[kind]
        for pattern, region in _BODY_REGIONS:
            if re.search(pattern, head, re.IGNORECASE):
                return f"{prefix} — {region}"
        return prefix
    if kind == "консультация специалиста":
        for spec in ("невролог", "кардиолог", "педиатр", "терапевт", "офтальмолог",
                     "эндокринолог", "хирург", "ортопед", "гинеколог", "уролог",
                     "гастроэнтеролог", "пульмонолог", "дерматолог", "логопед"):
            if re.search(r"\b" + spec + r"[а-яё]*\b", head, re.IGNORECASE):
                return "Консультация " + spec
    if kind == "эндоскопическое заключение":
        for pattern, title in (
            (r"\b(?:фгдс|эзофагогастродуоденоскопи|гастроскопи)[а-яё]*\b", "ФГДС"),
            (r"\bколоноскопи[а-яё]*\b", "Колоноскопия"),
            (r"\bбронхоскопи[а-яё]*\b", "Бронхоскопия"),
        ):
            if re.search(pattern, head, re.IGNORECASE):
                return title
    return _TYPE_TITLES.get(kind, kind[:1].upper()+kind[1:] if kind else "Медицинский документ")


def format_archive_filename(date_str, title, extension, digest):
    """Readable, collision-resistant filename; patient is represented by its folder."""
    ext = (Path(extension or "").suffix or extension or "bin").lstrip(".").lower()
    ext = re.sub(r"[^a-z0-9]+", "", ext) or "bin"
    clean = re.sub(r"[^\w -]+", " ", title or "", flags=re.UNICODE)
    clean = re.sub(r"\s+", " ", clean).strip(" -")[:90] or "Медицинский документ"
    date_part = (date_str or "Дата не определена").replace("/", "-")
    return f"{date_part} {clean} — {str(digest or '')[:8]}.{ext}"

[executed on device: marss1k.fvds.ru (ecc850ae-e012-4a56-b726-1ade67f14bec)]