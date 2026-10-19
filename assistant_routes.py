    ))


def _looks_like_explicit_memory_command(question):
    """Only treat explicit save-to-memory instructions as manual memory writes."""
    q = " ".join(str(question or "").casefold().replace("ё", "е").split())
    return bool(re.search(
        r"\b(?:запиши|сохрани|добавь|внеси)\b.{0,45}\b(?:в\s+память|памят|рост|вес)\b",
        q,
    ))


def _looks_like_hypothetical_measurement(question):
    q = " ".join(str(question or "").casefold().replace("ё", "е").split())
    if "?" in q:
        return True
    return bool(re.search(
        r"\b(?:если|допустим|предположим|представим|например,\s*если|что\s+если)\b",
        q,
    ))


def _extract_memory_measurements(question):
    """Extract plausible height/weight statements for a confirmation proposal, never an automatic write."""
    q = " ".join(str(question or "").casefold().replace("ё", "е").split())
    explicit_save = _looks_like_explicit_memory_command(q)
    if not explicit_save and _looks_like_hypothetical_measurement(q):
        return []

    results = []
    patterns = (
        ("height_cm", r"\b(?:мой\s+)?рост\s*(?:~|≈|около|примерно)?\s*(\d+(?:[.,]\d+)?)\s*(см|сантиметр\w*)?\b", "Рост", "см"),
        ("weight_kg", r"\b(?:мой\s+)?вес\s*(?:~|≈|около|примерно)?\s*(\d+(?:[.,]\d+)?)\s*(кг|килограмм\w*)?\b|\b(?:вешу|весит|весила|весил)\s*(?:~|≈|около|примерно)?\s*(\d+(?:[.,]\d+)?)\s*(кг|килограмм\w*)?\b", "Вес", "кг"),
    )
    for memory_key, pattern, label, unit in patterns:
        match = re.search(pattern, q, re.I)
        if not match:
            continue
        # Explicit save commands may omit units; conversational statements must carry units.
        if memory_key == "weight_kg" and match.group(3) is not None:
            number, found_unit = match.group(3), match.group(4)
            matched_text = match.group(0)
        else:
            number, found_unit = match.group(1), match.group(2)
            matched_text = match.group(0)
        if not found_unit and not explicit_save:
            continue
        value = number.replace(",", ".")
        try:
            numeric = float(value)
        except ValueError:
            continue
        if numeric <= 0 or (memory_key == "height_cm" and not 30 <= numeric <= 260) or (memory_key == "weight_kg" and not 1 <= numeric <= 500):
            continue
        approximate = bool(re.search(r"(?:~|≈|около|примерно)\s*\d", matched_text))
        text = f"{label}: {'около ' if approximate else ''}{value} {unit}"
        results.append({"memory_key": memory_key, "text": text, "category": "note"})
    # Keep one proposal per fact, even if the same value is repeated in the sentence.
    unique = []
    seen = set()
    for item in results:
        marker = (item["memory_key"], item["text"])
        if marker not in seen:
            unique.append(item)
            seen.add(marker)
    return unique


