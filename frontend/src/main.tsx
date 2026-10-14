import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ArrowLeft, ChevronRight, ClipboardCheck, FilePlus2, Home, Menu, Search,
  Settings, Users, X, HeartPulse, Cloud, ShieldCheck, PanelLeftClose
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
  const welcome = main.querySelector('.home-welcome');
  const search = main.querySelector('form.home-search');
  const upload = main.querySelector('#quick-upload');
  const actions = main.querySelector('.home-actions');
  if (welcome) main.insertBefore(welcome, main.firstChild);
  if (search && welcome) welcome.after(search);
  if (upload && search) search.after(upload);
  if (actions && upload) upload.after(actions);
  const archiveHeading = main.querySelector('#patients-section > h2');
  if (archiveHeading) archiveHeading.textContent = 'Семья';
  main.querySelector('#patients')?.remove();
  const addPatient = Array.from(main.querySelectorAll('a')).find(a => a.textContent?.includes('Добавить пациента'));
  if (addPatient) addPatient.textContent = '＋ Добавить члена семьи';
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
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  // Initial load only; popstate is managed by the listener.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const root = contentRef.current;
    if (!root || !screen) return;
    const zone = root.querySelector<HTMLElement>('#quick-upload');
    const input = root.querySelector<HTMLInputElement>('#upload-files');
    const familySelect = root.querySelector<HTMLSelectElement>('#upload-family');
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
      files.forEach(file => {
        const item = document.createElement('div');
        item.className = 'upload-item';
        item.textContent = file.name + ' · Загрузка…';
        queue?.appendChild(item);
        const data = new FormData();
        data.append('family_id', familySelect?.value || '');
        data.append('files', file, file.name);
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/upload');
        xhr.onload = () => { item.textContent = file.name + (xhr.status >= 200 && xhr.status < 300 ? ' · Передан серверу' : ' · Ошибка HTTP ' + xhr.status); };
        xhr.onerror = () => { item.textContent = file.name + ' · Ошибка сети'; };
        xhr.send(data);
      });
    };
    zone?.addEventListener('click', openPicker);
    choose?.addEventListener('click', chooseFiles);
    input?.addEventListener('change', changeFiles);
    const onClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement;
      const anchor = target.closest('a') as HTMLAnchorElement | null;
      if (!anchor || anchor.target === '_blank' || anchor.hasAttribute('download')) return;
      const href = anchor.getAttribute('href');
      if (!href || href.startsWith('#') || href.startsWith('mailto:') || href.startsWith('tel:')) return;
      const next = new URL(href, location.origin);
      if (next.origin !== location.origin) return;
      event.preventDefault();
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
        const params = new URLSearchParams(new FormData(form) as any);
        navigate(action.pathname + (params.size ? '?' + params.toString() : ''));
        return;
      }
      setLoading(true); setError('');
      try {
        const data = new FormData(form);
        const response = await fetch(action.pathname + action.search, { method, body: data, credentials: 'same-origin', redirect: 'follow' });
        const html = await response.text();
        if (!response.ok) throw new Error('Не удалось сохранить данные (' + response.status + ').');
        const finalUrl = new URL(response.url);
        const next: Screen = { url: finalUrl.pathname + finalUrl.search, html: extractContent(html), title: new DOMParser().parseFromString(html, 'text/html').title || 'Медицинский архив' };
        window.history.pushState({ medicalArchive: true }, '', next.url);
        setPath(next.url); setScreen(next); window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
      } catch (e) { setError(e instanceof Error ? e.message : 'Ошибка отправки формы'); }
      finally { setLoading(false); }
    };
    root.addEventListener('click', onClick);
    root.addEventListener('submit', onSubmit);
    return () => { zone?.removeEventListener('click', openPicker); choose?.removeEventListener('click', chooseFiles); input?.removeEventListener('change', changeFiles); root.removeEventListener('click', onClick); root.removeEventListener('submit', onSubmit); };
  }, [screen, navigate]);

  const isHome = path === '/' || path === '/app' || path.startsWith('/?');
  const back = () => {
    if (historyRef.current.length) { const previous = historyRef.current.pop()!; window.history.back(); navigate(previous, false); }
    else navigate(HOME);
  };

  return <div className="app-frame">
    {menuOpen && <button className="scrim" aria-label="Закрыть меню" onClick={() => setMenuOpen(false)} />}
    <aside className={'sidebar ' + (menuOpen ? 'sidebar-open' : '')}>
      <div className="brand"><span className="brand-icon"><HeartPulse size={22}/></span><span>Медицинский архив</span><button className="icon-button sidebar-close" onClick={() => setMenuOpen(false)} aria-label="Закрыть"><X size={20}/></button></div>
      <button className={'nav-item ' + (isHome ? 'active' : '')} onClick={() => navigate(HOME)}><Home size={19}/>Главная</button>
      <button className="nav-item" onClick={() => { const link = document.querySelector<HTMLAnchorElement>('.app-content a[href*="/inbox"]'); navigate(link?.getAttribute('href') || '/search'); }}><ClipboardCheck size={19}/>Требуют проверки</button>
      <button className="nav-item" onClick={() => navigate('/search')}><Search size={19}/>Поиск</button>
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
