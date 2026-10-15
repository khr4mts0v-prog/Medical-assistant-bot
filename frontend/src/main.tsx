import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ArrowLeft, ChevronRight, ClipboardCheck, FilePlus2, Home, Menu, Search, Plus,
  Settings, Users, X, HeartPulse, Cloud, ShieldCheck, PanelLeftClose, BrainCircuit
} from 'lucide-react';
import './style.css';

type Screen = { url: string; html: string; title: string };
const HOME = '/';

function extractContent(documentText: string): string {
  const parsed = new DOMParser().parseFromString(documentText, 'text/html');
  const main = parsed.querySelector('.app-content') || parsed.querySelector('main') || parsed.body;
  main.querySelector('.app-topbar')?.remove();
  main.querySelector('#app-sidebar')?.remove();
  main.querySelector('#sidebar-backdrop')?.remove();
  main.querySelectorAll('script').forEach(node => node.remove());
  main.querySelector('#family-settings')?.remove();
  if (!main.querySelector('.home-welcome')) {
    main.querySelectorAll('a').forEach(a => {
      if (/^(?:←\s*)?(?:в архив|к архиву|назад|ко входящим|к входящим)$/i.test((a.textContent || '').trim())) a.remove();
    });
    const patientHeading = main.querySelector('.patient-heading');
    if (patientHeading) patientHeading.classList.add('screen-heading');
    main.querySelectorAll('form.card, form:not(.home-search)').forEach(form => form.classList.add('app-form-card'));
    main.querySelectorAll('.tabs, .tab-row, nav.tabs').forEach(tabs => tabs.classList.add('app-tabs'));
  }
  const welcome = main.querySelector('.home-welcome');
  const search = main.querySelector('form.home-search');
  const upload = main.querySelector('#quick-upload');
  const actions = main.querySelector('.home-actions');
  const inboxAction = main.querySelector<HTMLAnchorElement>('.home-action[href*="/inbox"]');
  if (inboxAction) inboxAction.textContent = (inboxAction.textContent || '').replace(/^▤\\s*/, '').trim();
  if (welcome) main.insertBefore(welcome, main.firstChild);
  if (search && welcome) welcome.after(search);
  if (upload && search) search.after(upload);
  if (actions && upload) upload.after(actions);
  const archiveHeading = main.querySelector('#patients-section > h2');
  if (archiveHeading) archiveHeading.textContent = 'Семья';
  main.querySelector('#patients')?.remove();
  const addPatient = Array.from(main.querySelectorAll('a')).find(a => a.textContent?.includes('Добавить пациента'));
  if (addPatient) {
    addPatient.textContent = '＋ Добавить члена семьи';
    const patientGrid = main.querySelector('#patients-section .patient-grid');
    if (patientGrid) {
      patientGrid.after(addPatient);
      addPatient.classList.add('add-family-bottom');
      const oldHeading = main.querySelector('#patients-section > .patient-heading');
      if (oldHeading && !oldHeading.textContent?.trim()) oldHeading.remove();
    }
  }
  main.querySelector('#patients-section > p')?.remove();
  main.querySelector('.home-action[href="#patients"]')?.remove();
  main.querySelectorAll('a').forEach(a => {
    const href = a.getAttribute('href');
    if (href && href.startsWith('/') && !href.startsWith('//')) a.dataset.spa = 'true';
  });
  return main.innerHTML;
}

async function fetchScreen(url: string): Promise<Screen> {
  const response = await fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'MedicalArchiveSPA' } });
  if (response.status === 401 || response.status === 403) {
    throw new Error(response.status === 401 ? 'Сессия авторизации требует обновления. Обновите страницу и войдите снова.' : 'Недостаточно прав для просмотра этого раздела.');
  }
  const text = await response.text();
  if (!response.ok) throw new Error('Не удалось открыть раздел (' + response.status + ').');
  const parsed = new DOMParser().parseFromString(text, 'text/html');
  return { url: response.url, html: extractContent(text), title: parsed.title || 'Медицинский архив' };
}