def _parse_structured_answer(raw):
        except Exception:
            data = None
    if not isinstance(data, dict) or not sanitize_model_text(data.get("answer") or ""):
        # Plain prose can be a useful fallback, but never expose serialized JSON as if it
        # were a user-facing answer when structured output is malformed or truncated.
        looks_serialized = text.lstrip().startswith("{") and any(
            key in text[:300] for key in ('"answer"', '"missing_documents"', '"data_completeness"')
        )
        fallback = ("Не удалось корректно обработать ответ модели. Попробуйте переформулировать вопрос."
                    if looks_serialized else sanitize_model_text(text) or sanitize_model_text(raw))
        return {"answer": fallback, "missing_documents": [], "limitations": [],
                "data_completeness": "unknown"}
    answer_text = sanitize_model_text(data.get("answer"))
    # Some OpenAI-compatible models place a complete JSON response inside the outer
    # answer field. Unwrap it before rendering or retaining it in chat history.
    for _ in range(3):
        try:
            nested = json.loads(answer_text)
        except (TypeError, ValueError):
            break
        if isinstance(nested, dict) and isinstance(nested.get("answer"), str):
            for key in ("missing_documents", "limitations", "data_completeness", "memory_updates"):
                if key not in data and key in nested:
                    data[key] = nested[key]
            answer_text = sanitize_model_text(nested.get("answer"))
        else:
            break
    if not answer_text:
        answer_text = "Не удалось корректно обработать ответ модели. Попробуйте переформулировать вопрос."
    embedded_fields = re.search(r"(?:\\\\n|\\n|\n)\s*(?:missing_documents|limitations|data_completeness|memory_updates)\s*:", answer_text, re.I)
    if embedded_fields:
        answer_text = answer_text[:embedded_fields.start()]
                "source_document_id": source_id,
                "date": " ".join(sanitize_model_text(item.get("fact_date")).split())[:40],
            })
    return {"answer": answer_text, "missing_documents": gaps,
            "limitations": limits, "data_completeness": completeness, "memory_updates": updates}


    prior_questions = [str(x).strip()[:350] for x in (history or []) if str(x).strip()][-5:]
    system = (
        "Ты медицинский информационный помощник семейного архива. Отвечай по-русски, понятно и по существу. "
        "Стиль: короткий естественный русский без канцелярита, повторов и общих лекций. По умолчанию 80–180 слов; если пользователь просит «кратко», «вывод» или «что делать» — до 100 слов. "
        "Сначала ответь на текущий вопрос. Не пересказывай всё досье и не перечисляй источники/анализы, если они не нужны для ответа. Не добавляй нерелевантные сведения о других членах семьи. "
        "Не обращайся к пациенту во втором лице и не называй ребёнка собеседником: отвечай взрослому, который задаёт вопрос о пациенте. "
        "История диалога нужна только для разрешения ссылок и уточнений; предыдущие ответы ассистента не являются медицинскими доказательствами. "
        "Для сводки по нескольким людям используй отдельный короткий абзац на каждого: что известно, даты, что требует внимания и насколько данные свежие. "
        "Строго разделяй пациентов: каждый факт и результат относится только к человеку, указанному у его источника; никогда не переноси данные между людьми. "
        "Список Пациент(ы), переданный в запросе, задаёт разрешённую область анализа. Не анализируй и не делай выводов о других людях, даже если их имя случайно есть в вопросе или истории. "
    user = (
        "Пациент(ы): " + (", ".join(patients) or "семья") + "\n"
        + ("Контекст предыдущего диалога (только для понимания короткого уточнения): " + " | ".join(prior_questions) + "\n" if prior_questions else "")
        + "Память и документы переданы в двух явно разделённых секциях выше. При пустом разделе документов всё равно ответь на общий медицинский вопрос, "
        + "используя осторожные общие знания и доступную память пациента; не подменяй ответ сообщением об отсутствии документов.\n"
        + context[:18000]
        + "\n\nТекущий вопрос: " + question
    )
    if trace_id:
        ai_trace_log.emit_full(trace_id, "model.request", provider="configured_provider", system_prompt=system, user_prompt=user)
    completion = chat_completion(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=1200, temperature=0.1, timeout=90, return_metadata=True,
    )
    if isinstance(completion, dict) and isinstance(completion.get("content"), str):
        raw = completion["content"]
        metadata = completion.get("metadata") if isinstance(completion.get("metadata"), dict) else {}
    else:
        # Preserve compatibility with test doubles or alternate adapters returning plain text.
        raw = completion
        metadata = {}
    if trace_id:
        ai_trace_log.emit_full(trace_id, "model.raw_response", raw_response=raw)
        ai_trace_log.emit(trace_id, "model.completion_metadata", **metadata)
    answer_data = _parse_structured_answer(raw)
    if metadata.get("finish_reason") in {"length", "max_tokens", "token_limit", "max_output_tokens"}:
        answer_data["answer"] += (
            "\n\n⚠️ Ответ мог быть обрезан лимитом генерации. "
            "Попросите продолжить ответ, чтобы получить оставшуюся часть."
        )
    return answer_data


def _search_referenced_documents(fid, patients, gaps, existing_ids):
    return selected


def _planner(question, token, trace_id=None):
    """Ask the configured provider for a strict retrieval plan; trace raw I/O for debugging."""
    prompt = (
        "Преобразуй вопрос пользователя в план поиска по локальному медицинскому архиву. "
        "Верни только JSON-объект с ключами search_terms (массив из 3-12 конкретных терминов/синонимов), "
        "Не выдумывай данные пациента, не возвращай patient_id, SQL, команды или текст ответа. "
        "Ищи медицинские синонимы, лабораторные показатели и типы исследований."
    )
    messages = [{"role": "system", "content": prompt}, {"role": "user", "content": question}]
    if trace_id:
        ai_trace_log.emit_full(trace_id, "planner.request", provider="configured_provider", model_input=messages)
    raw = chat_completion(messages, max_tokens=500, temperature=0, timeout=45)
    if trace_id:
        ai_trace_log.emit_full(trace_id, "planner.raw_response", raw_response=raw)
    raw = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", raw, flags=re.I)
    plan = json.loads(raw)
    if not isinstance(plan, dict):
        if forced_patient:
            mentioned = [forced_patient]
        scoped_people = [forced_patient] if forced_patient else (mentioned or people)
        explicit_memory_command = _looks_like_explicit_memory_command(query)
        explicit_measurements = _extract_memory_measurements(query)
        if explicit_measurements and not forced_patient and len(mentioned) == 0:
            # Never guess which family member owns a user-entered measurement.
            if followup and len(previous_turn_people) == 1:
                mentioned = list(previous_turn_people)
                scoped_people = list(mentioned)
            elif len(people) == 1:
                mentioned = [people[0]]
                scoped_people = list(mentioned)
            else:
                ai_trace_log.emit(trace_id, "patient.memory_target_ambiguous",
                    scoped_patient_count=len(people), model_called=False)
                answer = ("Уточни, для кого сохранить эти данные: выбери пациента в карточке "
                          "или укажи его имя. Пока ничего не записано.")
                return JSONResponse({"mode":"memory_clarification", "answer":answer,
                    "documents":[], "missing_documents":[], "limitations":[],
                    "data_completeness":"insufficient", "memory_proposals":[]})
        # A clear measurement statement is handled locally as a pending proposal,
        # not sent to an external model and never written without user confirmation.
        if explicit_measurements and (explicit_memory_command or not _looks_like_hypothetical_measurement(query)):
            if len(mentioned) != 1:
                ai_trace_log.emit(trace_id, "patient.memory_target_ambiguous",
                    scoped_patient_count=len(scoped_people), model_called=False)
                answer = ("Уточни, для кого сохранить эти данные: выбери пациента в карточке "
                          "или укажи его имя. Пока ничего не записано.")
                return JSONResponse({"mode":"memory_clarification", "answer":answer,
                    "documents":[], "missing_documents":[], "limitations":[],
                    "data_completeness":"insufficient", "memory_proposals":[]})
            direct_proposals = []
            for measurement in explicit_measurements:
                try:
                    if not patient_memory.should_propose_measurement(
                        fid, mentioned[0], measurement["memory_key"], measurement["text"]
                    ):
                        continue
                    direct_proposals.append(patient_memory.propose_fact(
                        fid, mentioned[0], measurement["text"], "note", date.today().isoformat(),
                        memory_key=measurement["memory_key"],
                        reason=("Параметр сообщён пользователем. Это не медицинское измерение из документа; подтвердите сохранение." if explicit_memory_command else "Похоже, вы сообщили этот параметр в разговоре. Значение не подтверждено медицинским документом; подтвердите сохранение."),
                        actor_id=uid,
                    ))
                except ValueError as exc:
                    logging.warning("Could not create direct memory proposal (%s)", type(exc).__name__)
            if direct_proposals:
                answer = ("Подготовил предложение сохранить данные со слов пользователя. Проверь значения и подтверди сохранение ниже." if explicit_memory_command else "Распознал сообщённые параметры и подготовил предложения для памяти. Проверь значения и подтверди сохранение ниже.")
            else:
                answer = "Такие значения уже есть в памяти и не требуют обновления. Ничего не изменено."
            ai_trace_log.emit(trace_id, "response.complete", status="ok", mode="memory_update",
                answer_chars=len(answer), proposal_count=len(direct_proposals), model_called=False)
            return JSONResponse({"mode":"memory_update", "answer":answer,
                "documents":[], "missing_documents":[], "limitations":[],
                "data_completeness":"general", "memory_proposals":direct_proposals})

        comparison_request = _is_comparison_request(query)
        comparison_types = _comparison_requested_document_types(query)
        comparison_blood = _comparison_asks_blood_labs(query, comparison_types)
            or query_mentioned_people == [forced_patient]
        )
        if needs_analysis and len(mentioned) == 1 and measurement_patient_allowed:
            for measurement in (explicit_measurements if explicit_memory_command else _extract_memory_measurements(query)):
                try:
                    if not patient_memory.should_propose_measurement(
                        fid, mentioned[0], measurement["memory_key"], measurement["text"]

        rows_by_id = {}
        explicit_archive_request = bool(re.search(
            r"\b(архив|документ\w*|файл\w*|истори\w*|узи|экг|мрт|кт|выписк\w*|эпикриз\w*|результат\w*|покажи|найди|сравни|сводк\w*|пациент\w*)\b", qfold, re.I))
        if needs_analysis and not mentioned and not history and not explicit_archive_request and not forced_patient:
            # Generic medical education must not retrieve, reveal, or attach any family records.
            # Route metadata is fingerprinted; the encrypted interaction journal stores the
                provider_name, _token, _url, model_name, _key = provider_config()
                ai_trace_log.emit(trace_id, "model.configured", provider=provider_name,
                    model=model_name, mode="general_medical")
                answer = answer_archive_question(query, "не идентифицирован", context="", history=conversation, trace_id=trace_id)
                if answer.startswith("Не удалось получить ответ ИИ") or answer.startswith("Не задан "):
                    ai_trace_log.emit(trace_id, "response.complete", status="error", mode="general_medical",
                        error_type="provider_error", answer_chars=len(answer),
                    plan = {"search_terms": [], "document_types": [], "allow_full_history": False, "original_question": query}
                else:
                    try:
                        plan = _planner(search_question, token, trace_id=trace_id)
                    except Exception as exc:
                        logging.warning("Smart search planner unavailable (%s); using local keyword fallback", type(exc).__name__)
                        plan = _fallback_plan(search_question)
                    for memory_patient in memory_people:
                        snapshot = patient_memory.get_snapshot(fid, memory_patient)
                        snapshot_text = patient_memory.to_context(snapshot)
                        profile = snapshot.get("profile") if isinstance(snapshot.get("profile"), dict) else {}
                        birth_day = _parse_date(profile.get("birth_date"))
                        if birth_day:
                            today = date.today()
                            age_years = today.year - birth_day.year - ((today.month, today.day) < (birth_day.month, birth_day.day))
                            snapshot_text = (f"ВОЗРАСТ, РАССЧИТАННЫЙ СЕРВЕРОМ на {today.isoformat()}: {age_years} лет; "
                                             f"дата рождения из карточки: {birth_day.isoformat()}. Используй этот возраст вместо возраста из OCR/старых ответов.\n"
                                             + snapshot_text)
                        memory_parts.append("Пациент: " + str(memory_patient) + "\n" + snapshot_text[:per_patient_budget])
                    memory_context = "\n\n".join(memory_parts)[:8500]
                ai_trace_log.emit(trace_id, "context.assembled", memory_context_present=bool(memory_context), history_turns=len(history_for_model), source_document_ids=[int(r["id"]) for r in rows], source_count=len(rows))