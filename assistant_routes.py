"""AI-assisted archive search for the authenticated web archive.

The LLM plans retrieval; all patient/family filtering and database access stay local.
Only bounded, relevant OCR excerpts are sent to the configured provider after explicit consent.
"""
import html
import json
import logging
import os
import re
from datetime import date, datetime
from urllib.parse import quote

import requests
from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

import database as db
import tenancy
from ai_provider import answer_archive_question, chat_completion, provider_config
import patient_memory
from document_references import discover_referenced_documents

STOP_WORDS = {
    "что", "как", "когда", "где", "почему", "какой", "какая", "какие",
    "покажи", "найди", "сравни", "сравнить", "все", "весь", "вся",
    "последний", "последние", "период", "пациент", "пациента", "документ",
    "документы", "медицинский", "медицинские", "моя", "мой", "мне", "для",
    "про", "это", "его", "ее", "него", "неё", "был", "была", "были",
    "есть", "самый", "самая", "самое", "динамику", "динамика", "изменения",
    "всех", "членов", "семьи", "семей", "каждого", "каждой", "каждый", "каждую",
}

def _page(title, body, status=200):
    return HTMLResponse(
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>' + html.escape(title) + ' · Медицинский архив</title>'
        '<style>body{margin:0;padding:20px;max-width:900px;font:16px/1.55 system-ui,sans-serif;background:#f4f8ff;color:#172b4d}'
        '.card{background:#fff;border:1px solid #e2eaf5;border-radius:16px;padding:18px;margin:14px 0}'
        'input,select,textarea,button{box-sizing:border-box;font:inherit;width:100%;padding:11px;margin:5px 0;border:1px solid #d8e2f0;border-radius:10px}'
        'button{background:#2868c7;color:#fff;font-weight:700;cursor:pointer}.muted{color:#65758b}'
        'label{display:block;font-weight:650;margin:12px 0 4px}.source{padding:10px 0;border-top:1px solid #e2eaf5}'
        'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}</style></head><body>'
        '<p><a href="/">← В архив</a> · <a href="/assistant">Ассистент</a></p>'
        '<h1>' + html.escape(title) + '</h1>' + body + '</body></html>',
        status_code=status,
    )

ARCHIVE_INTENT_TERMS = re.compile(
    r"\b(медицин\w*|здоров\w*|болезн\w*|диагноз\w*|симптом\w*|анализ\w*|кров\w*|моч\w*|"
    r"гемоглобин|ферритин|лейкоцит\w*|эритроцит\w*|тромбоцит\w*|гематокрит|билирубин|креатинин|"
    r"узи|экг|мрт|кт|флг|флюорограф\w*|рентген\w*|врач\w*|лечени\w*|препарат\w*|лекарств\w*|"
    r"назначени\w*|рецепт\w*|привив\w*|вакцин\w*|беремен\w*|род\w*|реб[её]н\w*|пациент\w*|"
    r"документ\w*|архив\w*|выписк\w*|эпикриз\w*|медкарт\w*|анем\w*|давлени\w*|пульс|температур\w*)\b", re.I)

OFF_TOPIC_TERMS = re.compile(
    r"\b(погод\w*|weather|политик\w*|выбор\w*|парти\w*|геополит\w*|"
    r"программирован\w*|программ\w+ на|programming|python|javascript|typescript|java|c\+\+|code|script|код|скрипт|компилятор|"
    r"html|css|api|git|linux|windows|сервер|politics|election|анекдот\w*|joke|мем\w*|фильм\w*|movie|сериал\w*|игр\w*|game|"
    r"word|excel|powerpoint|zip|rar|winrar|news|sport\w*|футбол|баскетбол|теннис|travel|путешеств\w*|туризм|отел\w*|"
    r"доллар\w*|евро|валют\w*|финанс\w*|акци\w*|бирж\w*|bitcoin|crypto|shopping|купить|покупк\w*|price|цен\w*|скидк\w*|"
    r"ресторан\w*|кулинар\w*|рецепт\s+(?:борщ\w*|пицц\w*|блюд\w*|торт\w*)|автомобил\w*|машин\w*)\b", re.I)