function App() {
  const [path, setPath] = useState(location.pathname + location.search);
  const [screen, setScreen] = useState<Screen | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [menuOpen, setMenuOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [modal, setModal] = useState<Screen | null>(null);
  const [modalError, setModalError] = useState('');
  const [modalBusy, setModalBusy] = useState(false);
  const [smartSearchOpen, setSmartSearchOpen] = useState(false);
  const [smartQuery, setSmartQuery] = useState('');
  const [smartConsent, setSmartConsent] = useState(false);
  const [smartBusy, setSmartBusy] = useState(false);
  const [smartError, setSmartError] = useState('');
  const [smartResult, setSmartResult] = useState<any>(null);
  const [smartConversation, setSmartConversation] = useState<any[]>([]);
  const [toast, setToast] = useState('');
  const contentRef = useRef<HTMLDivElement>(null);
  const historyRef = useRef<string[]>([]);

  const navigate = useCallback(async (url: string, push = true) => {
    setLoading(true); setError(''); setMenuOpen(false);
    try {
      const next = await fetchScreen(url);
      if (push && url !== path) {
        historyRef.current.push(path);
        window.history.pushState({ medicalArchive: true }, '', url);
      }
      setPath(url); setScreen(next); setSettingsOpen(false);
      window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось загрузить страницу');
    } finally { setLoading(false); }
  }, [path]);

  useEffect(() => {
    navigate(location.pathname === '/app' ? HOME : location.pathname + location.search, false);
    const onPop = () => navigate(location.pathname + location.search, false);
    const onArchiveRefresh = () => navigate(location.pathname + location.search, false);
    window.addEventListener('popstate', onPop);
    window.addEventListener('medical-archive-refresh', onArchiveRefresh);
    return () => {
      window.removeEventListener('popstate', onPop);
      window.removeEventListener('medical-archive-refresh', onArchiveRefresh);
    };
  // Initial load only; popstate is managed by the listener.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    let startX = 0;
    let startY = 0;
    let tracking = false;
    const onTouchStart = (event: TouchEvent) => {
      const touch = event.touches[0];
      if (!touch) return;
      startX = touch.clientX;
      startY = touch.clientY;
      tracking = menuOpen ? startX < 330 : startX < 24;
    };
    const onTouchEnd = (event: TouchEvent) => {
      if (!tracking) return;
      tracking = false;
      const touch = event.changedTouches[0];
      if (!touch) return;
      const dx = touch.clientX - startX;
      const dy = touch.clientY - startY;
      if (Math.abs(dx) < 65 || Math.abs(dx) < Math.abs(dy) * 1.25) return;
      if (!menuOpen && dx > 0) setMenuOpen(true);
      if (menuOpen && dx < 0) setMenuOpen(false);
    };
    window.addEventListener('touchstart', onTouchStart, { passive: true });
    window.addEventListener('touchend', onTouchEnd, { passive: true });
    return () => {
      window.removeEventListener('touchstart', onTouchStart);
      window.removeEventListener('touchend', onTouchEnd);
    };
  }, [menuOpen]);

  useEffect(() => {
    const root = contentRef.current;
    if (!root || !screen) return;
    const zone = root.querySelector<HTMLElement>('#quick-upload');
    const input = root.querySelector<HTMLInputElement>('#upload-files');
    const familySelect = root.querySelector<HTMLSelectElement>('#upload-family');
    const aiConsent = root.querySelector<HTMLInputElement>('#ai-classification-consent');
    const queue = root.querySelector<HTMLElement>('#upload-queue');
    const choose = root.querySelector<HTMLButtonElement>('#choose-files');
    const openPicker = (event: MouseEvent) => {
      if ((event.target as HTMLElement).closest('button,input,a,select')) return;
      input?.click();
    };
    const chooseFiles = () => input?.click();
    const changeFiles = () => {
      const files = Array.from(input?.files || []);
      if (input) input.value = '';
      let pendingRequests = 0;
      const finishRequest = () => {
        pendingRequests -= 1;
        if (pendingRequests === 0) window.setTimeout(() => window.dispatchEvent(new Event('medical-archive-refresh')), 1800);
      };
      files.forEach(file => {
        const item = document.createElement('div');
        item.className = 'upload-item';
        item.textContent = file.name + ' · Загрузка…';
        queue?.appendChild(item);
        const data = new FormData();
        data.append('family_id', familySelect?.value || '');
        data.append('files', file, file.name);
        data.append('ai_consent', aiConsent?.checked ? 'true' : 'false');
        const xhr = new XMLHttpRequest();
        pendingRequests += 1;
        xhr.open('POST', '/upload');
        xhr.onload = () => { item.textContent = file.name + (xhr.status >= 200 && xhr.status < 300 ? ' · Передан серверу' : ' · Ошибка HTTP ' + xhr.status); finishRequest(); };
        xhr.onerror = () => { item.textContent = file.name + ' · Ошибка сети'; finishRequest(); };
        xhr.send(data);
      });
    };
    zone?.addEventListener('click', openPicker);
    choose?.addEventListener('click', chooseFiles);
    input?.addEventListener('change', changeFiles);
    const patientUploadForm = root.querySelector<HTMLFormElement>('#patient-upload form');
    const patientFileInput = patientUploadForm?.querySelector<HTMLInputElement>('input[type="file"]');
    const openPatientUpload = (event: MouseEvent) => {
      const anchor = (event.target as HTMLElement).closest('a[href="#patient-upload"]');
      if (!anchor) return;
      event.preventDefault();
      patientFileInput?.click();
    };
    const submitPatientUploadOnSelect = () => {
      if (patientFileInput?.files?.length) patientUploadForm?.requestSubmit();
    };
    root.addEventListener('click', openPatientUpload);
    patientFileInput?.addEventListener('change', submitPatientUploadOnSelect);
    const onClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      const anchor = target.closest('a') as HTMLAnchorElement | null;
      if (!anchor || anchor.target === '_blank' || anchor.hasAttribute('download')) return;
      const href = anchor.getAttribute('href');
      if (href === '#patient-upload') return;
      if (!href || href.startsWith('#') || href.startsWith('mailto:') || href.startsWith('tel:')) return;
      const next = new URL(href, location.origin);
      if (next.origin !== location.origin) return;
      event.preventDefault();
      if (/\/patients\/new\/?$/.test(next.pathname)) {
        setModalError('');
        fetchScreen(next.pathname + next.search).then(setModal).catch(e => setModalError(e instanceof Error ? e.message : 'Не удалось открыть форму'));
        return;
      }
      navigate(next.pathname + next.search + next.hash);
    };
    const onSubmit = async (event: SubmitEvent) => {
      const form = event.target as HTMLFormElement;
      if (!(form instanceof HTMLFormElement)) return;
      const action = new URL(form.action || location.href, location.origin);
      if (action.origin !== location.origin) return;
      event.preventDefault();
      const method = (form.method || 'get').toUpperCase();
      if (method === 'GET') {
        if (action.pathname === '/search' && form.classList.contains('home-search')) {
          const data = new FormData(form);
          const query = String(data.get('q') || '').trim();
          const familyId = String(data.get('family_id') || new URLSearchParams(location.search).get('family_id') || '');
          setSmartQuery(query);
          setSmartSearchOpen(true); setSmartConsent(false); setSmartError(''); setSmartResult(null); setSmartBusy(true);
          try {
            const response = await fetch('/api/intelligent-search', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify({query, family_id:familyId ? Number(familyId) : undefined, consent:false})});
            const result = await response.json();
            if (!response.ok) throw new Error(result.detail || result.error || 'Не удалось выполнить поиск.');
            setSmartResult(result);
          } catch (e) { setSmartError(e instanceof Error ? e.message : 'Ошибка поиска'); }
          finally { setSmartBusy(false); }
          return;
        }
        const params = new URLSearchParams(new FormData(form) as any);
        navigate(action.pathname + (params.size ? '?' + params.toString() : ''));
        return;
      }
      setLoading(true); setError('');
      try {
        const data = new FormData(form);
        const isBulkAssignment = action.pathname.endsWith('/inbox/assign-selected');
        const response = await fetch(action.pathname + action.search, { method, body: data, credentials: 'same-origin', redirect: 'follow' });
        const html = await response.text();
        if (!response.ok) throw new Error('Не удалось сохранить данные (' + response.status + ').');
        if (isBulkAssignment) {
          const parsedResult = new DOMParser().parseFromString(html, 'text/html');
          const resultText = (parsedResult.body.textContent || '').toLowerCase();
          if (/ошибка|не удалось|не назначен/.test(resultText)) {
            setError('Не все документы удалось назначить. Проверьте результат и повторите для оставшихся.');
          } else {
            setToast('Документы назначены пациенту');
            window.setTimeout(() => setToast(''), 3200);
          }
          const inboxLink = contentRef.current?.querySelector<HTMLAnchorElement>('a[href*="/inbox"]')?.getAttribute('href');
          const next = await fetchScreen(inboxLink || action.pathname.replace('/assign-selected',''));
          const nextUrl = next.url;
          window.history.replaceState({ medicalArchive: true }, '', nextUrl);
          setPath(nextUrl); setScreen(next); window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
          return;
        }
        const finalUrl = new URL(response.url);
        const next: Screen = { url: finalUrl.pathname + finalUrl.search, html: extractContent(html), title: new DOMParser().parseFromString(html, 'text/html').title || 'Медицинский архив' };
        window.history.pushState({ medicalArchive: true }, '', next.url);
        setPath(next.url); setScreen(next); window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
      } catch (e) { setError(e instanceof Error ? e.message : 'Ошибка отправки формы'); }
      finally { setLoading(false); }
    };
    root.addEventListener('click', onClick);
    root.addEventListener('submit', onSubmit);
    return () => { zone?.removeEventListener('click', openPicker); choose?.removeEventListener('click', chooseFiles); input?.removeEventListener('change', changeFiles); root.removeEventListener('click', openPatientUpload); patientFileInput?.removeEventListener('change', submitPatientUploadOnSelect); root.removeEventListener('click', onClick); root.removeEventListener('submit', onSubmit); };
  }, [screen, navigate]);

  const isHome = path === '/' || path === '/app' || path.startsWith('/?');
  const back = () => {
    if (historyRef.current.length) { const previous = historyRef.current.pop()!; window.history.back(); navigate(previous, false); }
    else navigate(HOME);
  };

  return <div className="app-frame">
    {toast && <div className="app-toast" role="status" aria-live="polite"><span className="app-toast-check">✓</span><span>{toast}</span></div>}
    {smartSearchOpen && <div className="modal-scrim smart-search-scrim" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !smartBusy) setSmartSearchOpen(false); }}>
      <section className="app-modal smart-search-modal smart-chat-modal" role="dialog" aria-modal="true" aria-label="ИИ-чат по медицинскому архиву">
        <header className="app-modal-header">
          <div><span className="modal-eyebrow">СЕМЕЙНЫЙ АРХИВ</span><h2>ИИ-ассистент</h2><p className="smart-search-subtitle">Задавай вопросы обычным языком. Сначала ответ, ниже — документы, на которых он основан.</p></div>
          <div className="smart-chat-head-actions">
            <button type="button" className="icon-button" aria-label="Новый диалог" title="Новый диалог" disabled={smartBusy} onClick={() => {setSmartConversation([]);setSmartQuery('');setSmartResult(null);setSmartError('');setSmartConsent(false);}}><Plus size={19}/></button>
            <button type="button" className="icon-button" aria-label="Закрыть чат" onClick={() => setSmartSearchOpen(false)}><X size={20}/></button>
          </div>
        </header>
        <div className="smart-search-body smart-chat-body">
          {smartConversation.length === 0 && !smartResult?.needs_consent && <section className="smart-chat-welcome">
            <h3>Что разберём?</h3><p>Я найду подходящие документы, подготовлю сводку и укажу, если важных источников не хватает.</p>
            <div className="smart-chat-suggestions">
              <button type="button" onClick={() => setSmartQuery('Дай краткую сводку по УЗИ Саши')}>Сводка по УЗИ Саши</button>
              <button type="button" onClick={() => setSmartQuery('Сравни результаты анализов крови по датам')}>Сравнить анализы крови</button>
              <button type="button" onClick={() => setSmartQuery('Какие важные документы упоминаются в найденных заключениях, но не находятся в архиве?')}>Проверить ссылки на документы</button>
            </div>
          </section>}
          <div className="smart-chat-history">
            {smartConversation.map((turn:any, index:number) => <article className="smart-chat-turn" key={index}>
              <div className="smart-user-message"><span>Вы</span><div>{turn.question}</div></div>
              {turn.result?.answer && <article className="smart-answer"><h3><BrainCircuit size={17}/> Ответ ассистента</h3><pre>{turn.result.answer}</pre></article>}
              {turn.result?.missing_documents?.length > 0 && <section className="smart-gaps">
                <h3><FilePlus2 size={17}/> Что может не хватать</h3>
                <p className="smart-gap-intro">Я проверил архив по названиям документов из найденных заключений. Если нужного файла здесь нет, загружать его необязательно — сводка выше уже составлена по доступным источникам.</p>
                {turn.result.missing_documents.map((gap:any, gapIndex:number) => <div className="smart-gap-card" key={gapIndex}>
                  <strong>{gap.name}</strong><p>{gap.reason}</p>
                  {gap.status === 'candidate_found' ? <small className="smart-gap-status">Есть совпадение по поисковым словам среди архивных документов; проверьте, что это именно нужный источник.</small> : <small className="smart-gap-status">Не найден по названию в доступном архиве. Возможно, он сохранён под другим именем.</small>}
                  <div className="smart-gap-actions">
                    <button type="button" onClick={() => {setSmartQuery('Найди документы: ' + gap.name + (turn.result.documents?.[0]?.patient ? ' для ' + turn.result.documents[0].patient : ''));setSmartResult(null);}}>Проверить в архиве</button>
                    <button type="button" onClick={() => {setSmartSearchOpen(false);navigate('/');}}>Загрузить, если файл есть</button>
                  </div>
                </div>)}
              </section>}
              {turn.result?.limitations?.length > 0 && <section className="smart-limitations"><strong>Ограничения вывода</strong><ul>{turn.result.limitations.map((item:string, i:number)=><li key={i}>{item}</li>)}</ul></section>}
              {turn.result?.documents && <section className="smart-documents"><h3>{turn.result.mode === 'analysis' ? 'Документы-источники' : 'Найденные документы'} <span>{turn.result.documents.length}</span></h3>
                {turn.result.documents.length === 0 ? <p className="muted">Подходящих документов не найдено.</p> : turn.result.documents.map((doc:any) => <a className="smart-document" href={doc.url} key={doc.id} onClick={event => {event.preventDefault();setSmartSearchOpen(false);navigate(doc.url);}}>
                  <span className="smart-document-date">{doc.date || 'Дата не указана'}</span><strong>{doc.name}</strong><span>{doc.patient} · {doc.kind}</span><span className="smart-document-open">Открыть документ <ChevronRight size={16}/></span>
                </a>)}
              </section>}
            </article>)}
          </div>
          {smartBusy && <div className="smart-search-loading" role="status"><span className="smart-spinner"/>Ищу документы и готовлю ответ…</div>}
          {smartError && <div className="error-banner" role="alert">{smartError}</div>}
          {smartResult?.needs_consent && <p className="smart-consent-note">{smartResult.message}</p>}
          <form className="smart-search-form smart-chat-compose" onSubmit={async event => {
            event.preventDefault();
            const submittedQuestion = smartQuery.trim();
            if (!submittedQuestion) return;
            setSmartBusy(true);setSmartError('');
            try {
              const familyId = new URLSearchParams(location.search).get('family_id');
              const history = smartConversation.map((turn:any) => String(turn.question || '')).slice(-5);
              const response = await fetch('/api/intelligent-search', {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:submittedQuestion,history,family_id:familyId ? Number(familyId) : undefined,consent:smartConsent})});
              const result = await response.json();
              if (!response.ok) throw new Error(result.detail || result.error || 'Не удалось выполнить запрос.');
              if (result.needs_consent) {
                setSmartResult(result);
                setSmartConsent(false);
              } else {
                setSmartConversation((previous:any[]) => [...previous,{question:submittedQuestion,result}].slice(-20));
                setSmartResult(null);
                setSmartQuery('');
              }
            } catch (e) {setSmartError(e instanceof Error ? e.message : 'Не удалось выполнить запрос');}
            finally {setSmartBusy(false);}
          }}>
            <label htmlFor="smart-search-query">Что хочешь узнать?</label>
            <textarea id="smart-search-query" rows={2} maxLength={1200} value={smartQuery} onChange={e => setSmartQuery(e.target.value)} placeholder="Например: Дай краткую сводку по УЗИ Саши" required />
            {smartResult?.needs_consent && <label className="smart-consent"><input type="checkbox" checked={smartConsent} onChange={e => setSmartConsent(e.target.checked)} /> Я разрешаю отправить вопрос и найденные фрагменты медицинских документов внешнему ИИ-провайдеру для анализа.</label>}
            <button type="submit" disabled={smartBusy || !smartQuery.trim()}>{smartBusy ? 'Готовлю ответ…' : smartResult?.needs_consent ? 'Продолжить анализ' : 'Отправить'}</button>
          </form>
          <p className="smart-search-footnote">Медицинские фрагменты передаются внешней модели только после явного согласия. ИИ может ошибаться; источники всегда доступны для проверки.</p>
        </div>
      </section>
    </div>}
    {modal && <div className="modal-scrim" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !modalBusy) setModal(null); }}>
      <section className="app-modal" role="dialog" aria-modal="true" aria-label="Добавить члена семьи">
        <header className="app-modal-header"><div><span className="modal-eyebrow">СЕМЕЙНЫЙ АРХИВ</span><h2>Добавить члена семьи</h2></div><button type="button" className="icon-button" aria-label="Закрыть окно" onClick={() => setModal(null)}><X size={20}/></button></header>
        {modalError && <div className="error-banner" role="alert">{modalError}</div>}
        <div className="app-modal-content" onSubmit={async event => {
          const form = event.target as HTMLFormElement;
          if (!(form instanceof HTMLFormElement) || !form.action.includes('/patients')) return;
          event.preventDefault(); setModalBusy(true); setModalError('');
          try {
            const response = await fetch(form.action, {method:(form.method || 'post').toUpperCase(), body:new FormData(form), credentials:'same-origin', redirect:'follow'});
            const html = await response.text();
            if (!response.ok) throw new Error('Не удалось сохранить данные (' + response.status + ').');
            const finalUrl = new URL(response.url);
            const next: Screen = {url:finalUrl.pathname + finalUrl.search, html:extractContent(html), title:new DOMParser().parseFromString(html,'text/html').title || 'Медицинский архив'};
            window.history.pushState({medicalArchive:true},'',next.url); setPath(next.url); setScreen(next); setModal(null); window.scrollTo({top:0,behavior:'instant' as ScrollBehavior});
          } catch (e) {setModalError(e instanceof Error ? e.message : 'Ошибка сохранения');}
          finally {setModalBusy(false);}
        }} dangerouslySetInnerHTML={{__html:modal.html}} />
        {modalBusy && <div className="modal-busy" role="status">Сохраняем карточку…</div>}
      </section>
    </div>}
    {menuOpen && <button className="scrim" aria-label="Закрыть меню" onClick={() => setMenuOpen(false)} />}
    <aside className={'sidebar ' + (menuOpen ? 'sidebar-open' : '')}>
      <div className="brand"><span className="brand-icon"><HeartPulse size={22}/></span><span>Медицинский архив</span><button className="icon-button sidebar-close" onClick={() => setMenuOpen(false)} aria-label="Закрыть"><X size={20}/></button></div>
      <button className={'nav-item ' + (isHome ? 'active' : '')} onClick={() => navigate(HOME)}><Home size={19}/>Главная</button>
      <button className="nav-item" onClick={() => { const link = document.querySelector<HTMLAnchorElement>('.app-content a[href*="/inbox"]'); navigate(link?.getAttribute('href') || '/search'); }}><ClipboardCheck size={19}/>Требуют проверки</button>
      <button className="nav-item" onClick={() => navigate('/search')}><Search size={19}/>Поиск</button>
      <button className="nav-item" onClick={() => navigate('/assistant')}><BrainCircuit size={19}/>Ассистент</button>
      <div className="sidebar-spacer"/>
      <button className={'nav-item ' + (settingsOpen ? 'active' : '')} onClick={() => navigate('/settings' + (location.search || ''))}><Settings size={19}/>Настройки архива</button>
      <div className="sidebar-foot"><ShieldCheck size={16}/> Данные хранятся на вашем сервере</div>
    </aside>
    <main className="main-area">
      <header className="topbar">
        <button className="icon-button menu-button" onClick={() => setMenuOpen(true)} aria-label="Открыть меню"><Menu size={23}/></button>
        {!isHome && <button className="back-button" onClick={back}><ArrowLeft size={18}/> Назад</button>}
        <div className="topbar-title">{isHome ? 'Семейный медицинский архив' : 'Медицинский архив'}</div>
      </header>
      {settingsOpen ? <section className="settings-view">
        <div className="eyebrow">ПАРАМЕТРЫ</div><h1>Настройки архива</h1><p className="lead">Управление семейным архивом и хранением документов.</p>
        <article className="settings-card"><div className="settings-icon"><Users size={21}/></div><div><h2>Семейный архив</h2><p>Имя архива и данные семьи будут доступны здесь после подключения безопасного редактирования на сервере.</p></div></article>
        <article className="settings-card"><div className="settings-icon"><Cloud size={21}/></div><div><h2>Хранение документов</h2><p>Сейчас документы хранятся локально на VPS. Подключение Яндекс Диска добавим отдельным этапом с OAuth и проверкой прав доступа.</p><span className="status-pill">Локальное хранилище</span></div></article>
        <article className="settings-card"><div className="settings-icon"><ShieldCheck size={21}/></div><div><h2>Безопасность</h2><p>Не храните медицинские данные в публичном кеше браузера. Перед использованием реальных документов необходимо проверить резервное копирование.</p></div></article>
      </section> : <section className={'page-content ' + (loading ? 'is-loading' : '')}>
        {error && <div className="error-banner" role="alert">{error}<button onClick={() => navigate(path, false)}>Повторить</button></div>}
        {loading && !screen ? <div className="skeleton"><div/><div/><div/></div> : <div ref={contentRef} className="legacy-content" dangerouslySetInnerHTML={{ __html: screen?.html || '' }} />}
        {loading && screen && <div className="loading-line"/>}
      </section>}
    </main>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);