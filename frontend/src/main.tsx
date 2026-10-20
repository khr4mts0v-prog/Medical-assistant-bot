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


type HomePatient = {name:string;short_name:string;document_count:number;url:string};
type HomeFamily = {id:number;name:string;selected:boolean};
type HomePayload = {families:HomeFamily[];selected_family_id:number|null;family_name:string;patients:HomePatient[];pending_count:number;storage_label:string;disk_connected:boolean;is_demo:boolean;upload_limit_mb:number};

function HomeReactView({familyId,onNavigate}: {familyId:number|null;onNavigate:(url:string)=>void}) {
  const [payload,setPayload] = useState<HomePayload|null>(null);
  const [busy,setBusy] = useState(true);
  const [error,setError] = useState('');
  const [consent,setConsent] = useState(false);
  const [uploadBusy,setUploadBusy] = useState(false);
  const [uploadStatus,setUploadStatus] = useState('');
  const [refreshKey,setRefreshKey] = useState(0);
  const [familyName,setFamilyName] = useState('');
  const [createFamilyOpen,setCreateFamilyOpen] = useState(false);
  const [createBusy,setCreateBusy] = useState(false);
  const [createError,setCreateError] = useState('');
  useEffect(() => {
    let active=true;
    setBusy(true); setError('');
    const query=familyId===null?'':'?family_id='+encodeURIComponent(String(familyId));
    fetch('/api/home'+query,{credentials:'same-origin',headers:{Accept:'application/json'}})
      .then(async response=>{const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.detail||'Не удалось загрузить семейный архив');return data as HomePayload;})
      .then(data=>{if(active)setPayload(data);})
      .catch(e=>{if(active)setError(e instanceof Error?e.message:'Ошибка загрузки архива');})
      .finally(()=>{if(active)setBusy(false);});
    return ()=>{active=false;};
  },[familyId,refreshKey]);
  const uploadFiles=async (files:FileList|null) => {
    if(!files?.length || !payload?.selected_family_id)return;
    const chosen=Array.from(files);
    setUploadBusy(true);setUploadStatus('Передаём файлы серверу…');
    try {
      const data=new FormData();
      data.append('family_id',String(payload.selected_family_id));
      data.append('ai_consent',consent?'true':'false');
      chosen.forEach(file=>data.append('files',file,file.name));
      const response=await fetch('/upload',{method:'POST',body:data,credentials:'same-origin'});
      const body=await response.text();
      if(!response.ok)throw new Error('Ошибка загрузки (HTTP '+response.status+'). '+body.replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim().slice(0,180));
      const lower=body.toLowerCase();
      setUploadStatus(lower.includes('добавлен во входящие')?'Файлы переданы; часть документов ожидает ручной проверки.':'Файлы переданы серверу. Проверь входящие и карточки пациентов.');
      window.setTimeout(()=>setRefreshKey(v=>v+1),1200);
    } catch(e) {setUploadStatus(e instanceof Error?e.message:'Не удалось загрузить файлы');}
    finally {setUploadBusy(false);}
  };
  const createFamily=async (event:React.FormEvent<HTMLFormElement>)=>{
    event.preventDefault();setCreateBusy(true);setCreateError('');
    try {
      const form=new FormData();form.set('name',familyName);
      const response=await fetch('/families',{method:'POST',body:form,credentials:'same-origin',redirect:'follow'});
      if(!response.ok)throw new Error('Не удалось создать архив (HTTP '+response.status+').');
      setCreateFamilyOpen(false);setFamilyName('');setRefreshKey(v=>v+1);
      if(response.url){const url=new URL(response.url);if(url.pathname==='/'&&url.search)onNavigate(url.pathname+url.search);}
    } catch(e){setCreateError(e instanceof Error?e.message:'Ошибка создания архива');}
    finally{setCreateBusy(false);}
  };
  return <div className="home-react-screen">
    <section className="home-react-hero"><div><div className="eyebrow">СЕМЕЙНЫЙ МЕДИЦИНСКИЙ АРХИВ</div><h1>Всё важное о здоровье — в одном месте</h1><p>Документы, обследования и история семьи с быстрым поиском и помощью ИИ.</p></div><div className="home-react-hero-icon"><HeartPulse size={34}/></div></section>
    {payload?.is_demo && <div className="notice-warning"><strong>Демо-режим.</strong> Используй только тестовые документы. Данные демо-архива автоматически удаляются после периода бездействия.</div>}
    {error && <div className="error-banner" role="alert">{error}<button type="button" onClick={()=>setRefreshKey(v=>v+1)}>Повторить</button></div>}
    {busy && <div className="skeleton"><div/><div/><div/></div>}
    {!busy && payload && <>
      <section className="home-react-section">
        <div className="home-react-section-heading"><div><div className="eyebrow">ПРОСТРАНСТВО ДАННЫХ</div><h2>Семейные архивы</h2></div><button type="button" className="button-link" onClick={()=>setCreateFamilyOpen(v=>!v)}><Plus size={16}/> Создать архив</button></div>
        <div className="home-react-family-list">{payload.families.map(family=><button type="button" key={family.id} className={'home-react-family '+(family.id===payload.selected_family_id?'selected':'')} onClick={()=>onNavigate('/?family_id='+family.id)}><span className="home-react-family-icon"><Users size={19}/></span><span className="home-react-family-copy"><strong>{family.name}</strong><small>{family.id===payload.selected_family_id?'Открыт сейчас':'Открыть архив'}</small></span>{family.id===payload.selected_family_id&&<span className="home-react-family-current">Выбран</span>}</button>)}
          {payload.families.length===0 && <div className="card"><p>Пока нет семейных архивов. Создай первый, чтобы начать.</p></div>}
        </div>
        {createFamilyOpen && <form className="card home-react-create-family" onSubmit={createFamily}><label htmlFor="home-family-name">Название нового архива</label><div className="row"><input id="home-family-name" value={familyName} onChange={e=>setFamilyName(e.target.value)} maxLength={80} required placeholder="Например, Семья"/><button type="submit" disabled={createBusy}>{createBusy?'Создаём…':'Создать'}</button></div>{createError&&<p className="error-text" role="alert">{createError}</p>}</form>}
      </section>
      {payload.selected_family_id!==null && <section className="home-react-section">
        <div className="home-react-section-heading"><div><div className="eyebrow">АРХИВ</div><h2>{payload.family_name}</h2><p className="muted">Хранение документов: {payload.storage_label}{payload.disk_connected?' · диск подключён':''}</p></div></div>
        <div className="home-react-stats"><button type="button" onClick={()=>onNavigate('/families/'+payload.selected_family_id+'/inbox')} className="home-react-stat"><ClipboardCheck size={19}/><span><strong>{payload.pending_count}</strong><small>Входящие на проверку</small></span></button><div className="home-react-stat"><Users size={19}/><span><strong>{payload.patients.length}</strong><small>Пациентов</small></span></div></div>
        {payload.pending_count>0&&<button type="button" className="home-react-inbox" onClick={()=>onNavigate('/families/'+payload.selected_family_id+'/inbox')}><ClipboardCheck size={18}/> Проверить входящие документы <ChevronRight size={17}/></button>}
        <div className="home-react-section-heading home-react-patients-heading"><div><h2>Члены семьи</h2><p className="muted">Выбери пациента, чтобы открыть документы и медицинскую историю.</p></div><button type="button" className="button-link" onClick={()=>onNavigate('/families/'+payload.selected_family_id+'/patients/new')}><Plus size={16}/> Добавить</button></div>
        <div className="home-react-patient-grid">{payload.patients.map(patient=><button type="button" className="home-react-patient" key={patient.name} onClick={()=>onNavigate(patient.url)}><span className="patient-avatar">{(patient.short_name||'П').slice(0,1).toUpperCase()}</span><span className="home-react-patient-copy"><strong>{patient.short_name}</strong><small>{patient.document_count} документов</small></span><ChevronRight size={17}/></button>)}
          {payload.patients.length===0&&<div className="card home-react-empty"><Users size={24}/><strong>Пока нет карточек пациентов</strong><p>Добавь члена семьи, чтобы хранить его документы отдельно.</p><button type="button" onClick={()=>onNavigate('/families/'+payload.selected_family_id+'/patients/new')}>Добавить первого пациента</button></div>}
        </div>
      </section>}
      <section className="home-react-section">
        <div className="home-react-section-heading"><div><div className="eyebrow">ЗАГРУЗКА</div><h2>Добавить документы</h2><p className="muted">PDF, фотографии и сканы · до {payload.upload_limit_mb} МБ на файл.</p></div></div>
        <div className="card home-react-upload"><label className="home-react-consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/> Разрешаю отправить OCR-текст внешнему ИИ для уточнения типа документа</label><label className={'home-react-file-picker '+(uploadBusy?'disabled':'')}><FilePlus2 size={21}/><span>{uploadBusy?'Обработка загрузки…':'Выбрать документы'}</span><input type="file" accept="image/*,application/pdf,.tif,.tiff,.bmp" multiple disabled={uploadBusy||payload.families.length===0} onChange={e=>{void uploadFiles(e.target.files);e.currentTarget.value='';}}/></label>{uploadStatus&&<p className="home-react-upload-status" role="status">{uploadStatus}</p>}</div>
      </section>
      <p className="home-react-safety"><ShieldCheck size={16}/> Перед загрузкой реальных медицинских документов проверь резервное копирование и права доступа.</p>
    </>}
  </div>;
}

type InboxDocument = {id:number;name:string;created:string};
type InboxPayload = {family_id:number;patients:{name:string}[];documents:InboxDocument[]};

function InboxReactView({familyId,onNavigate}: {familyId:number;onNavigate:(url:string)=>void}) {
  const [payload,setPayload] = useState<InboxPayload|null>(null);
  const [selected,setSelected] = useState<number[]>([]);
  const [patient,setPatient] = useState('');
  const [busy,setBusy] = useState(true);
  const [submitting,setSubmitting] = useState(false);
  const [error,setError] = useState('');
  const [status,setStatus] = useState('');
  const [refresh,setRefresh] = useState(0);
  useEffect(()=>{
    let active=true;setBusy(true);setError('');
    fetch('/api/families/'+familyId+'/inbox',{credentials:'same-origin',headers:{Accept:'application/json'},cache:'no-store'})
      .then(async response=>{const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.detail||'Не удалось загрузить входящие документы');return data as InboxPayload;})
      .then(data=>{if(active){setPayload(data);setSelected([]);setPatient(current=>data.patients.some(p=>p.name===current)?current:(data.patients[0]?.name||''));}})
      .catch(e=>{if(active)setError(e instanceof Error?e.message:'Ошибка загрузки');})
      .finally(()=>{if(active)setBusy(false);});
    return ()=>{active=false;};
  },[familyId,refresh]);
  const assignSelected=async(event:React.FormEvent<HTMLFormElement>)=>{
    event.preventDefault();
    if(!selected.length||!patient||submitting)return;
    setSubmitting(true);setError('');setStatus('');
    try{
      const form=new FormData();form.set('patient',patient);selected.forEach(id=>form.append('pending_ids',String(id)));
      const response=await fetch('/families/'+familyId+'/inbox/assign-selected',{method:'POST',body:form,credentials:'same-origin'});
      const body=await response.text();
      if(!response.ok)throw new Error('Не удалось назначить документы (HTTP '+response.status+').');
      const parsed=new DOMParser().parseFromString(body,'text/html');
      const items=Array.from(parsed.querySelectorAll('li')).map(node=>(node.textContent||'').trim()).filter(Boolean);
      setStatus(items.length?items.join(' '):'Обработка завершена. Список входящих обновлён.');
      setSelected([]);setRefresh(value=>value+1);
    }catch(e){setError(e instanceof Error?e.message:'Ошибка назначения документов');}
    finally{setSubmitting(false);}
  };
  return <div className="inbox-react-screen">
    <div className="inbox-react-header"><div><div className="eyebrow">СЕМЕЙНЫЙ АРХИВ</div><h1>Входящие документы</h1><p className="lead">Назначь документ пациенту после проверки или выбери несколько файлов одного человека.</p></div><button type="button" className="button-link" onClick={()=>onNavigate('/?family_id='+familyId)}><Home size={16}/> К архиву</button></div>
    {error&&<div className="error-banner" role="alert">{error}<button type="button" onClick={()=>setRefresh(v=>v+1)}>Повторить</button></div>}
    {status&&<div className="notice-success" role="status">{status}</div>}
    {busy&&<div className="skeleton"><div/><div/><div/></div>}
    {!busy&&payload&&payload.documents.length===0&&<div className="card inbox-react-empty"><ClipboardCheck size={26}/><h2>Входящих документов нет</h2><p className="muted">Новые загруженные документы появятся здесь, если системе потребуется ручная проверка.</p><button type="button" onClick={()=>onNavigate('/?family_id='+familyId)}>Вернуться в архив</button></div>}
    {!busy&&payload&&payload.documents.length>0&&<form className="inbox-react-bulk" onSubmit={assignSelected}>
      <section className="card inbox-react-bulk-tools"><div><strong>Массовое назначение</strong><p className="muted">Выбирай только документы, которые относятся к одному пациенту.</p></div><label>Пациент<select value={patient} onChange={event=>setPatient(event.target.value)} required><option value="" disabled>Выбери пациента</option>{payload.patients.map(p=><option key={p.name} value={p.name}>{p.name}</option>)}</select></label><button type="submit" disabled={!selected.length||!patient||submitting}>{submitting?'Обрабатываем…':'Назначить выбранные ('+selected.length+')'}</button></section>
      <div className="inbox-react-list"><div className="inbox-react-select-all"><label><input type="checkbox" checked={payload.documents.length>0&&selected.length===payload.documents.length} onChange={event=>setSelected(event.target.checked?payload.documents.map(d=>d.id):[])}/> Выбрать все</label><span>{payload.documents.length} документов</span></div>
        {payload.documents.map(doc=><article className="inbox-react-document" key={doc.id}><label className="inbox-react-document-check"><input type="checkbox" checked={selected.includes(doc.id)} onChange={event=>setSelected(current=>event.target.checked?[...current,doc.id]:current.filter(id=>id!==doc.id))}/></label><div className="inbox-react-document-copy"><strong>{doc.name}</strong><small>Добавлен: {doc.created||'дата не указана'}</small></div><button type="button" className="button-link" onClick={()=>onNavigate('/families/'+familyId+'/inbox/'+doc.id)}>Открыть и классифицировать</button></article>)}
      </div>
    </form>}
  </div>;
}


type DocumentEditorPayload = {family_id:number;document_id:number;patient:string;source_name:string;kind:string;title:string;date:string;ocr_text:string;kinds:string[];preview_url:string|null};
function DocumentEditorReactView({familyId,documentId,onNavigate}: {familyId:number;documentId:number;onNavigate:(url:string)=>void}) {
  const [data,setData]=useState<DocumentEditorPayload|null>(null);
  const [kind,setKind]=useState('');
  const [title,setTitle]=useState('');
  const [date,setDate]=useState('');
  const [ocrText,setOcrText]=useState('');
  const [busy,setBusy]=useState(true);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{
    let active=true;
    setBusy(true);setError('');
    fetch('/api/families/'+familyId+'/documents/'+documentId+'/edit',{credentials:'same-origin',headers:{Accept:'application/json'}})
      .then(async response=>{const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.detail||'Не удалось загрузить документ');return body as DocumentEditorPayload;})
      .then(body=>{if(active){setData(body);setKind(body.kind);setTitle(body.title);setDate(body.date);setOcrText(body.ocr_text);}})
      .catch(e=>{if(active)setError(e instanceof Error?e.message:'Ошибка загрузки документа');})
      .finally(()=>{if(active)setBusy(false);});
    return ()=>{active=false;};
  },[familyId,documentId]);
  const save=async(event:React.FormEvent<HTMLFormElement>)=>{
    event.preventDefault();
    if(!data)return;
    setSaving(true);setError('');
    try{
      const form=new FormData();
      form.set('kind',kind);form.set('title',title);form.set('date',date);form.set('ocr_text',ocrText);
      const response=await fetch('/families/'+familyId+'/documents/'+documentId+'/edit',{method:'POST',body:form,credentials:'same-origin',redirect:'follow'});
      if(!response.ok)throw new Error('Сохранение не подтверждено сервером (HTTP '+response.status+'). Проверь дату и повтори попытку.');
      const finalUrl=new URL(response.url,location.origin);
      if(finalUrl.pathname.indexOf('/families/'+familyId+'/patients/')!==0)throw new Error('Сервер не подтвердил сохранение. Данные не считаются сохранёнными.');
      onNavigate(finalUrl.pathname+finalUrl.search);
    }catch(e){setError(e instanceof Error?e.message:'Не удалось сохранить изменения');}
    finally{setSaving(false);}
  };
  return <div className="document-editor-react">
    <button type="button" className="inbox-back-link" onClick={()=>onNavigate(data?'/families/'+familyId+'/patients/'+encodeURIComponent(data.patient):'/?family_id='+familyId)}>← Назад к документам</button>
    <div className="document-editor-heading"><div className="eyebrow">МЕДИЦИНСКИЙ АРХИВ</div><h1>Редактирование документа</h1><p>Исправления метаданных и OCR влияют на поиск и последующий анализ. Исходный файл не изменяется.</p></div>
    {error&&<div className="error-banner" role="alert">{error}<button type="button" onClick={()=>onNavigate(location.pathname+location.search)}>Повторить загрузку</button></div>}
    {busy&&<div className="skeleton"><div/><div/><div/></div>}
    {!busy&&data&&<form className="document-editor-form" onSubmit={save}>
      <section className="card document-editor-source"><div><span className="muted">Пациент</span><strong>{data.patient}</strong></div><div><span className="muted">Исходный файл</span><strong>{data.source_name}</strong></div></section>
      {data.preview_url&&<section className="card document-editor-preview"><h2>Предпросмотр оригинала</h2>{data.preview_url.endsWith('/original')?<iframe src={data.preview_url+'#toolbar=1&navpanes=0&scrollbar=1'} title="Оригинал PDF" loading="lazy"/>:<a href={data.preview_url} target="_blank" rel="noopener noreferrer"><img src={data.preview_url} alt="Предпросмотр оригинала"/></a>}</section>}
      <section className="card document-editor-fields">
        <label>Тип документа<select value={kind} onChange={e=>setKind(e.target.value)} required>{data.kinds.map(value=><option key={value} value={value}>{value}</option>)}</select></label>
        <label>Название в архиве<input value={title} onChange={e=>setTitle(e.target.value)} maxLength={180} required/></label>
        <label>Дата документа (ДД-ММ-ГГГГ)<input value={date} onChange={e=>setDate(e.target.value)} maxLength={10} placeholder="17-03-2025" inputMode="numeric"/></label>
        <label>Распознанный текст (OCR)<textarea value={ocrText} onChange={e=>setOcrText(e.target.value)} maxLength={100000} rows={14}/></label>
        <p className="muted">OCR-текст доступен только в авторизованной карточке документа. Сохранение выполняется существующим backend-обработчиком.</p>
        <div className="document-editor-actions"><button type="submit" disabled={saving}>{saving?'Сохраняем…':'Сохранить изменения'}</button><button type="button" className="secondary" onClick={()=>onNavigate(data?'/families/'+familyId+'/patients/'+encodeURIComponent(data.patient):'/')}>Отмена</button></div>
      </section>
    </form>}
  </div>;
}

type PatientDocument = { id:number; title:string; kind:string; date:string; metadata:string; finding:string; review_required:boolean; url:string };
type PatientPayload = { patient:string; family_id:number; query:string; view:string; document_count:number; documents:PatientDocument[]; capabilities:{upload:boolean;patient_memory:boolean;document_selection:boolean;assistant:boolean} };

function PatientReactView({familyId, patient, onAsk}: {familyId:number; patient:string; onAsk:(selectedIds?:number[])=>void}) {
  const [query,setQuery] = useState('');
  const [view,setView] = useState<'timeline'|'tree'>('timeline');
  const [payload,setPayload] = useState<PatientPayload|null>(null);
  const [busy,setBusy] = useState(true);
  const [error,setError] = useState('');
  const [selectionMode,setSelectionMode] = useState(false);
  const [selected,setSelected] = useState<number[]>([]);
  useEffect(() => {
    let active = true;
    setBusy(true); setError('');
    const params = new URLSearchParams({q:query,view});
    fetch('/api/families/'+familyId+'/patients/'+encodeURIComponent(patient)+'?'+params.toString(), {credentials:'same-origin',headers:{Accept:'application/json'}})
      .then(async response => { const data = await response.json().catch(()=>({})); if (!response.ok) throw new Error(data.detail || 'Не удалось загрузить документы пациента'); return data as PatientPayload; })
      .then(data => { if(active) setPayload(data); })
      .catch(e => { if(active) setError(e instanceof Error ? e.message : 'Ошибка загрузки'); })
      .finally(() => { if(active) setBusy(false); });
    return () => { active = false; };
  },[familyId,patient,query,view]);
  useEffect(()=>{setSelected([]);setSelectionMode(false);},[familyId,patient]);
  const base='/families/'+familyId+'/patients/'+encodeURIComponent(patient);
  const grouped = payload?.documents.reduce<Record<string,PatientDocument[]>>((acc,doc)=>{(acc[doc.kind || 'Не определено'] ||= []).push(doc);return acc;},{}) || {};
  return <div className="patient-react-screen">
    <div className="patient-react-header"><div><div className="eyebrow">КАРТОЧКА ПАЦИЕНТА</div><h1>{patient}</h1><p className="lead">{payload ? payload.document_count+' документов в архиве' : 'Документы и медицинская история'}</p></div>
      <div className="patient-react-actions"><button type="button" className="patient-action-primary" onClick={() => onAsk()}><BrainCircuit size={17}/> Спросить ИИ</button><a className="button-link" href={'/patient-memory?family_id='+familyId+'&patient='+encodeURIComponent(patient)}>Память пациента</a><a className="button-link" href={base+'/edit'}>Редактировать</a></div>
    </div>
    <form className="card patient-react-search" onSubmit={event=>event.preventDefault()}><label htmlFor="patient-react-q">Поиск по документам пациента</label><div className="row"><input id="patient-react-q" type="search" value={query} onChange={event=>setQuery(event.target.value)} placeholder="Например: анализы, УЗИ, выписка"/>{query && <button type="button" onClick={()=>setQuery('')}>Сбросить</button>}</div></form>
    {payload?.capabilities.upload && <section className="card patient-react-upload"><h2>Добавить документы</h2><form method="post" encType="multipart/form-data" action={base+'/upload'}><input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp" required/><label><input type="checkbox" name="ai_consent" value="true"/> Разрешаю отправить OCR-текст внешнему ИИ для уточнения типа документа</label><button type="submit">Загрузить и распознать</button></form></section>}
    <div className="patient-react-tabs" role="tablist" aria-label="Вид документов"><button type="button" role="tab" aria-selected={view==='timeline'} className={view==='timeline'?'active':''} onClick={()=>setView('timeline')}>Хронология</button><button type="button" role="tab" aria-selected={view==='tree'} className={view==='tree'?'active':''} onClick={()=>setView('tree')}>Дерево документов</button></div>
    {view==='tree' && <div className="patient-react-selection"><div><strong>Выбор документов для ИИ</strong><p>По умолчанию ассистент сам ищет подходящие документы. Включи выбор, чтобы ограничить запрос отмеченными файлами.</p></div><button type="button" onClick={()=>{setSelectionMode(v=>!v);setSelected([]);}}>{selectionMode?'Отменить выбор':'Выбрать документы'}</button>{selectionMode && <span>{selected.length} выбрано</span>}</div>}
    {busy && <div className="skeleton"><div/><div/><div/></div>}
    {error && <div className="error-banner" role="alert">{error}<button type="button" onClick={()=>window.location.reload()}>Повторить</button></div>}
    {!busy && !error && payload?.documents.length===0 && <div className="card"><p>Документы не найдены.</p><p className="muted">Попробуй изменить запрос или загрузить документ.</p></div>}
    {!busy && !error && view==='timeline' && payload && <div className="patient-react-documents">{payload.documents.map(doc=><article className="document-row document-card" key={doc.id}><div className="document-main"><strong>{doc.title}</strong><div className="muted document-meta">{doc.kind} · {doc.date || 'Дата не указана'}</div>{doc.metadata && <div className="document-meta">{doc.metadata}</div>}<p className="document-finding">{doc.finding || 'Открой документ, чтобы посмотреть заключение.'}</p>{doc.review_required && <span className="status-pill">Требуется проверка</span>}</div><a className="button-link" href={doc.url}>Открыть</a></article>)}</div>}
    {!busy && !error && view==='tree' && payload && <div className="patient-react-tree">{Object.entries(grouped).sort(([a],[b])=>a.localeCompare(b,'ru')).map(([kind,docs])=><details className="tree-group" open key={kind}><summary>{kind} <span className="muted">({docs.length})</span></summary>{docs.map(doc=><div className="document-row" key={doc.id}>{selectionMode && <label className="document-select-label"><input type="checkbox" checked={selected.includes(doc.id)} onChange={event=>setSelected(current=>event.target.checked?[...current,doc.id]:current.filter(id=>id!==doc.id))}/></label>}<div className="document-main"><strong>{doc.title}</strong><span className="muted">{doc.date || 'Дата не указана'}</span></div><a className="button-link" href={doc.url}>Открыть</a></div>)}</details>)}</div>}
    {view==='tree' && selectionMode && selected.length>0 && <div className="patient-react-selection"><span>Отмечено документов: {selected.length}</span><button type="button" onClick={()=>{onAsk(selected);}}>Спросить ИИ по выбранным</button></div>}
  </div>;
}


type PatientEditorPayload = {family_id:number;patient:string;name:string;birth_date:string;aliases:string[]};
function PatientEditorReactView({familyId,patient,onNavigate}: {familyId:number;patient:string|null;onNavigate:(url:string)=>void}) {
  const editing=patient!==null;
  const [name,setName]=useState('');
  const [birthDate,setBirthDate]=useState('');
  const [aliases,setAliases]=useState('');
  const [busy,setBusy]=useState(editing);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{
    let active=true;
    if(!patient){setBusy(false);setName('');setBirthDate('');setAliases('');setError('');return ()=>{active=false;};}
    setBusy(true);setError('');
    fetch('/api/families/'+familyId+'/patients/'+encodeURIComponent(patient)+'/edit',{credentials:'same-origin',headers:{Accept:'application/json'}})
      .then(async response=>{const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.detail||'Не удалось загрузить карточку пациента');return body as PatientEditorPayload;})
      .then(body=>{if(active){setName(body.name);setBirthDate(body.birth_date);setAliases(body.aliases.join(', '));}})
      .catch(e=>{if(active)setError(e instanceof Error?e.message:'Ошибка загрузки карточки');})
      .finally(()=>{if(active)setBusy(false);});
    return ()=>{active=false;};
  },[familyId,patient]);
  const save=async(event:React.FormEvent<HTMLFormElement>)=>{
    event.preventDefault();setSaving(true);setError('');
    try{
      const form=new FormData();form.set('name',name);form.set('birth_date',birthDate);form.set('aliases',aliases);
      const url=editing
        ? '/families/'+familyId+'/patients/'+encodeURIComponent(patient as string)+'/edit'
        : '/families/'+familyId+'/patients';
      const response=await fetch(url,{method:'POST',body:form,credentials:'same-origin',redirect:'follow'});
      if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail||'Не удалось сохранить карточку (HTTP '+response.status+').');}
      const target=new URL(response.url,window.location.origin);
      if(editing && target.pathname.includes('/patients/') && target.pathname.endsWith('/edit')){
        onNavigate('/families/'+familyId+'/patients/'+encodeURIComponent(name.trim().replace(/\s+/g,' ')));
      }else{
        onNavigate(target.pathname+target.search);
      }
    }catch(e){setError(e instanceof Error?e.message:'Ошибка сохранения карточки');}
    finally{setSaving(false);}
  };
  return <div className="patient-editor-screen">
    <div className="patient-editor-header"><div><div className="eyebrow">СЕМЕЙНЫЙ МЕДИЦИНСКИЙ АРХИВ</div><h1>{editing?'Данные члена семьи':'Новый пациент'}</h1><p className="muted">{editing?'Изменения имени сохранятся и в связях документов.':'Создай карточку, чтобы хранить медицинские документы отдельно.'}</p></div><button type="button" className="button-link" onClick={()=>onNavigate(editing?'/families/'+familyId+'/patients/'+encodeURIComponent(patient as string):'/?family_id='+familyId)}>← {editing?'К карточке':'В архив'}</button></div>
    {error&&<div className="error-banner" role="alert">{error}</div>}
    {busy?<div className="skeleton"><div/><div/><div/></div>:<form className="card patient-editor-form" onSubmit={save}>
      <label htmlFor="patient-editor-name">Полное имя и фамилия</label>
      <input id="patient-editor-name" name="name" value={name} onChange={e=>setName(e.target.value)} required maxLength={100} placeholder="Иванов Александр Сергеевич"/>
      <label htmlFor="patient-editor-birth-date">Дата рождения</label>
      <input id="patient-editor-birth-date" name="birth_date" type="date" value={birthDate} onChange={e=>setBirthDate(e.target.value)}/>
      <label htmlFor="patient-editor-aliases">Другие варианты имени</label>
      <input id="patient-editor-aliases" name="aliases" value={aliases} onChange={e=>setAliases(e.target.value)} maxLength={500} placeholder="Саша, Александр"/>
      <p className="muted">Дата рождения помогает сверять документы, но не является единственным подтверждением личности.</p>
      <div className="patient-editor-form-actions"><button type="submit" disabled={saving||busy}>{saving?'Сохраняем…':editing?'Сохранить изменения':'Создать карточку'}</button><button type="button" className="button-link" disabled={saving} onClick={()=>onNavigate(editing?'/families/'+familyId+'/patients/'+encodeURIComponent(patient as string):'/?family_id='+familyId)}>Отмена</button></div>
    </form>}
  </div>;
}


type SettingsPayload = {family_id:number|null;name:string;role:string|null;can_rename:boolean;is_demo:boolean;storage_label:string;disk_connected:boolean;can_connect_disk:boolean;updated:boolean};
function SettingsReactView({familyId,onNavigate}: {familyId:number|null;onNavigate:(url:string)=>void}) {
  const [data,setData]=useState<SettingsPayload|null>(null);
  const [name,setName]=useState('');
  const [busy,setBusy]=useState(true);
  const [saving,setSaving]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{
    let active=true;setBusy(true);setError('');
    const query=familyId===null?'':'?family_id='+encodeURIComponent(String(familyId));
    fetch('/api/settings'+query,{credentials:'same-origin',headers:{Accept:'application/json'}})
      .then(async response=>{const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.detail||'Не удалось загрузить настройки архива');return body as SettingsPayload;})
      .then(body=>{if(active){setData(body);setName(body.name);}})
      .catch(e=>{if(active)setError(e instanceof Error?e.message:'Ошибка загрузки настроек');})
      .finally(()=>{if(active)setBusy(false);});
    return ()=>{active=false;};
  },[familyId]);
  const save=async(event:React.FormEvent<HTMLFormElement>)=>{
    event.preventDefault();if(!data?.family_id||!data.can_rename)return;
    setSaving(true);setError('');
    try{
      const form=new FormData();form.set('family_id',String(data.family_id));form.set('name',name);
      const response=await fetch('/settings',{method:'POST',body:form,credentials:'same-origin',redirect:'follow'});
      if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail||'Не удалось сохранить настройки (HTTP '+response.status+').');}
      const target=new URL(response.url,window.location.origin);
      onNavigate(target.pathname+target.search);
    }catch(e){setError(e instanceof Error?e.message:'Ошибка сохранения настроек');}
    finally{setSaving(false);}
  };
  return <div className="settings-react-screen">
    <header className="settings-react-header"><div><div className="eyebrow">УПРАВЛЕНИЕ АРХИВОМ</div><h1>Настройки архива</h1><p className="muted">Параметры семейного медицинского архива и хранения документов.</p></div><button type="button" className="button-link" onClick={()=>onNavigate(data?.family_id? '/?family_id='+data.family_id:'/')}>← На главную</button></header>
    {error&&<div className="error-banner" role="alert">{error}</div>}
    {busy?<div className="skeleton"><div/><div/><div/></div>:data&&!data.family_id?<section className="card"><h2>Семейный архив не создан</h2><p>Сначала создай архив, чтобы настраивать его параметры.</p><button type="button" onClick={()=>onNavigate('/')}>Перейти на главную</button></section>:data&&<>
      {data.is_demo&&<div className="notice-warning"><strong>Демо-режим.</strong> Временный архив хранится локально и автоматически очищается примерно через 2 часа. Используй только тестовые документы.</div>}
      {data.updated&&<div className="notice-success" role="status">Название архива сохранено.</div>}
      <form className="card settings-react-card" onSubmit={save}>
        <div className="settings-react-card-icon"><Users size={20}/></div><div className="settings-react-card-body"><h2>Название архива</h2><p className="muted">Название, которое отображается в семейной навигации.</p><label htmlFor="settings-family-name">Название архива</label><input id="settings-family-name" name="name" value={name} onChange={e=>setName(e.target.value)} maxLength={80} required disabled={!data.can_rename}/>{data.can_rename?<button type="submit" disabled={saving}>{saving?'Сохраняем…':'Сохранить название'}</button>:<p className="muted">Переименовывать архив может только владелец.</p>}</div>
      </form>
      <section className="card settings-react-card"><div className="settings-react-card-icon"><Cloud size={20}/></div><div className="settings-react-card-body"><h2>Хранение документов</h2><p>Текущий режим: <strong>{data.storage_label}</strong></p>
        {data.is_demo?<p className="muted">Подключение внешнего хранилища отключено для демо-аккаунта.</p>:data.storage_label==='Яндекс Диск'?<><p>{data.disk_connected?'Яндекс Диск подключён.':'Яндекс Диск ещё не подключён.'}</p>{data.can_connect_disk&&<button type="button" onClick={()=>onNavigate('/families/'+data.family_id+'/connect-disk')}>Подключить Яндекс Диск</button>}</>:<p className="muted">Подключение Яндекс Диска добавим отдельным этапом; сейчас используется локальное хранилище.</p>}
      </div></section>
      <section className="card settings-react-card"><div className="settings-react-card-icon"><ShieldCheck size={20}/></div><div className="settings-react-card-body"><h2>Резервное копирование</h2><p>Перед загрузкой реальных медицинских документов проверь наличие внешней резервной копии и возможность восстановления.</p></div></section>
    </>}
  </div>;
}


type InboxReviewPayload = {family_id:number;pending_id:number;source_name:string;created:string;ocr_text:string;patient_options:{name:string;birth_date:string}[];kinds:{value:string;label:string}[];kind:string;title:string;date:string;preview_url:string|null;preview_kind:'image'|'pdf'|'none';page_count:number};
function InboxReviewReactView({familyId,pendingId,onNavigate}: {familyId:number;pendingId:number;onNavigate:(url:string)=>void}) {
  const [data,setData]=useState<InboxReviewPayload|null>(null);
  const [patient,setPatient]=useState('');
  const [kind,setKind]=useState('не определено');
  const [title,setTitle]=useState('');
  const [date,setDate]=useState('');
  const [busy,setBusy]=useState(true);
  const [saving,setSaving]=useState(false);
  const [deleting,setDeleting]=useState(false);
  const [showOcr,setShowOcr]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{
    let active=true;setBusy(true);setError('');
    fetch('/api/families/'+familyId+'/inbox/'+pendingId,{credentials:'same-origin',headers:{Accept:'application/json'},cache:'no-store'})
      .then(async response=>{const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.detail||'Не удалось загрузить документ');return body as InboxReviewPayload;})
      .then(body=>{if(active){setData(body);setPatient(body.patient_options[0]?.name||'');setKind(body.kind);setTitle(body.title);setDate(body.date||'');}})
      .catch(e=>{if(active)setError(e instanceof Error?e.message:'Ошибка загрузки документа');})
      .finally(()=>{if(active)setBusy(false);});
    return ()=>{active=false;};
  },[familyId,pendingId]);
  const assign=async(event:React.FormEvent<HTMLFormElement>)=>{
    event.preventDefault();if(!patient||saving)return;
    setSaving(true);setError('');
    try{
      const form=new FormData();form.set('patient',patient);form.set('kind',kind);form.set('title',title);form.set('date',date);
      const response=await fetch('/families/'+familyId+'/inbox/'+pendingId+'/assign',{method:'POST',body:form,credentials:'same-origin',redirect:'follow'});
      if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail||'Не удалось сохранить документ (HTTP '+response.status+').');}
      const target=new URL(response.url,window.location.origin);onNavigate(target.pathname+target.search);
    }catch(e){setError(e instanceof Error?e.message:'Ошибка сохранения документа');}
    finally{setSaving(false);}
  };
  const remove=async()=>{
    if(deleting||!window.confirm('Удалить этот документ из входящих без возможности восстановления?'))return;
    setDeleting(true);setError('');
    try{
      const form=new FormData();form.set('confirm','yes');
      const response=await fetch('/families/'+familyId+'/inbox/'+pendingId+'/delete',{method:'POST',body:form,credentials:'same-origin',redirect:'follow'});
      if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.detail||'Не удалось удалить документ (HTTP '+response.status+').');}
      const target=new URL(response.url,window.location.origin);onNavigate(target.pathname+target.search);
    }catch(e){setError(e instanceof Error?e.message:'Ошибка удаления документа');}
    finally{setDeleting(false);}
  };
  return <div className="inbox-review-react-screen">
    <header className="inbox-review-react-header"><div><div className="eyebrow">РУЧНАЯ ПРОВЕРКА</div><h1>Классификация документа</h1><p className="muted">Проверь распознанные данные и назначь документ нужному пациенту.</p></div><button type="button" className="button-link" onClick={()=>onNavigate('/families/'+familyId+'/inbox')}><Home size={16}/> К входящим</button></header>
    {error&&<div className="error-banner" role="alert">{error}</div>}
    {busy&&<div className="skeleton"><div/><div/><div/></div>}
    {!busy&&data&&<>
      <section className="card inbox-review-source"><div><div className="eyebrow">ИСХОДНЫЙ ФАЙЛ</div><h2>{data.source_name}</h2><p className="muted">Добавлен: {data.created||'дата не указана'}</p></div>
        {data.preview_kind==='image'&&data.preview_url&&<a href={data.preview_url} target="_blank" rel="noopener" className="inbox-review-image-link"><img src={data.preview_url} alt="Предпросмотр исходного документа"/><span>Открыть полностью ↗</span></a>}
        {data.preview_kind==='pdf'&&data.preview_url&&<div className="inbox-review-pdf">{data.page_count>0?Array.from({length:Math.min(data.page_count,100)},(_,i)=><figure key={i}><figcaption>Страница {i+1}{data.page_count>100?' (показаны первые 100 страниц)':' из '+data.page_count}</figcaption><img src={data.preview_url+'/page/'+(i+1)} alt={'Страница '+(i+1)} loading="lazy" decoding="async"/></figure>):<iframe src={data.preview_url+'#toolbar=1&navpanes=0'} title="Предпросмотр PDF" loading="lazy"/>}<p><a href={data.preview_url} target="_blank" rel="noopener">Открыть PDF отдельно ↗</a></p></div>}
        {data.preview_kind==='none'&&<p className="muted">Предпросмотр для этого формата недоступен.</p>}
        <button type="button" className="button-link inbox-review-ocr-toggle" onClick={()=>setShowOcr(v=>!v)}>{showOcr?'Скрыть OCR-текст':'Показать OCR-текст'}</button>
        {showOcr&&<pre className="inbox-review-ocr">{data.ocr_text||'Текст не распознан.'}</pre>}
      </section>
      <form className="card inbox-review-form" onSubmit={assign}>
        <h2>Данные для архива</h2>
        <label htmlFor="inbox-review-patient">Пациент</label><select id="inbox-review-patient" value={patient} onChange={e=>setPatient(e.target.value)} required><option value="" disabled>Выбери пациента</option>{data.patient_options.map(p=><option key={p.name} value={p.name}>{p.name}{p.birth_date?' · рожд. '+p.birth_date:''}</option>)}</select>
        {data.patient_options.length===0&&<p className="muted">Сначала создай карточку пациента.</p>}
        <button type="button" className="button-link inbox-review-add-patient" onClick={()=>onNavigate('/families/'+familyId+'/patients/new')}>＋ Добавить пациента</button>
        <label htmlFor="inbox-review-kind">Тип документа</label><select id="inbox-review-kind" value={kind} onChange={e=>setKind(e.target.value)} required>{data.kinds.map(k=><option key={k.value} value={k.value}>{k.label}</option>)}</select>
        <label htmlFor="inbox-review-title">Название в архиве</label><input id="inbox-review-title" value={title} onChange={e=>setTitle(e.target.value)} required maxLength={180}/>
        <label htmlFor="inbox-review-date">Дата документа (ДД-ММ-ГГГГ)</label><input id="inbox-review-date" value={date} onChange={e=>setDate(e.target.value)} maxLength={10} placeholder="17-03-2025"/>
        <div className="inbox-review-actions"><button type="submit" disabled={saving||!patient}>{saving?'Сохраняем…':'Сохранить в историю пациента'}</button><button type="button" className="inbox-review-delete" onClick={()=>void remove()} disabled={deleting}>{deleting?'Удаляем…':'Удалить документ'}</button></div>
      </form>
    </>}
  </div>;
}


type SearchResult = {id:number;title:string;kind:string;date:string;text:string;url:string;patient_url:string};
type SearchPayload = {family_id:number|null;family_name:string;query:string;patient:string;patients:{name:string;aliases:string[]}[];needs_patient:boolean;ambiguous:boolean;patient_choices:string[];results:SearchResult[];searched:boolean;message:string;total:number};
function SearchReactView({familyId,onNavigate}: {familyId:number|null;onNavigate:(url:string)=>void}) {
  const params=new URLSearchParams(location.search);
  const [selectedFamily,setSelectedFamily]=useState(familyId ?? (Number(params.get('family_id')) || null));
  const [query,setQuery]=useState(params.get('q')||'');
  const [patient,setPatient]=useState(params.get('patient')||'');
  const [payload,setPayload]=useState<SearchPayload|null>(null);
  const [busy,setBusy]=useState(true);
  const [searching,setSearching]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{
    let active=true;setBusy(true);setError('');
    const qs=new URLSearchParams();if(selectedFamily)qs.set('family_id',String(selectedFamily));if(query.trim())qs.set('q',query.trim());if(patient)qs.set('patient',patient);
    fetch('/api/search?'+qs.toString(),{credentials:'same-origin',headers:{Accept:'application/json'},cache:'no-store'})
      .then(async response=>{const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(body.detail||'Не удалось выполнить поиск');return body as SearchPayload;})
      .then(body=>{if(active){setPayload(body);if(!selectedFamily&&body.family_id)setSelectedFamily(body.family_id);}})
      .catch(e=>{if(active)setError(e instanceof Error?e.message:'Ошибка поиска');})
      .finally(()=>{if(active)setBusy(false);});
    return ()=>{active=false;};
  },[selectedFamily,query,patient]);
  const submit=(event:React.FormEvent<HTMLFormElement>)=>{event.preventDefault();setSearching(true);setError('');const qs=new URLSearchParams();if(selectedFamily)qs.set('family_id',String(selectedFamily));if(query.trim())qs.set('q',query.trim());if(patient)qs.set('patient',patient);onNavigate('/search?'+qs.toString());setSearching(false);};
  const choosePatient=(name:string)=>{setPatient(name);const qs=new URLSearchParams();if(selectedFamily)qs.set('family_id',String(selectedFamily));qs.set('patient',name);qs.set('q',query);onNavigate('/search?'+qs.toString());};
  return <div className="archive-search-screen">
    <header className="archive-search-header"><div><div className="eyebrow">ПОИСК ПО МЕДИЦИНСКОМУ АРХИВУ</div><h1>Поиск документов</h1><p className="muted">Ищи по содержимому, названию, типу исследования или дате. Результаты ограничены выбранным семейным архивом.</p></div><button type="button" className="button-link" onClick={()=>onNavigate(selectedFamily? '/?family_id='+selectedFamily:'/')}><Home size={16}/> В архив</button></header>
    <form className="card archive-search-form" onSubmit={submit}>
      <label htmlFor="archive-search-query">Что ищем?</label><div className="archive-search-input-row"><input id="archive-search-query" type="search" value={query} onChange={e=>setQuery(e.target.value)} maxLength={300} placeholder="Например: Саша анализы за март" required/><button type="submit" disabled={searching}>{searching?'Ищем…':'Найти'}</button></div>
      {payload?.patients?.length?<><label htmlFor="archive-search-patient">Пациент</label><select id="archive-search-patient" value={patient} onChange={e=>choosePatient(e.target.value)}><option value="">Определить из запроса</option>{payload.patients.map(p=><option key={p.name} value={p.name}>{p.name}</option>)}</select></>:null}
      <p className="muted">Если имя встречается у нескольких пациентов, поиск попросит выбрать нужного — автоматически угадывать не будет.</p>
    </form>
    {error&&<div className="error-banner" role="alert">{error}</div>}
    {busy?<div className="skeleton"><div/><div/><div/></div>:payload&&<>
      {payload.ambiguous&&<section className="card"><h2>Уточни пациента</h2><p>{payload.message}</p><div className="archive-search-patient-choices">{payload.patient_choices.map(name=><button type="button" key={name} onClick={()=>choosePatient(name)}>{name}<ChevronRight size={16}/></button>)}</div></section>}
      {!payload.ambiguous&&payload.needs_patient&&payload.searched&&<section className="card"><h2>Выбери пациента</h2><p>{payload.message}</p><div className="archive-search-patient-choices">{payload.patient_choices.map(name=><button type="button" key={name} onClick={()=>choosePatient(name)}>{name}<ChevronRight size={16}/></button>)}</div></section>}
      {payload.searched&&!payload.needs_patient&&!payload.ambiguous&&<section className="archive-search-results"><div className="archive-search-results-heading"><h2>Результаты</h2><span>{payload.total} документов</span></div>{payload.message&&<p className="muted">{payload.message}</p>}
        {payload.results.length===0?<div className="card">Подходящие документы не найдены. Попробуй уточнить запрос или выбрать другой тип документа.</div>:payload.results.map(doc=><article className="card archive-search-result" key={doc.id}><div className="archive-search-result-heading"><h3>{doc.title}</h3><span className="archive-search-kind">{doc.kind||'Не определено'}</span></div><p className="muted">Дата: {doc.date||'не указана'} · Пациент: {payload.patient}</p><details><summary>Показать фрагмент OCR-текста</summary><pre>{doc.text||'Текст не распознан.'}</pre></details><div className="archive-search-result-actions"><button type="button" onClick={()=>onNavigate(doc.patient_url)}>История пациента</button><button type="button" className="button-link" onClick={()=>onNavigate(doc.url)}>Открыть документ</button></div></article>)}
      </section>}
      {!payload.searched&&<section className="card archive-search-empty"><Search size={24}/><h2>Найди нужный документ</h2><p>Введи запрос, например «анализы крови», «УЗИ» или «выписка за июнь», и выбери пациента, если понадобится.</p></section>}
    </>}
  </div>;
}

function App() {
  const [path, setPath] = useState(location.pathname + location.search);
  const settingsRoute = path.split('?')[0] === '/settings';
  const searchRoute = path.split('?')[0] === '/search';
  const patientRoute = path.match(/^\/families\/(\d+)\/patients\/([^/?]+)(?:\?[^#]*)?$/);
  const patientNewRoute = path.match(/^\/families\/(\d+)\/patients\/new(?:\?[^#]*)?$/);
  const patientEditRoute = path.match(/^\/families\/(\d+)\/patients\/([^/?]+)\/edit(?:\?[^#]*)?$/);
  const inboxDetailRoute = path.match(/^\/families\/(\d+)\/inbox\/(\d+)(?:\?[^#]*)?$/);
  const inboxRoute = path.match(/^\/families\/(\d+)\/inbox(?:\?[^#]*)?$/);
  const documentEditRoute = path.match(/^\/families\/(\d+)\/documents\/(\d+)\/edit(?:\?[^#]*)?$/);
  const patientRouteData = patientRoute ? {familyId:Number(patientRoute[1]), patient:decodeURIComponent(patientRoute[2])} : null;
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
        {loading && !screen ? <div className="skeleton"><div/><div/><div/></div> : path.split('?')[0] === '/' ? <HomeReactView familyId={new URLSearchParams(path.split('?')[1] || '').has('family_id') ? Number(new URLSearchParams(path.split('?')[1] || '').get('family_id')) : null} onNavigate={(url)=>{void navigate(url);}} /> : searchRoute ? <SearchReactView familyId={new URLSearchParams(path.split('?')[1] || '').has('family_id') ? Number(new URLSearchParams(path.split('?')[1] || '').get('family_id')) : null} onNavigate={(url)=>{void navigate(url);}} /> : settingsRoute ? <SettingsReactView familyId={new URLSearchParams(path.split('?')[1] || '').has('family_id') ? Number(new URLSearchParams(path.split('?')[1] || '').get('family_id')) : null} onNavigate={(url)=>{void navigate(url);}} /> : inboxDetailRoute ? <InboxReviewReactView familyId={Number(inboxDetailRoute[1])} pendingId={Number(inboxDetailRoute[2])} onNavigate={(url)=>{void navigate(url);}} /> : patientNewRoute ? <PatientEditorReactView familyId={Number(patientNewRoute[1])} patient={null} onNavigate={(url)=>{void navigate(url);}} /> : patientEditRoute ? <PatientEditorReactView familyId={Number(patientEditRoute[1])} patient={decodeURIComponent(patientEditRoute[2])} onNavigate={(url)=>{void navigate(url);}} /> : documentEditRoute ? <DocumentEditorReactView familyId={Number(documentEditRoute[1])} documentId={Number(documentEditRoute[2])} onNavigate={(url)=>{void navigate(url);}} /> : inboxRoute ? <InboxReactView familyId={Number(inboxRoute[1])} onNavigate={(url)=>{void navigate(url);}} /> : patientRouteData ? <PatientReactView familyId={patientRouteData.familyId} patient={patientRouteData.patient} onAsk={(selectedIds) => {setPatientAssistantScope({familyId:patientRouteData.familyId,patient:patientRouteData.patient});setSelectedDocumentIds(selectedIds || []);setDocumentSelectionActive(Boolean(selectedIds?.length));setSmartConversation([]);setSmartQuery('');setSmartResult(null);setSmartError('');setSmartConsent(false);setSmartSearchOpen(true);}} /> : <div ref={contentRef} className="legacy-content" dangerouslySetInnerHTML={{ __html: screen?.html || '' }} />}
        {loading && screen && <div className="loading-line"/>}
      </section>}
    </main>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
