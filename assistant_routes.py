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
from fastapi import Form, HTTPException
from fastapi.responses import HTMLResponse

import database as db
import tenancy
from ai_provider import answer_archive_question, chat_completion, provider_config

STOP_WORDS = {
    "что", "как", "когда", "где", "почему", "какой", "какая", "какие",
    "покажи", "найди", "сравни", "сравнить", "все", "весь", "вся",
    "последний", "последние", "период", "пациент", "пациента", "документ",
    "документы", "медицинский", "медицинские", "моя", "мой", "мне", "для",
    "про", "это", "его", "ее", "него", "неё", "был", "была", "были",
    "есть", "самый", "самая", "самое", "динамику", "динамика", "изменения",
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
    start = _parse_date(plan.get("period_start"))
    end = _parse_date(plan.get("period_end"))
    types = [x.casefold() for x in plan.get("document_types", [])]
    rows = []
    for row in found.values():
        ddate = _doc_date(row)
        if start and (not ddate or ddate < start):
            continue
        if end and (not ddate or ddate > end):
            continue
        if types:
            blob = (str(row.get("kind") or "") + " " + str(row.get("name") or "")).casefold()
            if not any(t in blob or blob in t for t in types):
                continue
        row["_assistant_score"] = int(row.get("_search_score", 0))
        rows.append(row)
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
            if not rows:
                return _page("Результаты поиска", '<div class="card"><p>По заданным критериям документы не найдены.</p><p class="muted">' + html.escape(planner_status) + '. Попробуйте сформулировать вопрос иначе или проверить период.</p></div><p><a href="/assistant?family_id=' + str(family_id) + '&patient=' + quote(patient, safe="") + '">Задать другой вопрос</a></p>')
            context = _context(rows)
            answer = answer_archive_question(question, patient, context=context)
            if answer.startswith("Не удалось получить ответ ИИ") or answer.startswith("Не задан "):
                return _page("Ошибка анализа", '<div class="card">' + html.escape(answer) + '</div><p><a href="/assistant?family_id=' + str(family_id) + '&patient=' + quote(patient, safe="") + '">Попробовать ещё раз</a></p>', 502)
            sources = "".join(
                '<div class="source"><strong>' + html.escape(str(r.get("name") or "Без названия")) + '</strong><br>'
                + html.escape(str(r.get("date") or "Дата не указана")) + ' · ' + html.escape(str(r.get("kind") or "не определён"))
                + ' · <a href="/families/' + str(family_id) + '/documents/' + str(r["id"]) + '/edit">Открыть документ</a></div>'
                for r in rows
            )
            plan_html = '<p class="muted">' + html.escape(planner_status) + '; найдено источников: ' + str(len(rows)) + '.</p>'
            answer_html = '<div class="card"><h2>Ответ</h2><pre>' + html.escape(answer) + '</pre></div>'
            return _page("Ответ ассистента", plan_html + answer_html + '<div class="card"><h2>Источники</h2>' + sources + '</div><p><a href="/assistant?family_id=' + str(family_id) + '&patient=' + quote(patient, safe="") + '">Задать следующий вопрос</a></p>')
        except HTTPException:
            raise
        except Exception as exc:
            logging.exception("Medical assistant request failed (%s)", type(exc).__name__)
            return _page("Не удалось выполнить запрос", '<div class="card">Произошла техническая ошибка. Подробности записаны в журнал без текста медицинского запроса.</div><p><a href="/assistant?family_id=' + str(family_id) + '&patient=' + quote(patient, safe="") + '">Попробовать ещё раз</a></p>', 502)
