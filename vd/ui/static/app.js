'use strict';

const $ = (selector) => document.querySelector(selector);

const KINDS = [
  { id: 'videos', label: 'Videos' },
  { id: 'notes', label: 'Notes' },
  { id: 'dpp', label: 'DPP' },
  { id: 'slides', label: 'Slides' },
  { id: 'documents', label: 'E-books' },
];

// Slides are hundreds of images per subject: shown, but off until ticked.
const DEFAULT_KINDS = ['videos', 'notes', 'dpp', 'documents'];

const S = {
  overview: null,
  key: '',
  plan: null,
  selection: new Set(),
  kinds: new Set(DEFAULT_KINDS),
  onlyMissing: true,
  search: '',
  jobTimer: null,
  logOpen: false,
};

// ---------- small helpers ----------
async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  let data = {};
  try {
    data = await response.json();
  } catch (err) {
    data = { error: `HTTP ${response.status}` };
  }
  if (!response.ok && !data.error) data.error = `HTTP ${response.status}`;
  return data;
}

const fmtGB = (value) => (value === null || value === undefined ? '?' : `${value} GB`);
const fmtMB = (mb) => {
  if (!mb) return '';
  if (mb < 1) return '<1 MB';
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${Math.round(mb)} MB`;
};
const esc = (text) => String(text ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function toast(message, kind = 'info') {
  const node = document.createElement('div');
  node.className = `toast ${kind}`;
  node.textContent = message;
  document.body.appendChild(node);
  setTimeout(() => node.remove(), 6000);
}

// ---------- boot ----------
async function boot() {
  renderKindChips();
  bindEvents();
  await refreshOverview();
  if (S.overview.job && S.overview.job.status === 'running') {
    startPolling();
  }
}

async function refreshOverview() {
  const data = await api('/api/overview');
  if (data.error) {
    toast(data.error, 'bad');
    return;
  }
  S.overview = data;
  $('#root-label').textContent = data.settings.output_root;
  $('#disk-pill').textContent = `Disk free: ${fmtGB(data.free_gb)}`;
  const session = data.session || {};
  const pill = $('#session-pill');
  const ok = session.has_session && session.has_clearance;
  pill.textContent = ok ? 'Session: ✓ set' : 'Session: ✗ refresh';
  pill.className = `pill ${ok ? 'good' : 'bad'}`;
  renderSubjects();
  const settings = data.settings;
  $('#set-root').value = settings.output_root;
  $('#set-concurrency').value = settings.concurrency;
  $('#set-quality').value = settings.quality;
}

function renderSubjects() {
  const list = $('#subject-list');
  list.innerHTML = '';
  const subjects = S.overview?.subjects || [];
  if (!subjects.length) {
    list.innerHTML = '<li class="muted pad">Abhi koi subject link nahi. <b>+ Link</b> dabao.</li>';
    return;
  }
  subjects.forEach((subject) => {
    const li = document.createElement('li');
    li.className = `subject ${subject.key === S.key ? 'active' : ''}`;
    li.dataset.key = subject.key;
    const age = subject.catalog_age_days;
    const badge = subject.has_catalog
      ? `<span class="tag ${age > 7 ? 'warn' : ''}">catalog ${age} din</span>`
      : '<span class="tag bad">catalog nahi</span>';
    li.innerHTML = `
      <div class="subject-name">${esc(subject.subject_name || subject.key)}</div>
      <div class="subject-meta">${badge}<span class="tag">${subject.totals?.videos || 0} videos</span></div>
      <button class="x" title="Remove link">×</button>`;
    list.appendChild(li);
  });
}

async function selectSubject(key) {
  S.key = key;
  renderSubjects();
  await loadPlan();
}

async function loadPlan() {
  if (!S.key) return;
  const params = new URLSearchParams({
    key: S.key,
    kinds: [...S.kinds].join(','),
    only_missing: S.onlyMissing ? '1' : '0',
  });
  const plan = await api(`/api/plan?${params.toString()}`);
  if (plan.error) {
    S.plan = null;
    $('#subject-panel').classList.add('hidden');
    $('#empty').classList.remove('hidden');
    $('#empty').innerHTML = `
      <h2>Catalog nahi hai</h2>
      <p>${esc(plan.error)}</p>
      <p>Left me <b>Catalog refresh</b> dabao (internet chahiye, ~2–5 min).</p>`;
    return;
  }
  S.plan = plan;
  S.selection = new Set(plan.selected_ids || []);
  renderPlan();
}

// ---------- rendering ----------
function renderKindChips() {
  const box = $('#kind-chips');
  box.innerHTML = '';
  KINDS.forEach((kind) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `chip ${S.kinds.has(kind.id) ? 'on' : ''}`;
    button.dataset.kind = kind.id;
    button.textContent = kind.label;
    box.appendChild(button);
  });
  box.querySelectorAll('.chip').forEach((chip) => {
    chip.addEventListener('click', async () => {
      const kind = chip.dataset.kind;
      if (S.kinds.has(kind)) S.kinds.delete(kind); else S.kinds.add(kind);
      renderKindChips();
      await loadPlan();
    });
  });
}

function countsLabel(counts) {
  if (!counts || !counts.total) return '<span class="muted">—</span>';
  const total = counts.total - (counts.unavailable || 0);
  const done = counts.done || 0;
  const cls = done >= total ? 'good' : (done === 0 ? 'bad' : 'warn');
  return `<span class="count ${cls}">${done}/${total}</span>`;
}

function statusTag(item) {
  if (item.status === 'done') return '<span class="tag good">local</span>';
  if (item.status === 'unavailable') return `<span class="tag bad" title="${esc(item.unavailable_reason || '')}">site par nahi</span>`;
  return '<span class="tag warn">missing</span>';
}

function renderPlan() {
  const plan = S.plan;
  if (!plan) return;
  $('#empty').classList.add('hidden');
  $('#subject-panel').classList.remove('hidden');
  $('#subject-title').textContent = plan.subject?.name || S.key;
  const summary = plan.summary;
  $('#subject-sub').textContent =
    `${plan.chapters.length} chapters · ${plan.summary.by_kind.videos.total} videos · ${fmtGB(plan.free_gb)} free · catalog ${plan.catalog_at || '—'}`;

  const byKind = summary.by_kind;
  $('#summary-strip').innerHTML = KINDS.map((kind) => {
    const counts = byKind[kind.id];
    if (!counts || !counts.total) return '';
    return `<span class="stat"><b>${esc(kind.label)}</b> ${countsLabel(counts)}</span>`;
  }).join('') +
    `<span class="stat muted">Missing selected: ${summary.selected} · ~${summary.selected_est_gb} GB</span>`;

  const box = $('#chapters');
  box.innerHTML = '';
  const needle = S.search.trim().toLowerCase();

  plan.chapters.forEach((chapter) => {
    const visibleItems = chapter.items.filter((item) => {
      if (!S.kinds.has(item.kind)) return false;
      if (!needle) return true;
      return chapter.name.toLowerCase().includes(needle) || (item.name || '').toLowerCase().includes(needle);
    });
    if (!visibleItems.length && needle) return;

    const wrapper = document.createElement('details');
    wrapper.className = 'chapter';
    const selectable = visibleItems.filter((item) => item.status === 'missing');
    const selectedHere = selectable.filter((item) => S.selection.has(item.id)).length;

    wrapper.innerHTML = `
      <summary>
        <input type="checkbox" class="chapter-check" data-chapter="${esc(chapter.name)}"
          ${selectable.length && selectedHere === selectable.length ? 'checked' : ''}
          ${selectable.length ? '' : 'disabled'}>
        <span class="chapter-name">${esc(chapter.name)}</span>
        <span class="chapter-counts">
          <span title="videos">▶ ${countsLabel(chapter.counts.videos || kindCount(chapter, 'videos'))}</span>
          <span title="notes">📄 ${countsLabel(kindCount(chapter, 'notes'))}</span>
          <span title="dpp">🧾 ${countsLabel(kindCount(chapter, 'dpp'))}</span>
          <span title="slides">🖼 ${countsLabel(kindCount(chapter, 'slides'))}</span>
          ${kindCount(chapter, 'documents').total ? `<span title="e-books">📚 ${countsLabel(kindCount(chapter, 'documents'))}</span>` : ''}
        </span>
      </summary>
      <div class="items"></div>`;
    const itemsBox = wrapper.querySelector('.items');
    visibleItems.forEach((item) => {
      const row = document.createElement('label');
      row.className = `item ${item.status}`;
      const disabled = item.status !== 'missing';
      row.innerHTML = `
        <input type="checkbox" class="item-check" data-id="${esc(item.id)}"
          ${S.selection.has(item.id) ? 'checked' : ''} ${disabled ? 'disabled' : ''}>
        <span class="kind-pill ${item.kind}">${item.kind}</span>
        <span class="item-name" title="${esc(item.target)}">${esc(item.name)}</span>
        <span class="item-size">${item.status === 'done' ? fmtMB((item.size || 0) / 1048576) : fmtMB(item.size_est_mb)}</span>
        ${statusTag(item)}`;
      itemsBox.appendChild(row);
    });
    box.appendChild(wrapper);
  });

  if (!box.children.length) {
    box.innerHTML = '<p class="muted pad">Is filter me kuch nahi mila.</p>';
  }
  updateSelectionBar();
}

function kindCount(chapter, kind) {
  const counts = { total: 0, done: 0, missing: 0, unavailable: 0 };
  chapter.items.forEach((item) => {
    if (item.kind !== kind) return;
    counts.total += 1;
    counts[item.status] = (counts[item.status] || 0) + 1;
  });
  return counts;
}

function updateSelectionBar() {
  const plan = S.plan;
  const ids = [...S.selection];
  const text = $('#selection-text');
  const button = $('#btn-download');
  if (!plan) {
    text.textContent = 'Kuch select nahi';
    button.disabled = true;
    return;
  }
  let estMb = 0;
  const index = itemIndex();
  ids.forEach((id) => {
    const item = index.get(id);
    if (item) estMb += Number(item.size_est_mb || 0);
  });
  text.innerHTML = `<b>${ids.length}</b> items selected · ~${fmtMB(estMb)} · free ${fmtGB(plan.free_gb)}`;
  button.disabled = ids.length === 0;
  button.textContent = ids.length ? `Download ${ids.length}` : 'Download';
}

function itemIndex() {
  const index = new Map();
  if (!S.plan) return index;
  S.plan.chapters.forEach((chapter) => chapter.items.forEach((item) => index.set(item.id, item)));
  return index;
}

// ---------- events ----------
function bindEvents() {
  $('#subject-list').addEventListener('click', async (event) => {
    const remove = event.target.closest('.x');
    const card = event.target.closest('.subject');
    if (!card) return;
    if (remove) {
      event.stopPropagation();
      if (!confirm('Link remove karein? (files delete nahi hongi)')) return;
      await api(`/api/subjects/${card.dataset.key}`, { method: 'DELETE' });
      if (S.key === card.dataset.key) {
        S.key = '';
        S.plan = null;
        $('#subject-panel').classList.add('hidden');
        $('#empty').classList.remove('hidden');
      }
      await refreshOverview();
      return;
    }
    await selectSubject(card.dataset.key);
  });

  $('#chapters').addEventListener('change', (event) => {
    const itemCheck = event.target.closest('.item-check');
    if (itemCheck) {
      if (itemCheck.checked) S.selection.add(itemCheck.dataset.id);
      else S.selection.delete(itemCheck.dataset.id);
      syncChapterCheck(itemCheck.closest('.chapter'));
      updateSelectionBar();
      return;
    }
    const chapterCheck = event.target.closest('.chapter-check');
    if (chapterCheck) {
      const chapter = chapterCheck.closest('.chapter');
      chapter.querySelectorAll('.item-check:not(:disabled)').forEach((box) => {
        box.checked = chapterCheck.checked;
        if (chapterCheck.checked) S.selection.add(box.dataset.id);
        else S.selection.delete(box.dataset.id);
      });
      updateSelectionBar();
    }
  });

  function syncChapterCheck(chapterNode) {
    if (!chapterNode) return;
    const boxes = [...chapterNode.querySelectorAll('.item-check:not(:disabled)')];
    const head = chapterNode.querySelector('.chapter-check');
    if (!head) return;
    const checked = boxes.filter((box) => box.checked).length;
    head.checked = boxes.length > 0 && checked === boxes.length;
    head.indeterminate = checked > 0 && checked < boxes.length;
  }

  $('#only-missing').addEventListener('change', async (event) => {
    S.onlyMissing = event.target.checked;
    await loadPlan();
  });

  let searchTimer = null;
  $('#search').addEventListener('input', (event) => {
    S.search = event.target.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(renderPlan, 180);
  });

  $('#btn-select-missing').addEventListener('click', () => {
    S.selection = new Set(itemIndex().values());
    S.selection = new Set([...S.selection].filter((item) => item.status === 'missing'));
    renderPlan();
  });

  $('#btn-clear').addEventListener('click', () => {
    S.selection.clear();
    renderPlan();
  });

  $('#btn-catalog').addEventListener('click', async () => {
    if (!S.key) return toast('Pehle subject chuno', 'bad');
    const result = await api('/api/catalog', { method: 'POST', body: JSON.stringify({ key: S.key }) });
    if (!result.ok) return toast(result.error || 'catalog start nahi hua', 'bad');
    toast('Catalog refresh chalu…', 'info');
    startPolling();
  });

  $('#btn-download').addEventListener('click', async () => {
    if (!S.key || !S.selection.size) return;
    const ids = [...S.selection];
    const result = await api('/api/download', { method: 'POST', body: JSON.stringify({ key: S.key, ids }) });
    if (!result.ok) return toast(result.error || 'download start nahi hua', 'bad');
    toast(`${ids.length} items download queue me`, 'info');
    startPolling();
  });

  $('#btn-status').addEventListener('click', async () => {
    if (!S.key) return toast('Pehle subject chuno', 'bad');
    const result = await api('/api/status', { method: 'POST', body: JSON.stringify({ key: S.key }) });
    if (result.error) return toast(result.error, 'bad');
    toast(`Report: ${result.path}`, 'info');
  });

  $('#btn-stop').addEventListener('click', async () => {
    const result = await api('/api/job/stop', { method: 'POST', body: '{}' });
    toast(result.ok ? 'Stop request bheja' : (result.error || ''), result.ok ? 'info' : 'bad');
  });

  $('#btn-log').addEventListener('click', () => {
    S.logOpen = !S.logOpen;
    $('#job-log').classList.toggle('hidden', !S.logOpen);
  });

  $('#session-pill').addEventListener('click', () => $('#dlg-session').showModal());
  $('#btn-settings').addEventListener('click', () => $('#dlg-settings').showModal());
  $('#btn-add-link').addEventListener('click', () => {
    $('#link-msg').textContent = '';
    $('#dlg-link').showModal();
  });

  $('#link-save').addEventListener('click', async (event) => {
    event.preventDefault();
    const url = $('#link-url').value.trim();
    if (!url) return;
    const result = await api('/api/subjects', {
      method: 'POST',
      body: JSON.stringify({ url, dir: $('#link-dir').value.trim() }),
    });
    if (!result.ok) {
      $('#link-msg').textContent = result.error || 'add nahi hua';
      $('#link-msg').className = 'msg bad';
      return;
    }
    $('#dlg-link').close();
    $('#link-url').value = '';
    $('#link-dir').value = '';
    toast('Subject add ho gaya — ab Catalog refresh dabao', 'good');
    await refreshOverview();
    await selectSubject(result.subject.key);
  });

  $('#session-save').addEventListener('click', async (event) => {
    event.preventDefault();
    const raw = $('#session-json').value.trim();
    if (!raw) return;
    const result = await api('/api/session', { method: 'POST', body: JSON.stringify({ cookies: raw }) });
    const msg = $('#session-msg');
    if (!result.ok) {
      msg.textContent = result.error || 'save nahi hua';
      msg.className = 'msg bad';
      return;
    }
    msg.textContent = result.session_ok ? 'Session OK ✓' : `Saved, par verify fail: ${result.detail}`;
    msg.className = `msg ${result.session_ok ? 'good' : 'bad'}`;
    $('#session-json').value = '';
    await refreshOverview();
  });

  $('#settings-save').addEventListener('click', async (event) => {
    event.preventDefault();
    const result = await api('/api/settings', {
      method: 'POST',
      body: JSON.stringify({
        output_root: $('#set-root').value.trim(),
        concurrency: Number($('#set-concurrency').value),
        quality: $('#set-quality').value,
      }),
    });
    if (result.error) {
      $('#settings-msg').textContent = result.error;
      $('#settings-msg').className = 'msg bad';
      return;
    }
    $('#dlg-settings').close();
    toast('Settings save ho gaye', 'good');
    await refreshOverview();
    if (S.key) await loadPlan();
  });
}

// ---------- job polling ----------
function startPolling() {
  if (S.jobTimer) return;
  $('#jobbar').classList.remove('hidden');
  S.jobTimer = setInterval(pollJob, 1000);
  pollJob();
}

async function pollJob() {
  const data = await api('/api/job');
  const job = data.job;
  if (!job) {
    stopPolling();
    return;
  }
  $('#job-title').textContent = job.title;
  const status = $('#job-status');
  status.textContent = job.status;
  status.className = `pill ${job.status === 'running' ? 'info' : (job.status === 'done' ? 'good' : 'bad')}`;
  $('#btn-stop').disabled = job.status !== 'running';

  const progress = job.progress || {};
  const total = progress.total || 0;
  const done = job.kind === 'catalog'
    ? (progress.done || 0)
    : Math.min(progress.done || 0, total);
  const percent = total ? Math.max(2, Math.min(100, (done / total) * 100)) : (job.status === 'running' ? 4 : 0);
  $('#job-fill').style.width = `${percent}%`;

  let current = progress.current || progress.message || '';
  if (progress.phase === 'segments' && progress.segments_total) {
    current = `${current} · segment ${progress.segments_done}/${progress.segments_total}`;
  }
  if (progress.phase === 'mux') current = `${current} · ffmpeg mux`;
  $('#job-current').textContent = current;
  const bits = [];
  if (total) bits.push(`${done}/${total}`);
  if (progress.bytes) bits.push(`${(progress.bytes / 1073741824).toFixed(2)} GB`);
  if (progress.speed_mbps) bits.push(`${progress.speed_mbps} MB/s`);
  if (progress.failed) bits.push(`${progress.failed} failed`);
  bits.push(`${job.elapsed_s}s`);
  $('#job-numbers').textContent = bits.join(' · ');
  $('#job-log').textContent = (job.log || []).join('\n');

  if (job.status !== 'running') {
    stopPolling();
    if (job.status === 'done') toast('Job complete ✓', 'good');
    else if (job.error) toast(job.error, 'bad');
    else if (job.status === 'stopped') toast('Job rok diya', 'info');
    await refreshOverview();
    if (S.key) await loadPlan();
  }
}

function stopPolling() {
  if (S.jobTimer) clearInterval(S.jobTimer);
  S.jobTimer = null;
}

boot();
