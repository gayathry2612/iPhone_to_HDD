'use strict';
// ════════════════════════════════════════════════════════════════════════════
// State
// ════════════════════════════════════════════════════════════════════════════
const state = {
  device:      null,
  selected:    new Map(),   // afc_path → { name, size }
  destination: null,        // local path string
  conflict:    'skip',

  // iPhone tree
  iphone: {
    expanded: new Set(),
    loaded:   new Set(),    // dirs whose children are already in the DOM
  },

  // Destination tree
  local: {
    path:     null,
    expanded: new Set(),
    loaded:   new Set(),
  },
};

// ════════════════════════════════════════════════════════════════════════════
// API
// ════════════════════════════════════════════════════════════════════════════
const api = {
  async json(url, opts = {}) {
    const r = await fetch(url, opts);
    if (!r.ok) {
      const body = await r.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${r.status}`);
    }
    return r.json();
  },
  getDevice:        ()     => api.json('/api/device'),
  connect:          ()     => api.json('/api/connect', { method: 'POST' }),
  iphoneFiles:      (path) => api.json(`/api/iphone/files?path=${enc(path)}`),
  iphoneCollect:    (path) => api.json(`/api/iphone/collect?path=${enc(path)}`),
  localFiles:       (path) => api.json(`/api/local/files?path=${enc(path)}`),
  shortcuts:        ()     => api.json('/api/local/shortcuts'),
  cancelTransfer:   ()     => api.json('/api/transfer/cancel', { method: 'POST' }),
  openFolder:       (path) => api.json('/api/open-folder', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  }),
};

const enc = (s) => encodeURIComponent(s);

// ════════════════════════════════════════════════════════════════════════════
// Utils
// ════════════════════════════════════════════════════════════════════════════
function fmtSize(bytes) {
  if (!bytes) return '';
  const units = ['B','KB','MB','GB','TB'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return (bytes / 1024 ** i).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
}

function fmtSpeed(bps) { return bps > 0 ? fmtSize(bps) + '/s' : ''; }

function fmtETA(secs) {
  if (!Number.isFinite(secs) || secs <= 0) return '';
  if (secs < 60)   return `~${Math.round(secs)}s`;
  if (secs < 3600) return `~${Math.round(secs / 60)}m`;
  return `~${(secs / 3600).toFixed(1)}h`;
}

const FILE_ICONS = {
  jpg:'🖼',jpeg:'🖼',png:'🖼',gif:'🖼',webp:'🖼',heic:'🖼',heif:'🖼',tiff:'🖼',bmp:'🖼',raw:'🖼',
  mov:'🎬',mp4:'🎬',m4v:'🎬',avi:'🎬',mkv:'🎬','3gp':'🎬',
  mp3:'🎵',m4a:'🎵',aac:'🎵',flac:'🎵',wav:'🎵',
  pdf:'📄',epub:'📚',
  zip:'📦',rar:'📦',gz:'📦',
};
function fileIcon(name, isDir) {
  if (isDir) return '📁';
  const ext = name.split('.').pop()?.toLowerCase() ?? '';
  return FILE_ICONS[ext] ?? '📎';
}

// Tiny element factory
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'cls')    el.className = v;
    else if (k === 'st') Object.assign(el.style, v);
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids) {
    if (kid == null) continue;
    el.append(typeof kid === 'string' ? document.createTextNode(kid) : kid);
  }
  return el;
}

const $ = (id) => document.getElementById(id);

// ════════════════════════════════════════════════════════════════════════════
// Device
// ════════════════════════════════════════════════════════════════════════════
async function checkDevice() {
  const d = await api.getDevice();
  if (d.connected) onConnected(d); else showConnectScreen();
}

function showConnectScreen() {
  $('connection-screen').classList.remove('hidden');
  $('main-screen').classList.add('hidden');
  setDeviceStatus(null);
}

async function connectDevice() {
  const btn = $('connect-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Connecting…';
  $('connect-error').textContent = '';
  try {
    const d = await api.connect();
    onConnected(d);
  } catch (e) {
    $('connect-error').textContent = e.message;
    btn.disabled = false;
    btn.textContent = '🔌 Connect iPhone';
  }
}

function onConnected(device) {
  state.device = device;
  $('connection-screen').classList.add('hidden');
  $('main-screen').classList.remove('hidden');
  setDeviceStatus(device);
  loadIPhoneRoot();
  loadShortcuts();
}

function setDeviceStatus(device) {
  const el = $('device-status');
  if (!device) {
    el.innerHTML = '<span class="badge badge-warning">Not connected</span>';
    return;
  }
  el.innerHTML = `
    <span class="badge badge-success">●</span>
    <strong>${device.name}</strong>
    <span class="muted">iOS ${device.ios_version} · ${device.model}</span>`;
}

// ════════════════════════════════════════════════════════════════════════════
// iPhone tree
// ════════════════════════════════════════════════════════════════════════════
async function loadIPhoneRoot() {
  const tree = $('iphone-tree');
  tree.innerHTML = '<div class="loading"><span class="spinner"></span> Loading iPhone…</div>';
  try {
    const entries = await api.iphoneFiles('/');
    tree.innerHTML = '';
    for (const entry of entries) appendIPhoneRow(tree, entry, 0);
  } catch (e) {
    tree.innerHTML = `<div class="loading error-text">⚠ ${e.message}</div>`;
  }
}

function appendIPhoneRow(container, entry, depth) {
  const pl = depth * 18 + 8;

  if (entry.is_dir) {
    // ── Directory row ────────────────────────────────────────────────────
    const arrow   = h('span', { cls: 'arrow' }, '▶');
    const icon    = h('span', { cls: 'icon'  }, '📁');
    const name    = h('span', { cls: 'name'  }, entry.name);
    const selBtn  = h('button', {
      cls: 'btn btn-sm row-action',
      title: 'Select all files in this folder',
      onclick: (e) => { e.stopPropagation(); handleSelectDir(entry.path, selBtn); },
    }, '☑ All');

    const row = h('div', {
      cls: 'tree-row',
      'data-path': entry.path,
      'data-dir': '1',
      st: { paddingLeft: pl + 'px' },
      onclick: () => toggleIPhoneDir(entry, row, childWrap, depth),
    }, arrow, icon, name, selBtn);

    // ── Children wrapper ─────────────────────────────────────────────────
    const childWrap = h('div', {
      cls: 'hidden',
      'data-children-for': entry.path,
    });

    container.appendChild(row);
    container.appendChild(childWrap);

  } else {
    // ── File row ─────────────────────────────────────────────────────────
    const isSel    = state.selected.has(entry.path);
    const checkbox = h('span', { cls: 'checkbox' + (isSel ? ' checked' : '') }, isSel ? '☑' : '☐');
    const icon     = h('span', { cls: 'icon' }, fileIcon(entry.name, false));
    const name     = h('span', { cls: 'name' }, entry.name);
    const size     = h('span', { cls: 'fsize' }, fmtSize(entry.size));

    const row = h('div', {
      cls: 'tree-row' + (isSel ? ' selected' : ''),
      'data-path': entry.path,
      st: { paddingLeft: pl + 'px' },
      onclick: () => toggleFileSelect(entry, row, checkbox),
    }, checkbox, icon, name, size);

    container.appendChild(row);
  }
}

async function toggleIPhoneDir(entry, row, childWrap, depth) {
  const expanded = state.iphone.expanded.has(entry.path);

  if (expanded) {
    state.iphone.expanded.delete(entry.path);
    row.classList.remove('expanded');
    childWrap.classList.add('hidden');
  } else {
    state.iphone.expanded.add(entry.path);
    row.classList.add('expanded');
    childWrap.classList.remove('hidden');

    if (!state.iphone.loaded.has(entry.path)) {
      childWrap.innerHTML = '<div class="loading"><span class="spinner"></span></div>';
      try {
        const entries = await api.iphoneFiles(entry.path);
        childWrap.innerHTML = '';
        state.iphone.loaded.add(entry.path);
        for (const e of entries) appendIPhoneRow(childWrap, e, depth + 1);
      } catch (err) {
        childWrap.innerHTML = `<div class="loading error-text" style="padding-left:${(depth+1)*18+8}px">⚠ ${err.message}</div>`;
      }
    }
  }
}

function toggleFileSelect(entry, row, checkbox) {
  if (state.selected.has(entry.path)) {
    state.selected.delete(entry.path);
    row.classList.remove('selected');
    checkbox.className = 'checkbox';
    checkbox.textContent = '☐';
  } else {
    state.selected.set(entry.path, { name: entry.name, size: entry.size });
    row.classList.add('selected');
    checkbox.className = 'checkbox checked';
    checkbox.textContent = '☑';
  }
  refreshTransferBar();
}

async function handleSelectDir(path, btn) {
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  try {
    const files = await api.iphoneCollect(path);
    for (const f of files) state.selected.set(f.path, { name: f.name, size: f.size });
    syncIPhoneCheckboxes();
    refreshTransferBar();
  } finally {
    btn.disabled = false;
    btn.textContent = '☑ All';
  }
}

function syncIPhoneCheckboxes() {
  // Sync visible file rows with the current selection state
  $('iphone-tree').querySelectorAll('.tree-row:not([data-dir])').forEach(row => {
    const path = row.dataset.path;
    const isSel = state.selected.has(path);
    row.classList.toggle('selected', isSel);
    const cb = row.querySelector('.checkbox');
    if (cb) {
      cb.className = 'checkbox' + (isSel ? ' checked' : '');
      cb.textContent = isSel ? '☑' : '☐';
    }
  });
}

function clearSelection() {
  state.selected.clear();
  syncIPhoneCheckboxes();
  refreshTransferBar();
}

// ════════════════════════════════════════════════════════════════════════════
// Destination tree
// ════════════════════════════════════════════════════════════════════════════
async function loadShortcuts() {
  const bar = $('shortcuts-bar');
  bar.innerHTML = '';
  try {
    const list = await api.shortcuts();
    for (const s of list) {
      const btn = h('button', {
        cls: 'shortcut-btn',
        onclick: () => navigateDest(s.path, btn),
      }, s.icon, ' ', s.name);
      bar.appendChild(btn);
    }
    // Default to Downloads
    const dl = list.find(s => s.name === 'Downloads');
    if (dl) {
      const dlBtn = bar.querySelector(`button:nth-child(${list.indexOf(dl) + 1})`);
      navigateDest(dl.path, dlBtn);
    }
  } catch (e) {
    bar.textContent = 'Could not load shortcuts';
  }
}

async function navigateDest(path, activeBtn) {
  state.local.path = path;
  state.local.expanded.clear();
  state.local.loaded.clear();

  // Update active shortcut highlight
  $('shortcuts-bar').querySelectorAll('.shortcut-btn').forEach(b => b.classList.remove('active'));
  if (activeBtn) activeBtn.classList.add('active');

  $('dest-breadcrumb').textContent = path;

  const tree = $('dest-tree');
  tree.innerHTML = '<div class="loading"><span class="spinner"></span> Loading…</div>';

  try {
    const entries = await api.localFiles(path);
    tree.innerHTML = '';

    // "Use this folder" row at top
    tree.appendChild(makeDestUseRow(path));

    // Only directories (you pick a destination folder, not files)
    const dirs = entries.filter(e => e.is_dir);
    for (const d of dirs) appendLocalRow(tree, d, 0);
  } catch (e) {
    tree.innerHTML = `<div class="loading error-text">⚠ ${e.message}</div>`;
  }
}

function makeDestUseRow(path) {
  const shortName = path.split('/').pop() || path;
  return h('div', {
    cls: 'dest-use-row',
    title: `Set "${path}" as destination`,
    onclick: () => setDestination(path),
  }, '🎯 Use ', h('strong', {}, shortName), ' as destination');
}

function appendLocalRow(container, entry, depth) {
  const pl = depth * 18 + 8;

  const arrow   = h('span', { cls: 'arrow' }, '▶');
  const icon    = h('span', { cls: 'icon'  }, '📁');
  const name    = h('span', { cls: 'name'  }, entry.name);
  const useBtn  = h('button', {
    cls: 'btn btn-sm row-action',
    title: `Use "${entry.path}" as destination`,
    onclick: (e) => { e.stopPropagation(); setDestination(entry.path); },
  }, '🎯 Use');

  const row = h('div', {
    cls: 'tree-row' + (state.destination === entry.path ? ' dest-active' : ''),
    'data-path': entry.path,
    st: { paddingLeft: pl + 'px' },
  }, arrow, icon, name, useBtn);

  const childWrap = h('div', { cls: 'hidden', 'data-local-children-for': entry.path });

  row.addEventListener('click', async (e) => {
    if (e.target.closest('button')) return;
    const exp = state.local.expanded.has(entry.path);
    if (exp) {
      state.local.expanded.delete(entry.path);
      row.classList.remove('expanded');
      childWrap.classList.add('hidden');
    } else {
      state.local.expanded.add(entry.path);
      row.classList.add('expanded');
      childWrap.classList.remove('hidden');

      if (!state.local.loaded.has(entry.path)) {
        childWrap.innerHTML = '<div class="loading"><span class="spinner"></span></div>';
        try {
          const children = await api.localFiles(entry.path);
          childWrap.innerHTML = '';
          state.local.loaded.add(entry.path);

          // "Use this" row in sub-dir
          childWrap.appendChild(makeDestUseRow(entry.path));

          for (const c of children.filter(x => x.is_dir)) {
            appendLocalRow(childWrap, c, depth + 1);
          }
        } catch (err) {
          childWrap.innerHTML = `<div class="loading error-text">⚠ ${err.message}</div>`;
        }
      }
    }
  });

  container.appendChild(row);
  container.appendChild(childWrap);
}

function setDestination(path) {
  state.destination = path;
  const shortName = path.split('/').pop() || path;

  // Breadcrumb
  $('dest-breadcrumb').textContent = `📍 ${path}`;

  // Highlight badge
  $('dest-badge').textContent = shortName;
  $('dest-badge').classList.remove('hidden');

  // Highlight row
  $('dest-tree').querySelectorAll('.tree-row').forEach(r => {
    r.classList.toggle('dest-active', r.dataset.path === path);
  });

  refreshTransferBar();
}

// ════════════════════════════════════════════════════════════════════════════
// Transfer bar
// ════════════════════════════════════════════════════════════════════════════
function refreshTransferBar() {
  const count = state.selected.size;
  const bytes = [...state.selected.values()].reduce((s, f) => s + f.size, 0);

  if (count === 0) {
    $('selection-info').innerHTML = '<span class="muted">No files selected</span>';
  } else {
    $('selection-info').innerHTML =
      `<strong>${count} file${count !== 1 ? 's' : ''}</strong>` +
      ` <span class="muted">(${fmtSize(bytes)})</span>`;
  }

  const destEl = $('dest-label');
  if (state.destination) {
    destEl.textContent = `→ ${state.destination}`;
    destEl.style.color = 'var(--muted)';
  } else {
    destEl.textContent = 'No destination selected';
    destEl.style.color = 'var(--danger)';
  }

  $('transfer-btn').disabled = count === 0 || !state.destination;
}

// ════════════════════════════════════════════════════════════════════════════
// Transfer
// ════════════════════════════════════════════════════════════════════════════
const speedCalc = { lastBytes: 0, lastTime: Date.now(), value: 0 };

function trackSpeed(doneBytes) {
  const now = Date.now();
  const dt = (now - speedCalc.lastTime) / 1000;
  if (dt >= 1) {
    speedCalc.value = (doneBytes - speedCalc.lastBytes) / dt;
    speedCalc.lastBytes = doneBytes;
    speedCalc.lastTime  = now;
  }
  return speedCalc.value;
}

async function startTransfer() {
  if (!state.selected.size || !state.destination) return;

  // Reset speed tracker
  Object.assign(speedCalc, { lastBytes: 0, lastTime: Date.now(), value: 0 });

  // Build payload
  const selected = {};
  for (const [path, { size }] of state.selected) selected[path] = size;

  // Show modal (progress view)
  showModal('progress');

  try {
    const resp = await fetch('/api/transfer', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ selected, destination: state.destination, conflict: state.conflict }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }

    // Parse Server-Sent Events from the streaming response
    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let   buf     = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      const lines = buf.split('\n');
      buf = lines.pop();  // keep incomplete last line

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let data;
        try { data = JSON.parse(line.slice(6)); } catch { continue; }
        if (data.ping) continue;
        onTransferProgress(data);
        if (data.finished || data.cancelled) return;
      }
    }
  } catch (e) {
    showModal('error', e.message);
  }
}

function onTransferProgress(data) {
  if (data.finished) {
    showModal('complete', data);
    return;
  }
  if (data.cancelled) {
    hideModal();
    return;
  }

  // Update in-progress view
  $('xfr-current').textContent   = data.current_file || '—';
  $('xfr-file-bar').style.width  = (data.byte_pct || 0) + '%';
  $('xfr-overall-bar').style.width = (data.file_pct || 0) + '%';
  $('xfr-count').textContent     = `${data.done_files} / ${data.total_files} files`;
  $('xfr-bytes').textContent     = `${fmtSize(data.done_bytes)} / ${fmtSize(data.total_bytes)}`;

  const speed = trackSpeed(data.done_bytes);
  const eta   = speed > 0 ? fmtETA((data.total_bytes - data.done_bytes) / speed) : '';
  $('xfr-speed').textContent = speed > 0 ? `${fmtSpeed(speed)}  ${eta}` : '';
}

async function cancelTransfer() {
  await api.cancelTransfer().catch(() => {});
  hideModal();
}

// ════════════════════════════════════════════════════════════════════════════
// Modal helpers
// ════════════════════════════════════════════════════════════════════════════
function showModal(mode, payload) {
  $('transfer-modal').classList.remove('hidden');
  $('modal-progress').classList.toggle('hidden', mode !== 'progress');
  $('modal-complete').classList.toggle('hidden', mode !== 'complete');
  $('modal-error').classList.toggle('hidden',    mode !== 'error');

  if (mode === 'complete' && payload) {
    const d = payload;
    $('cmp-count').textContent   = `${d.done_files} file${d.done_files !== 1 ? 's' : ''}`;
    $('cmp-size').textContent    = fmtSize(d.done_bytes) || '0 B';
    $('cmp-skipped').textContent = d.skipped > 0 ? `${d.skipped}` : '—';
    $('cmp-errors').textContent  = d.errors?.length > 0 ? d.errors.join('; ') : '—';
    $('cmp-dest').textContent    = state.destination;

    // Turn progress fills green
    $('xfr-file-bar').classList.add('done');
    $('xfr-overall-bar').classList.add('done');
  }

  if (mode === 'error' && payload) {
    $('modal-error-msg').textContent = payload;
  }
}

function hideModal() {
  $('transfer-modal').classList.add('hidden');
  $('xfr-file-bar').classList.remove('done');
  $('xfr-overall-bar').classList.remove('done');
}

// ════════════════════════════════════════════════════════════════════════════
// Init
// ════════════════════════════════════════════════════════════════════════════
function init() {
  // Connection
  $('connect-btn').addEventListener('click', connectDevice);
  $('header-reconnect-btn').addEventListener('click', connectDevice);

  // iPhone panel controls
  $('select-dcim-btn').addEventListener('click', async () => {
    const btn = $('select-dcim-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Scanning…';
    try {
      const files = await api.iphoneCollect('/DCIM');
      for (const f of files) state.selected.set(f.path, { name: f.name, size: f.size });
      syncIPhoneCheckboxes();
      refreshTransferBar();
    } catch (e) {
      alert(`Could not scan DCIM: ${e.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = '☑ All Photos';
    }
  });

  $('clear-btn').addEventListener('click', clearSelection);

  // Conflict policy
  $('conflict-policy').addEventListener('change', (e) => { state.conflict = e.target.value; });

  // Transfer
  $('transfer-btn').addEventListener('click', startTransfer);

  // Modal buttons
  $('xfr-cancel-btn').addEventListener('click', cancelTransfer);
  $('modal-done-btn').addEventListener('click', hideModal);
  $('modal-err-close').addEventListener('click', hideModal);
  $('open-dest-btn').addEventListener('click', () => {
    if (state.destination) api.openFolder(state.destination);
    hideModal();
  });

  // Close modal on backdrop click
  $('transfer-modal').addEventListener('click', (e) => {
    if (e.target === $('transfer-modal')) hideModal();
  });

  // Keyboard: Escape closes modal
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') hideModal();
  });

  // Check device on load
  checkDevice();
}

document.addEventListener('DOMContentLoaded', init);
