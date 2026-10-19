import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ChevronRight, ClipboardCheck, FilePlus2, Home, Menu, Search, Plus,
  Settings, Users, X, HeartPulse, Cloud, ShieldCheck, PanelLeftClose, BrainCircuit
} from 'lucide-react';
import './style.css';

type Screen = { url: string; html: string; title: string };
const HOME = '/';

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
  const search = main.querySelector<HTMLFormElement>('form.home-search');
  const searchInput = search?.querySelector<HTMLInputElement>('input[type="search"], input[type="text"]');
  if (searchInput) searchInput.placeholder = 'Быстрый запрос';
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
  if (actions && !actions.querySelector('a')) actions.remove();
  main.querySelectorAll('a').forEach(a => {
    const href = a.getAttribute('href');
    if (href && href.startsWith('/') && !href.startsWith('//')) a.dataset.spa = 'true';
  });
  return main.innerHTML;
}

async function fetchScreen(url: string): Promise<Screen> {
  const response = await fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'MedicalArchiveSPA' } });
  if (response.status === 401) {
    window.location.assign('/login?next=' + encodeURIComponent(url));
    throw new Error('Перенаправление на вход…');
  }
  if (response.status === 403) {
    throw new Error('Недостаточно прав для просмотра этого раздела.');
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
  const [patientsExpanded, setPatientsExpanded] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [modal, setModal] = useState<Screen | null>(null);
  const [modalError, setModalError] = useState('');
  const [modalBusy, setModalBusy] = useState(false);
  const [smartSearchOpen, setSmartSearchOpen] = useState(false);
  const [patientAssistantScope, setPatientAssistantScope] = useState<{familyId:number; patient:string} | null>(null);
  const [documentSelectionActive, setDocumentSelectionActive] = useState(false);
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<number[]>([]);
  const [smartQuery, setSmartQuery] = useState('');
  const [smartConsent, setSmartConsent] = useState(false);
  const [aiConsentGranted, setAiConsentGranted] = useState(false);
  const [aiConsentLoaded, setAiConsentLoaded] = useState(false);
  const [aiConsentActionBusy, setAiConsentActionBusy] = useState(false);
  const [aiConsentError, setAiConsentError] = useState('');
  const [smartBusy, setSmartBusy] = useState(false);
  const [smartError, setSmartError] = useState('');
  const [smartResult, setSmartResult] = useState<any>(null);
  const [smartConversation, setSmartConversation] = useState<any[]>([]);
  const [toast, setToast] = useState('');
  const contentRef = useRef<HTMLDivElement>(null);
  const historyRef = useRef<string[]>([]);

  useEffect(() => {
    let active = true;
    fetch('/api/ai-consent', { credentials: 'same-origin' })
      .then(response => response.ok ? response.json() : Promise.reject(new Error('Не удалось получить настройки согласия')))
      .then(data => { if (active) setAiConsentGranted(data.granted === true); })
      .catch(() => { if (active) setAiConsentGranted(false); })
      .finally(() => { if (active) setAiConsentLoaded(true); });
    return () => { active = false; };
  }, []);

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

  // Recover promptly if a session expires while the PWA remains open or returns from the background.
  useEffect(() => {
    let active = true;
    const checkSession = async () => {
      try {
        const response = await fetch('/auth/status', { credentials: 'same-origin', cache: 'no-store' });
        if (active && response.status === 401) {
          window.location.replace('/login?next=' + encodeURIComponent(location.pathname + location.search));
        }
      } catch {
        // Temporary network errors must not sign the user out.
      }
    };
    const onFocus = () => { void checkSession(); };
    window.addEventListener('focus', onFocus);
    const timer = window.setInterval(checkSession, 60000);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener('focus', onFocus);
    };
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
      if ((event.target as HTMLElement).closest('button,input,a,select,label')) return;
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
      const patientAssistant = target.closest<HTMLAnchorElement>('[data-patient-assistant]');
      if (patientAssistant) {
        event.preventDefault();
        const familyId = Number(patientAssistant.dataset.familyId || '');
        const patient = String(patientAssistant.dataset.patient || '').trim();
        if (!Number.isInteger(familyId) || familyId <= 0 || !patient) return;
        setPatientAssistantScope({familyId, patient});
        setSmartConversation([]); setSmartQuery(''); setSmartResult(null); setSmartError(''); setSmartConsent(false);
        setSmartSearchOpen(true);
        return;
      }
      const selectionToggle = target.closest<HTMLButtonElement>('[data-toggle-document-selection]');
      if (selectionToggle) {
        event.preventDefault();
        const tree = selectionToggle.closest<HTMLElement>('[data-patient-document-tree]');
        if (!tree) return;
        const enabled = !tree.classList.contains('document-selection-active');
        tree.classList.toggle('document-selection-active', enabled);
        selectionToggle.setAttribute('aria-pressed', enabled ? 'true' : 'false');
        selectionToggle.textContent = enabled ? 'Отменить выбор' : 'Выбрать документы';
        const note = tree.querySelector<HTMLElement>('[data-selection-note]');
        if (note) note.hidden = !enabled;
        if (!enabled) {
          tree.querySelectorAll<HTMLInputElement>('[data-document-id]').forEach(input => { input.checked = false; });
          setSelectedDocumentIds([]);
        }
        setDocumentSelectionActive(enabled);
        return;
      }
      const clearSelection = target.closest<HTMLButtonElement>('[data-clear-document-selection]');
      if (clearSelection) {
        event.preventDefault();
        const tree = clearSelection.closest<HTMLElement>('[data-patient-document-tree]');
        tree?.querySelectorAll<HTMLInputElement>('[data-document-id]').forEach(input => { input.checked = false; });
        setSelectedDocumentIds([]);
        return;
      }
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
          setPatientAssistantScope(null);
          setDocumentSelectionActive(false);
          setSelectedDocumentIds([]);
          setSmartConversation([]);
          setSmartQuery(query);
          setSmartSearchOpen(true);
          setSmartConsent(false);
          setSmartError('');
          setSmartResult(null);
          setSmartBusy(false);
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
    const onDocumentSelectionChange = (event: Event) => {
      const input = event.target as HTMLInputElement;
      if (!input.matches('[data-document-id]')) return;
      setSelectedDocumentIds(previous => {
        const id = Number(input.dataset.documentId || '');
        if (!Number.isInteger(id) || id <= 0) return previous;
        return input.checked ? Array.from(new Set([...previous, id])) : previous.filter(value => value !== id);
      });
    };
    root.addEventListener('click', onClick);
    root.addEventListener('change', onDocumentSelectionChange);
    root.addEventListener('submit', onSubmit);
    return () => { zone?.removeEventListener('click', openPicker); choose?.removeEventListener('click', chooseFiles); input?.removeEventListener('change', changeFiles); root.removeEventListener('click', openPatientUpload); patientFileInput?.removeEventListener('change', submitPatientUploadOnSelect); root.removeEventListener('click', onClick); root.removeEventListener('change', onDocumentSelectionChange); root.removeEventListener('submit', onSubmit); };
  }, [screen, navigate]);

  const isHome = path === '/' || path === '/app' || path.startsWith('/?');
  const patientMenuItems = React.useMemo(() => {
    if (!screen?.html) return [];
    const parsed = new DOMParser().parseFromString(screen.html, 'text/html');
    return Array.from(parsed.querySelectorAll<HTMLAnchorElement>('.patient-card[href]')).map(a => ({ href: a.getAttribute('href') || '/', label: (a.querySelector('strong')?.textContent || a.textContent || '').trim().replace(/\s+/g, ' ') })).filter(item => item.label && item.href.startsWith('/'));
  }, [screen]);
  const hasPendingInbox = !isHome || Boolean(screen?.html && /href=["']\/families\/\d+\/inbox/.test(screen.html));
  useEffect(() => {
    setDocumentSelectionActive(false);
    setSelectedDocumentIds([]);
    setPatientAssistantScope(null);
    setSmartSearchOpen(false);
  }, [path]);

  const handleMemoryProposal = async (proposal: any, action: 'accept' | 'reject', turnIndex: number) => {
    setSmartError('');
    try {
      const response = await fetch('/api/patient-memory/proposal-action', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action,
          proposal_id: proposal.id,
          family_id: proposal.family_id,
          patient: proposal.patient,
        }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Не удалось обновить память пациента.');
      setSmartConversation((previous: any[]) => previous.map((turn: any, index: number) =>
        index === turnIndex
          ? { ...turn, result: { ...turn.result, memory_proposals: (turn.result?.memory_proposals || []).filter((item: any) => item.id !== proposal.id) } }
          : turn
      ));
      setToast(action === 'accept' ? 'Запись добавлена в память пациента' : 'Предложение отклонено');
    } catch (e) {
      setSmartError(e instanceof Error ? e.message : 'Не удалось изменить память пациента');
    }
  };

  return <div className="app-frame">
    {toast && <div className="app-toast" role="status" aria-live="polite"><span className="app-toast-check">✓</span><span>{toast}</span></div>}
    {smartSearchOpen && <div className="modal-scrim smart-search-scrim" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !smartBusy) setSmartSearchOpen(false); }}>
      <section className="app-modal smart-search-modal smart-chat-modal" role="dialog" aria-modal="true" aria-label="ИИ-чат по медицинскому архиву">
        <header className="app-modal-header">
          <div><span className="modal-eyebrow">{patientAssistantScope ? 'КАРТОЧКА ПАЦИЕНТА' : 'СЕМЕЙНЫЙ АРХИВ'}</span><h2>{patientAssistantScope ? 'ИИ по пациенту: ' + patientAssistantScope.patient : 'ИИ-ассистент'}</h2><p className="smart-search-subtitle">{patientAssistantScope ? (documentSelectionActive ? 'Режим выбора: анализирую только отмеченные документы и память этого пациента.' : 'Поиск и анализ ограничены этим пациентом; по умолчанию ИИ сам подберёт релевантные документы и учтёт его память.') : 'Задавай вопросы обычным языком. Сначала ответ, ниже — документы, на которых он основан.'}</p></div>
          <div className="smart-chat-head-actions">
            <button type="button" className="icon-button" aria-label="Новый диалог" title="Новый диалог" disabled={smartBusy} onClick={() => {setSmartConversation([]);setSmartQuery('');setSmartResult(null);setSmartError('');setSmartConsent(false);}}><Plus size={19}/></button>
            <button type="button" className="icon-button" aria-label="Закрыть чат" onClick={() => setSmartSearchOpen(false)}><X size={20}/></button>
          </div>
        </header>
        <div className="smart-search-body smart-chat-body">
          {patientAssistantScope && documentSelectionActive && <div className="smart-selected-sources-note"><strong>Выбрано документов: {selectedDocumentIds.length}</strong><span>Будут использованы только эти файлы и память пациента. Чтобы изменить набор, закрой чат и отметь нужные файлы в дереве.</span></div>}
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
              {turn.result?.answer && <article className="smart-answer"><h3><BrainCircuit size={17}/> Ответ ассистента {turn.result.generation_status === 'partial' && <span className="smart-generation-warning" role="status">Ответ может быть неполным</span>}</h3><pre>{readableAnswer(turn.result.answer)}</pre></article>}
              {turn.result?.data_completeness && turn.result.mode !== 'general_medical' && <details className="smart-extra-details">
                <summary>Полнота исходных данных</summary>
                <div className={"smart-completeness completeness-" + turn.result.data_completeness}>
                  <strong>{turn.result.data_completeness === 'sufficient' ? 'Достаточно для краткой сводки' : turn.result.data_completeness === 'insufficient' ? 'Данных недостаточно' : turn.result.data_completeness === 'partial' ? 'Частичная картина' : 'Не удалось оценить'}</strong>
                </div>
              </details>}
              {turn.result?.missing_documents?.length > 0 && <section className="smart-gaps">
                <h3><FilePlus2 size={17}/> Что может не хватать</h3>
                <p className="smart-gap-intro">Я дополнительно проверил архив по названиям и ключевым словам из найденных заключений. Если нужного файла здесь нет, загружать его необязательно — сводка выше уже составлена по доступным источникам.</p>
                {turn.result.missing_documents.map((gap:any, gapIndex:number) => <div className="smart-gap-card" key={gapIndex}>
                  <strong>{gap.name}</strong><p>{gap.reason}</p>
                  {gap.status === 'candidate_found' ? <small className="smart-gap-status">Есть совпадение по поисковым словам среди архивных документов; проверьте, что это именно нужный источник.</small> : gap.status === 'not_found' ? <small className="smart-gap-status">Не найден по названию и ключевым словам в доступном архиве. Возможно, он сохранён под другим именем.</small> : <small className="smart-gap-status">Автоматически проверить этот документ не удалось. Можно выполнить поиск вручную.</small>}
                  <div className="smart-gap-actions">
                    <button type="button" onClick={() => {setSmartQuery('Найди документы: ' + gap.name + (turn.result.documents?.[0]?.patient ? ' для ' + turn.result.documents[0].patient : ''));setSmartResult(null);}}>Проверить в архиве</button>
                    <button type="button" onClick={() => {setSmartSearchOpen(false);navigate('/');}}>Загрузить, если файл есть</button>
                  </div>
                </div>)}
              </section>}
              {turn.result?.limitations?.length > 0 && <details className="smart-extra-details smart-limitations"><summary>Ограничения и оговорки</summary><ul>{turn.result.limitations.map((item:string, i:number)=><li key={i}>{item}</li>)}</ul></details>}
              {turn.result?.memory_proposals?.length > 0 && <section className="smart-memory-proposals">
                <h3><BrainCircuit size={17}/> Предлагаю сохранить в память пациента</h3>
                <p>Эти записи пока не сохранены. Проверь содержание и подтверди только то, что действительно нужно помнить.</p>
                {turn.result.memory_proposals.map((proposal:any) => <article className="smart-memory-proposal" key={proposal.id}>
                  <strong>{proposal.text}</strong>
                  {proposal.reason && <p>{proposal.reason}</p>}
                  <small>{proposal.source?.document_id ? ('Источник: ' + (proposal.source.name || 'документ') + (proposal.source.date ? ' · ' + proposal.source.date : '')) : 'Источник: сообщение пользователя'}</small>
                  <div className="smart-memory-actions">
                    <button type="button" onClick={() => handleMemoryProposal(proposal, 'accept', index)} disabled={smartBusy}>Добавить в память</button>
                    <button type="button" onClick={() => handleMemoryProposal(proposal, 'reject', index)} disabled={smartBusy}>Не сохранять</button>
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
          {smartError && <div className="error-banner" role="alert">{smartError}</div>}
          {smartResult?.needs_consent && <p className="smart-consent-note">{smartResult.message}</p>}
          <form className="smart-search-form smart-chat-compose" onSubmit={async event => {
            event.preventDefault();
            const submittedQuestion = smartQuery.trim();
            if (!submittedQuestion) return;
            setSmartBusy(true);setSmartError('');
            try {
              const familyId = patientAssistantScope?.familyId || Number(new URLSearchParams(location.search).get('family_id') || 0) || undefined;
              const selectionMode = Boolean(patientAssistantScope && documentSelectionActive);
              if (selectionMode && selectedDocumentIds.length === 0) throw new Error('Отметьте документы в дереве пациента или отключите режим выбора.');
              if (selectionMode && selectedDocumentIds.length > 40) throw new Error('Выбрано слишком много документов. Максимум — 40 за один запрос.');
              const conversation = (selectionMode ? [] : smartConversation.slice(-5)).map((turn:any) => ({
                question: String(turn.question || ''),
                answer: readableAnswer(turn.result?.answer || '').slice(0, 900),
                mode: String(turn.result?.mode || ''),
              }));
              const history = conversation.map((turn:any) => turn.question);
              const response = await fetch('/api/intelligent-search', {method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({query:submittedQuestion,history,conversation,family_id:familyId,patient_scope:patientAssistantScope?.patient,document_selection_mode:selectionMode,selected_document_ids:selectionMode ? selectedDocumentIds : [],consent:smartConsent})});
              const result = await response.json();
              if (!response.ok) throw new Error(result.detail || result.error || 'Не удалось выполнить запрос.');
              if (result.needs_consent) {
                setSmartResult(result);
                setSmartConsent(false);
              } else {
                if (smartConsent) {
                  // Reflect the server's persisted consent state; a checkbox alone does not grant consent.
                  try {
                    const consentResponse = await fetch('/api/ai-consent', {credentials:'same-origin'});
                    if (consentResponse.ok) {
                      const consentState = await consentResponse.json();
                      setAiConsentGranted(consentState.granted === true);
                    }
                  } catch {}
                  setSmartConsent(false);
                }
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
      <div className="brand"><span className="brand-icon"><HeartPulse size={22}/></span><span>Семейный медицинский архив</span><button className="icon-button sidebar-close" onClick={() => setMenuOpen(false)} aria-label="Закрыть"><X size={20}/></button></div>
      <button className={'nav-item ' + (isHome ? 'active' : '')} onClick={() => navigate(HOME)}><Home size={19}/>Главная</button>
      <button className={'nav-item ' + (patientsExpanded ? 'active' : '')} aria-expanded={patientsExpanded} onClick={() => setPatientsExpanded(value => !value)}><Users size={19}/>Пациенты <ChevronRight className={patientsExpanded ? 'submenu-chevron expanded' : 'submenu-chevron'} size={16}/></button>
      {patientsExpanded && <div className="patient-submenu">{patientMenuItems.length ? patientMenuItems.map((patient, index) => <button className="nav-subitem" key={patient.href + index} onClick={() => navigate(patient.href)}>{patient.label}</button>) : <span className="nav-subitem-empty">Открываем список пациентов…</span>}</div>}
      {hasPendingInbox && <button className="nav-item" onClick={() => { const link = document.querySelector<HTMLAnchorElement>('.app-content a[href*="/inbox"]'); navigate(link?.getAttribute('href') || '/search'); }}><ClipboardCheck size={19}/>Требуют проверки</button>}
      <button className="nav-item" onClick={() => navigate('/search')}><Search size={19}/>Поиск</button>
      <button className="nav-item" onClick={() => navigate('/assistant')}><BrainCircuit size={19}/>Ассистент</button>
      <div className="sidebar-spacer"/>
      <button className={'nav-item ' + (settingsOpen ? 'active' : '')} onClick={() => { setSettingsOpen(true); setMenuOpen(false); }}><Settings size={19}/>Настройки архива</button>
      <div className="sidebar-foot"><ShieldCheck size={16}/> Данные хранятся на вашем сервере</div>
    </aside>
    <main className="main-area">
      <header className="topbar">
        <button className="icon-button menu-button" onClick={() => setMenuOpen(true)} aria-label="Открыть меню"><Menu size={23}/></button>
        {!isHome && <button className="home-button" onClick={() => navigate(HOME)} aria-label="На главную" title="Домой"><Home size={18}/>Домой</button>}
        <div className="topbar-title">Семейный медицинский архив</div>
      </header>
      {settingsOpen ? <section className="settings-view">
        <div className="eyebrow">ПАРАМЕТРЫ</div><h1>Настройки архива</h1><p className="lead">Управление семейным архивом и хранением документов.</p>
        <article className="settings-card"><div className="settings-icon"><Users size={21}/></div><div><h2>Семейный архив</h2><p>Имя архива и данные семьи будут доступны здесь после подключения безопасного редактирования на сервере.</p></div></article>
        <article className="settings-card"><div className="settings-icon"><Cloud size={21}/></div><div><h2>Хранение документов</h2><p>Сейчас документы хранятся локально на VPS. Подключение Яндекс Диска добавим отдельным этапом с OAuth и проверкой прав доступа.</p><span className="status-pill">Локальное хранилище</span></div></article>
        <article className="settings-card"><div className="settings-icon"><BrainCircuit size={21}/></div><div>
          <h2>Внешний ИИ-анализ</h2>
          <p>При включении внешнему ИИ-провайдеру передаётся ваш вопрос и только отобранные релевантные фрагменты документов выбранного пациента. Весь архив целиком не отправляется. Вход в аккаунт сам по себе не означает согласия.</p>
          <span className="status-pill">{!aiConsentLoaded ? 'Проверка настроек…' : aiConsentGranted ? 'Согласие включено' : 'Согласие не дано'}</span>
          {aiConsentError && <p role="alert">{aiConsentError}</p>}
          <button type="button" disabled={!aiConsentLoaded || aiConsentActionBusy} onClick={async () => {
            const nextGranted = !aiConsentGranted;
            setAiConsentActionBusy(true); setAiConsentError('');
            try {
              const response = await fetch('/api/ai-consent', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify({granted:nextGranted})});
              const data = await response.json();
              if (!response.ok) throw new Error(data.detail || data.error || 'Не удалось сохранить согласие');
              setAiConsentGranted(data.granted === true);
              setSmartConsent(false);
              setSmartResult(null);
              setToast(data.granted ? 'Согласие на внешний ИИ-анализ сохранено' : 'Согласие отозвано');
              window.setTimeout(() => setToast(''), 3500);
            } catch (e) { setAiConsentError(e instanceof Error ? e.message : 'Не удалось изменить согласие'); }
            finally { setAiConsentActionBusy(false); }
          }}>{aiConsentActionBusy ? 'Сохранение…' : aiConsentGranted ? 'Отозвать согласие' : 'Дать согласие на внешний ИИ-анализ'}</button>
          <p className="muted">Согласие сохраняется для учётной записи и действует для следующих вопросов, пока вы его не отзовёте. Настройку можно изменить здесь в любое время.</p>
        </div></article>
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