def _is_archive_related(question):
    """No provider call is made for clearly unrelated or programming/politics requests."""
    q = " ".join(str(question or "").casefold().replace("ё", "е").split())
    if not q or len(q) > 1200 or OFF_TOPIC_TERMS.search(q):
        return False
    return bool(ARCHIVE_INTENT_TERMS.search(q))

def _off_topic_response():
    return "Я отвечаю только на вопросы о медицинских документах, результатах обследований и анализов, истории здоровья и поиске по семейному архиву. Погоду, политику, программирование и другие посторонние темы я не обрабатываю."

def _parse_date(value):
    value = str(value or "").strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None

def _doc_date(row):
    return _parse_date(row.get("date"))

def _planner(question, token):
    """Ask HF for a strict retrieval plan. Never allow the model to choose IDs or SQL."""
    prompt = (
        "Преобразуй вопрос пользователя в план поиска по локальному медицинскому архиву. "
        "Верни только JSON-объект с ключами search_terms (массив из 3-12 конкретных терминов/синонимов), "
        "document_types (массив типов документов, может быть пустым), period_start и period_end "
        "(даты YYYY-MM-DD или null), needs_full_history (boolean), intent (короткая строка). "
        "Относительный период вычисляй относительно сегодняшней даты " + date.today().isoformat() + ". "
        "Если период не указан, не ограничивай его: обе даты null, needs_full_history=true. "
        "Для «с рождения» начальная дата неизвестна из вопроса — period_start=null. "
        "Не выдумывай данные пациента, не возвращай patient_id, SQL, команды или текст ответа. "
        "Ищи медицинские синонимы, лабораторные показатели и типы исследований."
    )
    raw = chat_completion(
        [{"role": "system", "content": prompt}, {"role": "user", "content": question}],
        max_tokens=500, temperature=0, timeout=45,
    )
    raw = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.I)
    plan = json.loads(raw)
    if not isinstance(plan, dict):
        raise ValueError("Planner response is not an object")
    terms = plan.get("search_terms", [])
    if not isinstance(terms, list):
        terms = []
    plan["search_terms"] = [str(x).strip()[:80] for x in terms if str(x).strip()][:12]
    types = plan.get("document_types", [])
    plan["document_types"] = [str(x).strip().casefold() for x in types if str(x).strip()][:12] if isinstance(types, list) else []
    for key in ("period_start", "period_end"):
        plan[key] = str(plan.get(key) or "").strip() or None
        if plan[key] and not _parse_date(plan[key]):
            plan[key] = None
    plan["needs_full_history"] = bool(plan.get("needs_full_history", not plan["period_start"] and not plan["period_end"]))
    return plan

def _fallback_plan(question):
    words = re.findall(r"[0-9a-zа-яё-]{3,}", question.casefold())
    terms = [w for w in dict.fromkeys(words) if w not in STOP_WORDS][:12]
    return {"search_terms": terms, "document_types": [], "period_start": None,
            "period_end": None, "needs_full_history": True, "intent": "keyword_search"}

