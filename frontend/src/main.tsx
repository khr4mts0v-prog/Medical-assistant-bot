
// Last-resort presentation guard: never render a serialized structured answer as chat prose.
function readableAnswer(value: unknown): string {
  let cleaned = String(value ?? '').trim();
  if (!cleaned) return '';
  cleaned = cleaned.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();
  // Some compatible models double-serialize the structured response. Unwrap only answer
  // envelopes, with a bound to avoid loops; never display the JSON payload as chat prose.
  for (let depth = 0; depth < 3; depth += 1) {
    try {
      const parsed = JSON.parse(cleaned);
      if (parsed && typeof parsed === 'object' && typeof parsed.answer === 'string' && parsed.answer.trim()) {
        cleaned = parsed.answer.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '').trim();
        continue;
      }
      break;
    } catch { break; }
  }
  if (/^\s*\{/.test(cleaned) && /"(?:answer|missing_documents|data_completeness)"\s*:/.test(cleaned)) {
    return 'Не удалось корректно отобразить ответ модели. Повтори вопрос.';
  }
  return cleaned;
}

function extractContent(documentText: string): string {
  }
  main.querySelector('#patients-section > p')?.remove();
  main.querySelector('.home-action[href="#patients"]')?.remove();
  if (actions && !actions.querySelector('a')) actions.remove();
  main.querySelectorAll('a').forEach(a => {
    const href = a.getAttribute('href');
    if (href && href.startsWith('/') && !href.startsWith('//')) a.dataset.spa = 'true';
  }, [screen, navigate]);

  const isHome = path === '/' || path === '/app' || path.startsWith('/?');
  const hasPendingInbox = !isHome || Boolean(screen?.html && /href=["']\/families\/\d+\/inbox/.test(screen.html));
  useEffect(() => {
    setDocumentSelectionActive(false);
    setSelectedDocumentIds([]);
            {smartConversation.map((turn:any, index:number) => <article className="smart-chat-turn" key={index}>
              <div className="smart-user-message"><span>Вы</span><div>{turn.question}</div></div>
              {turn.result?.answer && <article className="smart-answer"><h3><BrainCircuit size={17}/> Ответ ассистента</h3><pre>{readableAnswer(turn.result.answer)}</pre></article>}
              {turn.result?.data_completeness && turn.result.mode !== 'general_medical' && <details className="smart-extra-details">
                <summary>Полнота исходных данных</summary>
                <div className={"smart-completeness completeness-" + turn.result.data_completeness}>
                  <strong>{turn.result.data_completeness === 'sufficient' ? 'Достаточно для краткой сводки' : turn.result.data_completeness === 'insufficient' ? 'Данных недостаточно' : turn.result.data_completeness === 'partial' ? 'Частичная картина' : 'Не удалось оценить'}</strong>
                </div>
              </details>}
              {turn.result?.missing_documents?.length > 0 && <section className="smart-gaps">
                <h3><FilePlus2 size={17}/> Что может не хватать</h3>
                <p className="smart-gap-intro">Я дополнительно проверил архив по названиям и ключевым словам из найденных заключений. Если нужного файла здесь нет, загружать его необязательно — сводка выше уже составлена по доступным источникам.</p>
                  </div>
                </div>)}
              </section>}
              {turn.result?.limitations?.length > 0 && <details className="smart-extra-details smart-limitations"><summary>Ограничения и оговорки</summary><ul>{turn.result.limitations.map((item:string, i:number)=><li key={i}>{item}</li>)}</ul></details>}
              {turn.result?.memory_proposals?.length > 0 && <section className="smart-memory-proposals">
                <h3><BrainCircuit size={17}/> Предлагаю сохранить в память пациента</h3>
                <p>Эти записи пока не сохранены. Проверь содержание и подтверди только то, что действительно нужно помнить.</p>
                  </div>
                </article>)}
              </section>}
              {turn.result?.documents && turn.result.mode !== 'general_medical' && <details className="smart-extra-details smart-documents"><summary>{turn.result.mode === 'analysis' ? 'Документы-источники' : 'Найденные документы'} · {turn.result.documents.length}</summary>
                {turn.result.documents.length === 0 ? <p className="muted">Подходящих документов не найдено.</p> : turn.result.documents.map((doc:any) => <a className="smart-document" href={doc.url} key={doc.id} onClick={event => {event.preventDefault();setSmartSearchOpen(false);navigate(doc.url);}}>
                  <span className="smart-document-date">{doc.date || 'Дата не указана'}</span><strong>{doc.name}</strong><span>{doc.patient} · {doc.kind}</span><span className="smart-document-open">Открыть документ <ChevronRight size={16}/></span>
                </a>)}
              </details>}
            </article>)}
          </div>
          {smartBusy && <div className="smart-search-loading" role="status"><span className="smart-spinner"/>Ищу документы и готовлю ответ…</div>}
              if (selectionMode && selectedDocumentIds.length > 40) throw new Error('Выбрано слишком много документов. Максимум — 40 за один запрос.');
              const conversation = (selectionMode ? [] : smartConversation.slice(-5)).map((turn:any) => ({
                question: String(turn.question || ''),
                answer: readableAnswer(turn.result?.answer || '').slice(0, 900),
                mode: String(turn.result?.mode || ''),
              }));
              const history = conversation.map((turn:any) => turn.question);
    </div>}
    {menuOpen && <button className="scrim" aria-label="Закрыть меню" onClick={() => setMenuOpen(false)} />}
    <aside className={'sidebar ' + (menuOpen ? 'sidebar-open' : '')}>
      <div className="brand"><span className="brand-icon"><HeartPulse size={22}/></span><span>Семейный медицинский архив</span><button className="icon-button sidebar-close" onClick={() => setMenuOpen(false)} aria-label="Закрыть"><X size={20}/></button></div>
      <button className={'nav-item ' + (isHome ? 'active' : '')} onClick={() => navigate(HOME)}><Home size={19}/>Главная</button>
      {hasPendingInbox && <button className="nav-item" onClick={() => { const link = document.querySelector<HTMLAnchorElement>('.app-content a[href*="/inbox"]'); navigate(link?.getAttribute('href') || '/search'); }}><ClipboardCheck size={19}/>Требуют проверки</button>}
      <button className="nav-item" onClick={() => navigate('/search')}><Search size={19}/>Поиск</button>
      <button className="nav-item" onClick={() => navigate('/assistant')}><BrainCircuit size={19}/>Ассистент</button>
      <div className="sidebar-spacer"/>
      <header className="topbar">
        <button className="icon-button menu-button" onClick={() => setMenuOpen(true)} aria-label="Открыть меню"><Menu size={23}/></button>
        {!isHome && <button className="back-button" onClick={back}><ArrowLeft size={18}/> Назад</button>}
        <div className="topbar-title">Семейный медицинский архив</div>
      </header>
      {settingsOpen ? <section className="settings-view">
        <div className="eyebrow">ПАРАМЕТРЫ</div><h1>Настройки архива</h1><p className="lead">Управление семейным архивом и хранением документов.</p>