def _retrieve(fid, patient, plan):
    terms = plan.get("search_terms") or []
    # Search each planned concept independently so a relevant document isn't lost
    # just because it doesn't contain every term in the plan.
    found = {}
    for term in terms[:12]:
        for row in db.search(fid, patient, term, limit=100):
            found[int(row["id"])] = row
    if not terms:
        for row in db.search(fid, patient, "", limit=1000):
            found[int(row["id"])] = row

    # Apply the date range before the optional type filter. Dates are parsed
    # from the archive's supported formats by _doc_date().
    start = _parse_date(plan.get("period_start"))
    end = _parse_date(plan.get("period_end"))
    date_rows = []
    for row in found.values():
        ddate = _doc_date(row)
        if start and (not ddate or ddate < start):
            continue
        if end and (not ddate or ddate > end):
            continue
        date_rows.append(row)

    # LLM-planned type labels often differ from the archive's canonical labels
    # (e.g. "анализ крови общий" vs "лабораторный отчёт"). Prefer matching types,
    # but don't turn a useful search into zero results solely due to that mismatch.
    types = [
        str(value).strip().casefold()
        for value in (plan.get("document_types") or [])
        if str(value).strip()
    ]
    rows = date_rows
    if types:
        typed_rows = []
        for row in date_rows:
            blob = (
                str(row.get("kind") or "") + " " + str(row.get("name") or "")
            ).casefold()
            if any(t in blob or blob in t for t in types):
                typed_rows.append(row)
        if typed_rows:
            rows = typed_rows
        elif date_rows:
            logging.warning(
                "Assistant document-type filter matched no candidates; "
                "using search/date-filtered candidates instead"
            )

    for row in rows:
        row["_assistant_score"] = int(row.get("_search_score", 0))
    rows.sort(key=lambda r: (r["_assistant_score"], _doc_date(r) or date.min), reverse=True)
    return rows[:15]

def _context(rows):
    chunks = []
    for row in rows:
        analysis = row.get("analysis") or {}
        lines = [
            "Источник: " + str(row.get("name") or "Без названия"),
            "Дата: " + str(row.get("date") or "не указана"),
            "Тип: " + str(row.get("kind") or "не определён"),
            "ID источника в архиве: " + str(row.get("id")),
        ]
        for item in (analysis.get("lab_results") or [])[:40]:
            lines.append("Лабораторный показатель: {name} = {value} {unit}; стр. {page}; строка OCR: {source}".format(
                name=item.get("name", ""), value=item.get("value") or "не извлечено",
                unit=item.get("unit") or "", page=item.get("page") or "?",
                source=item.get("source") or ""))
        for group in ("diagnoses", "medications"):
            for item in (analysis.get(group) or [])[:15]:
                lines.append(group + " (стр. " + str(item.get("page") or "?") + "): " + str(item.get("text") or ""))
        lines.append("Фрагмент OCR:\n" + str(row.get("text") or "")[:2200])
        chunks.append("\n".join(lines))
    return "\n\n--- ИСТОЧНИК ---\n\n".join(chunks)[:18000]

def install_assistant_routes(app, current_user, family_guard):
    patient_memory.init()

    @app.get("/patient-memory", response_class=HTMLResponse)
    def patient_memory_page(family_id: int | None = None, patient: str = "",
                            uid: int = __import__("fastapi").Depends(current_user)):
        families = tenancy.families_for_user(uid)
        if not families:
            return _page("Память пациента", '<div class="card">Сначала создайте семейный архив и добавьте пациента.</div>')
        allowed = {int(f["id"]) for f in families}
        fid = int(family_id) if family_id is not None else int(families[0]["id"])
        if fid not in allowed:
            raise HTTPException(403, "Нет доступа к этому семейному архиву")
        family_guard(fid, uid)
        patients = db.patients(fid)
        if patient not in patients:
            if len(patients) == 1:
                patient = patients[0]
            else:
                options = "".join(
                    '<li><a href="/patient-memory?family_id=' + str(fid) + '&patient=' + quote(p, safe="") + '">' + html.escape(p) + '</a></li>'
                    for p in patients
                )
                return _page("Память пациента", '<div class="card"><p>Выберите пациента:</p><ul>' + options + '</ul></div>')
        if not patient:
            return _page("Память пациента", '<div class="card">В этом архиве пока нет пациентов.</div>')
        snapshot = patient_memory.get_snapshot(fid, patient)

        def section(title, items, render_item):
            if not items:
                return '<section class="card"><h2>' + html.escape(title) + '</h2><p class="muted">Записей пока нет.</p></section>'
            return '<section class="card"><h2>' + html.escape(title) + '</h2><ul>' + "".join(render_item(item) for item in items) + '</ul></section>'

        def source_link(source):
            source = source or {}
            doc_id = source.get("document_id")
            if not doc_id:
                return ""
            return ' · <a href="/families/' + str(fid) + '/documents/' + str(int(doc_id)) + '/edit">Источник: ' + html.escape(str(source.get("name") or "документ")) + '</a>'

        diagnosis_html = section("Упомянутые диагнозы и состояния", snapshot["diagnoses_mentioned"][:100],
            lambda item: '<li><strong>' + html.escape(str(item.get("date") or "Дата не указана")) + '</strong> — '
            + html.escape(str(item.get("text") or "")) + source_link(item.get("source")) + '</li>')
        medication_html = section("Упомянутые лекарства и назначения", snapshot["medications_mentioned"][:100],
            lambda item: '<li><strong>' + html.escape(str(item.get("date") or "Дата не указана")) + '</strong> — '
            + html.escape(str(item.get("text") or "")) + source_link(item.get("source")) + '</li>')
        lab_html = section("Лабораторные показатели", snapshot["lab_results"][:150],
            lambda item: '<li><strong>' + html.escape(str(item.get("date") or "Дата не указана")) + '</strong> — '
            + html.escape(str(item.get("name") or "")) + ': ' + html.escape(str(item.get("value") or ""))
            + (' ' + html.escape(str(item.get("unit"))) if item.get("unit") else "")
            + source_link(item.get("source")) + '</li>')
        def render_trend(item):
            previous = item.get("previous") or {}
            latest = item.get("latest") or {}
            delta = str(item.get("absolute_change") or "0")
            if item.get("direction") == "increase":
                delta = "+" + delta
            return (
                '<li><strong>' + html.escape(str(item.get("name") or "")) + '</strong>: '
                + html.escape(str(previous.get("value") or "")) + ' → '
                + html.escape(str(latest.get("value") or "")) + ' ' + html.escape(str(item.get("unit") or ""))
                + '; изменение ' + html.escape(delta) + ' ' + html.escape(str(item.get("unit") or ""))
                + ' (' + html.escape(str(previous.get("date") or "?")) + ' → '
                + html.escape(str(latest.get("date") or "?")) + ')'
                + source_link(previous.get("source")) + source_link(latest.get("source")) + '</li>'
            )
        trend_html = section("Динамика лабораторных показателей", snapshot.get("lab_trends", []), render_trend)
        docs_html = section("Документы в истории", snapshot["documents"][:150],
            lambda item: '<li><strong>' + html.escape(str(item.get("date") or "Дата не указана")) + '</strong> — '
            + html.escape(str(item.get("kind") or "Тип не определён")) + ': '
            + '<a href="/families/' + str(fid) + '/documents/' + str(int(item["document_id"])) + '/edit">'
            + html.escape(str(item.get("name") or "Документ без названия")) + '</a></li>')
        caveats = "".join('<li>' + html.escape(str(note)) + '</li>' for note in snapshot["limitations"])
        body = (
            '<div class="card"><p><strong>Пациент:</strong> ' + html.escape(patient) + '</p>'
            '<p><strong>Дата рождения:</strong> ' + html.escape(str((snapshot.get("profile") or {}).get("birth_date") or "не указана")) + '</p>'
            '<p><strong>Документов учтено:</strong> ' + str(snapshot["document_count"]) + '</p>'
            '<p>Память формируется локально из структурированных результатов распознавания и обновляется при открытии. '
            'Каждая запись ведёт к исходному документу.</p>'
            '<p><a href="/assistant?family_id=' + str(fid) + '&patient=' + quote(patient, safe="") + '">Задать вопрос ассистенту по этому пациенту</a></p></div>'
            + diagnosis_html + medication_html + lab_html + trend_html + docs_html
            + '<section class="card"><h2>Ограничения памяти</h2><ul>' + caveats + '</ul></section>'
        )
        return _page("Память пациента", body)

    @app.get("/api/patient-memory")
    def patient_memory_api(family_id: int, patient: str,
                           uid: int = __import__("fastapi").Depends(current_user)):
        families = tenancy.families_for_user(uid)
        if int(family_id) not in {int(f["id"]) for f in families}:
            raise HTTPException(403, "Нет доступа к этому семейному архиву")
        family_guard(family_id, uid)
        if patient not in db.patients(family_id):
            raise HTTPException(400, "Выбранный пациент не найден в этом архиве")
        return JSONResponse(patient_memory.get_snapshot(family_id, patient))

    @app.get("/assistant", response_class=HTMLResponse)
    def assistant_page(family_id: int | None = None, patient: str = "", uid: int = __import__("fastapi").Depends(current_user)):
        families = tenancy.families_for_user(uid)
        if not families:
            return _page("Медицинский ассистент", '<div class="card">Сначала создайте семейный архив и добавьте пациента.</div>')
        allowed = {int(f["id"]) for f in families}
        fid = int(family_id) if family_id is not None else int(families[0]["id"])
        if fid not in allowed:
            raise HTTPException(403, "Нет доступа к этому семейному архиву")
        family_guard(fid, uid)
        patients = db.patients(fid)
        if patient not in patients:
            patient = patients[0] if len(patients) == 1 else ""
        family_options = "".join('<option value="' + str(f["id"]) + '"' + (" selected" if int(f["id"]) == fid else "") + ">" + html.escape(f["name"]) + "</option>" for f in families)
        patient_options = '<option value="">Выберите пациента</option>' + "".join('<option' + (" selected" if p == patient else "") + '>' + html.escape(p) + '</option>' for p in patients)
        body = (
            '<div class="card"><p>Ассистент сначала планирует поиск, затем ищет только в архиве выбранного пациента и анализирует найденные источники.</p>'
            '<form method="post" action="/assistant">'
            '<label>Семейный архив</label><select name="family_id" onchange="location.href=\'/assistant?family_id=\'+this.value">' + family_options + '</select>'
            '<label>Пациент</label><select name="patient" required>' + patient_options + '</select>'
            '<p><a href="/patient-memory?family_id=' + str(fid) + '&patient=' + quote(patient, safe="") + '">Открыть память пациента и историю показателей</a></p>'
            '<label>Вопрос</label><textarea name="question" rows="4" required maxlength="1200" placeholder="Например: сравни гемоглобин за последние полгода и покажи динамику"></textarea>'
            '<label style="font-weight:400"><input type="checkbox" name="consent" value="yes" required style="width:auto"> Я разрешаю отправить текст вопроса и найденные фрагменты медицинских документов внешнему ИИ-провайдеру для анализа.</label>'
            '<button type="submit">Найти и проанализировать</button></form>'
            '<p class="muted">Если согласие не дано, данные не отправляются во внешнюю нейросеть. Ответ не заменяет консультацию врача.</p></div>'
        )
        return _page("Медицинский ассистент", body)

    @app.post("/assistant", response_class=HTMLResponse)
    def assistant_ask(family_id: int = Form(...), patient: str = Form(...), question: str = Form(...),
                      consent: str = Form(""), uid: int = __import__("fastapi").Depends(current_user)):
        families = tenancy.families_for_user(uid)
        if not families or int(family_id) not in {int(f["id"]) for f in families}:
            raise HTTPException(403, "Нет доступа к этому семейному архиву")
        family_guard(family_id, uid)
        if patient not in db.patients(family_id):
            raise HTTPException(400, "Выбранный пациент не найден в этом архиве")
        question = " ".join((question or "").split())[:1200]
        if not question:
            raise HTTPException(400, "Введите вопрос")
        if not _is_archive_related(question):
            return _page("Вопрос вне тематики", '<div class="card">' + html.escape(_off_topic_response()) + '</div><p><a href="/assistant?family_id=' + str(family_id) + '&patient=' + quote(patient, safe="") + '">Вернуться к медицинскому вопросу</a></p>', 400)
        if consent != "yes":
            return _page("Требуется согласие", '<div class="card">Вопрос и медицинские фрагменты не отправлялись нейросети. Чтобы продолжить, вернитесь и явно подтвердите согласие.</div><p><a href="/assistant?family_id=' + str(family_id) + '&patient=' + quote(patient, safe="") + '">Вернуться</a></p>', 400)
        try:
            provider, token, _, model, key_name = provider_config()
        except Exception:
            return _page("ИИ не настроен", '<div class="card">Не удалось определить провайдера. Проверьте AI_PROVIDER в .env.</div><p><a href="/assistant?family_id=' + str(family_id) + '&patient=' + quote(patient, safe="") + '">Назад</a></p>', 503)
        if not token:
            return _page("ИИ не настроен", '<div class="card">Не задан ' + html.escape(key_name) + '. Поиск не запускался и медицинские данные не отправлялись.</div><p><a href="/assistant?family_id=' + str(family_id) + '&patient=' + quote(patient, safe="") + '">Назад</a></p>', 503)
        try:
            try:
                plan = _planner(question, token)
                planner_status = "План сформирован моделью " + model + " (" + provider + ")"
            except Exception as exc:
                logging.warning("Assistant planner unavailable (%s); using local keyword fallback", type(exc).__name__)
                plan = _fallback_plan(question)
                planner_status = "План построен локально: нейросеть планирования недоступна"
            rows = _retrieve(family_id, patient, plan)
            snapshot = patient_memory.get_snapshot(family_id, patient)
            all_patient_rows = db.search(family_id, patient, "", limit=1000)
            references = discover_referenced_documents(rows, all_patient_rows) if rows else {
                "found_documents": [], "missing_required": []
            }
            known_row_ids = {int(row["id"]) for row in rows}
            for referenced in references["found_documents"]:
                if int(referenced["id"]) not in known_row_ids:
                    referenced["_assistant_score"] = 0
                    rows.append(referenced)
                    known_row_ids.add(int(referenced["id"]))
            rows.sort(key=lambda row: (_doc_date(row) or date.min, int(row["id"])), reverse=True)
            rows = rows[:20]
            if not rows and not snapshot.get("document_count"):
                return _page("Результаты поиска", '<div class="card"><p>В архиве пациента пока нет документов, на которых можно построить ответ.</p><p class="muted">' + html.escape(planner_status) + '. Добавьте документы или уточните запрос.</p></div><p><a href="/assistant?family_id=' + str(family_id) + '&patient=' + quote(patient, safe="") + '">Задать другой вопрос</a></p>')
            context = patient_memory.to_context(snapshot) + "\\n\\nРЕЛЕВАНТНЫЕ ДОКУМЕНТЫ ПО ЗАПРОСУ И ЯВНЫМ ССЫЛКАМ:\\n" + _context(rows)
            if references["missing_required"]:
                missing_context = [
                    "- " + item["target"] + " (упомянуто в источнике ID "
                    + str(item["source"]["document_id"]) + ": " + str(item["source"]["name"]) + ")"
                    for item in references["missing_required"]
                ]
                context += "\\n\\nОБЯЗАТЕЛЬНЫЕ ДЛЯ ПОЛНОЙ ИНТЕРПРЕТАЦИИ ДОКУМЕНТЫ НЕ НАЙДЕНЫ В АРХИВЕ:\\n" + "\\n".join(missing_context)
            if not rows:
                planner_status += "; отдельные документы по запросу не найдены, использована память по всей истории"
            answer = answer_archive_question(question, patient, context=context)
            if answer.startswith("Не удалось получить ответ ИИ") or answer.startswith("Не задан "):
                return _page("Ошибка анализа", '<div class="card">' + html.escape(answer) + '</div><p><a href="/assistant?family_id=' + str(family_id) + '&patient=' + quote(patient, safe="") + '">Попробовать ещё раз</a></p>', 502)
            source_rows = {int(r["id"]): r for r in rows}
            for item in snapshot.get("documents", [])[:100]:
                doc_id = int(item["document_id"])
                source_rows.setdefault(doc_id, {
                    "id": doc_id, "name": item.get("name"), "date": item.get("date"), "kind": item.get("kind")
                })
            sources = "".join(
                '<div class="source"><strong>' + html.escape(str(r.get("name") or "Без названия")) + '</strong><br>'
                + html.escape(str(r.get("date") or "Дата не указана")) + ' · ' + html.escape(str(r.get("kind") or "не определён"))
                + ' · <a href="/families/' + str(family_id) + '/documents/' + str(r["id"]) + '/edit">Открыть документ</a></div>'
                for r in list(source_rows.values())[:100]
            )
            plan_html = '<p class="muted">' + html.escape(planner_status) + '; источников по запросу и ссылкам: ' + str(len(rows)) + '.</p>'
            missing_html = ""
            if references["missing_required"]:
                missing_items = "".join(
                    '<li>' + html.escape(str(item["target"])) + ' — упомянуто в документе '
                    + '<a href="/families/' + str(family_id) + '/documents/' + str(int(item["source"]["document_id"])) + '/edit">'
                    + html.escape(str(item["source"]["name"])) + '</a>, но подходящий документ не найден. '
                    + 'Проверьте архив по названию или загрузите документ, если он у вас есть.</li>'
                    for item in references["missing_required"]
                )
                missing_html = '<div class="card"><h2>Для полного анализа не хватает документов</h2><p>В исходных документах есть явные ссылки на следующие материалы:</p><ul>' + missing_items + '</ul></div>'
            answer_html = '<div class="card assistant-answer"><h2>Ответ</h2><pre>' + html.escape(answer) + '</pre></div>'
            return _page("Ответ ассистента", plan_html + missing_html + answer_html + '<div class="card"><h2>Источники</h2>' + sources + '</div><p><a href="/assistant?family_id=' + str(family_id) + '&patient=' + quote(patient, safe="") + '">Задать следующий вопрос</a></p>')
        except HTTPException:
            raise
        except Exception as exc:
            logging.exception("Medical assistant request failed (%s)", type(exc).__name__)
            return _page("Не удалось выполнить запрос", '<div class="card">Произошла техническая ошибка. Подробности записаны в журнал без текста медицинского запроса.</div><p><a href="/assistant?family_id=' + str(family_id) + '&patient=' + quote(patient, safe="") + '">Попробовать ещё раз</a></p>', 502)


    @app.post("/api/intelligent-search")
    async def intelligent_search(request: Request, uid: int = __import__("fastapi").Depends(current_user)):
        """Family-scoped smart search. Document discovery is local; AI analysis requires explicit consent."""
        families = tenancy.families_for_user(uid)
        if not families:
            raise HTTPException(400, "Сначала создайте семейный архив")
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(400, "Некорректный запрос")
        if not isinstance(payload, dict):
            raise HTTPException(400, "Некорректный запрос")
        query = " ".join(str(payload.get("query") or "").split())[:1200]
        try:
            fid = int(payload.get("family_id") or families[0]["id"])
        except (TypeError, ValueError):
            raise HTTPException(400, "Некорректный семейный архив")
        allowed = {int(f["id"]) for f in families}
        if fid not in allowed:
            raise HTTPException(403, "Нет доступа к этому семейному архиву")
        family_guard(fid, uid)
        if not query:
            raise HTTPException(400, "Введите запрос")
        if not _is_archive_related(query):
            return JSONResponse({"error": _off_topic_response(), "mode": "off_topic"}, status_code=400)

        people = db.patients(fid)
        qfold = query.casefold().replace("ё", "е")
        mentioned = [p for p in people if p.casefold().replace("ё", "е") in qfold]
        scoped_people = mentioned or people
        analysis_markers = (
            "сравни", "сравнить", "динамик", "объясни", "объяснить", "что означает",
            "что значит", "почему", "оцени", "проанализируй", "рекомендац", "что делать",
            "норма ли", "насколько опас", "какие выводы", "интерпрет"
        )
        needs_analysis = any(marker in qfold for marker in analysis_markers)
        consent = bool(payload.get("consent"))
        if needs_analysis and not consent:
            return JSONResponse({"mode": "analysis", "needs_consent": True,
                "message": "Для медицинского анализа вопрос и найденные фрагменты документов будут отправлены внешнему ИИ-провайдеру. Подтвердите согласие, чтобы продолжить."})

        rows_by_id = {}
        if needs_analysis:
            try:
                _, token, _, model, provider = provider_config()
                if not token:
                    return JSONResponse({"error": "ИИ не настроен: не задан ключ провайдера."}, status_code=503)
                try:
                    plan = _planner(query, token)
                except Exception as exc:
                    logging.warning("Smart search planner unavailable (%s); using local keyword fallback", type(exc).__name__)
                    plan = _fallback_plan(query)
                for person in scoped_people:
                    for row in _retrieve(fid, person, plan):
                        rows_by_id[int(row["id"])] = row
                rows = list(rows_by_id.values())
                rows.sort(key=lambda r: (_doc_date(r) or date.min, int(r.get("_assistant_score", 0))), reverse=True)
                rows = rows[:15]
                if not rows:
                    return JSONResponse({"mode": "analysis", "answer": "По запросу документы не найдены. Попробуйте уточнить название исследования или период.", "documents": []})
                answer = answer_archive_question(query, ", ".join(scoped_people), context=_context(rows))
                return JSONResponse({"mode": "analysis", "answer": answer, "documents": [
                    {"id": int(r["id"]), "patient": str(r.get("patient") or ""), "name": str(r.get("name") or "Без названия"),
                     "kind": str(r.get("kind") or "не определён"), "date": str(r.get("date") or ""),
                     "url": f"/families/{fid}/documents/{int(r['id'])}/edit"}
                    for r in rows
                ]})
            except HTTPException:
                raise
            except Exception as exc:
                logging.exception("Smart medical analysis failed (%s)", type(exc).__name__)
                return JSONResponse({"error": "Не удалось выполнить анализ. Попробуйте ещё раз."}, status_code=502)

        # Local document search: no OCR text or medical question is sent to an external provider.
        words = [w for w in re.findall(r"[0-9a-zа-яё-]{2,}", qfold) if w not in STOP_WORDS]
        for person in people:
            if person.casefold().replace("ё", "е") in qfold:
                words = [w for w in words if w not in person.casefold().replace("ё", "е").split()]
        synonyms = {
            "флг": ["флюорография", "флюорограф"],
            "флюорография": ["флг", "флюорограф"],
            "узи": ["ультразвуковое", "ультразвук"],
            "оак": ["общий анализ крови"],
            "экг": ["электрокардиограмма", "электрокардиография"],
            "мрт": ["магнитно-резонансная"],
            "кт": ["компьютерная томография"],
        }
        search_terms = list(dict.fromkeys(words))
        for word in list(search_terms):
            search_terms.extend(synonyms.get(word, []))
        search_terms = list(dict.fromkeys(search_terms))[:16]
        for person in scoped_people:
            candidates = db.search(fid, person, "", limit=1000) if not search_terms else [
                row for term in search_terms for row in db.search(fid, person, term, limit=100)
            ]
            for row in candidates:
                rows_by_id[int(row["id"])] = row
        rows = list(rows_by_id.values())
        rows.sort(key=lambda r: (_doc_date(r) or date.min, int(r.get("_search_score", 0))), reverse=True)
        latest_each = ("последн" in qfold and any(x in qfold for x in ("всех", "семь", "кажд")))
        if latest_each:
            latest = {}
            for row in rows:
                latest.setdefault(str(row.get("patient") or ""), row)
            rows = list(latest.values())
            rows.sort(key=lambda r: (_doc_date(r) or date.min), reverse=True)
        rows = rows[:100]
        return JSONResponse({"mode": "documents", "latest_each": latest_each, "documents": [
            {"id": int(r["id"]), "patient": str(r.get("patient") or ""), "name": str(r.get("name") or "Без названия"),
             "kind": str(r.get("kind") or "не определён"), "date": str(r.get("date") or ""),
             "url": f"/families/{fid}/documents/{int(r['id'])}/edit"}
            for r in rows
        ]})