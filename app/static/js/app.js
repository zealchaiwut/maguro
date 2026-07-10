/** Maguro frontend — vanilla JS SPA */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  config: null,
  orderDates: [],
  route: 'orders',
  editingId: null,
  prefillDate: null,
  prefillName: null,
  prefillNote: null,
  prefillPhone: null,
  prefillAddress: null,
  bangkokToday: '',
  inboxLabels: ['Interested', 'Confirmed', 'Asked price', 'No reply needed'],
  inboxFilter: 'all',
  inboxGroups: [
    { id: 'all', label: 'All' },
    { id: 'new', label: 'New message' },
    { id: 'pending', label: 'Pending' },
    { id: 'replied', label: 'Replied' },
  ],
};

// ── API ──────────────────────────────────────────────

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    credentials: 'same-origin',
    ...options,
  });
  if (res.status === 401) {
    showLogin();
    throw new Error('Unauthorized');
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

// ── Bangkok date helpers ─────────────────────────────

function bangkokISODate(d = new Date()) {
  return d.toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });
}

function formatDisplayDate(iso) {
  const [y, m, day] = iso.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, day));
  return dt.toLocaleDateString('en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

function formatBaht(n) {
  return `฿${Number(n).toLocaleString('en-US')}`;
}

async function fetchOrderDates() {
  state.orderDates = await api('/api/dates');
  return state.orderDates;
}

/** Pick default: today if it has orders, else most recent order date. */
function defaultOrderDate() {
  if (!state.orderDates.length) return state.bangkokToday;
  const today = state.bangkokToday;
  if (state.orderDates.some((d) => d.date === today)) return today;
  return state.orderDates[0].date;
}

function populateDateSelect(selectEl, selectedDate) {
  selectEl.innerHTML = '';
  const dates = [...state.orderDates];
  if (selectedDate && !dates.some((d) => d.date === selectedDate)) {
    dates.unshift({ date: selectedDate, order_count: 0 });
    dates.sort((a, b) => b.date.localeCompare(a.date));
  }
  if (!dates.length) {
    selectEl.innerHTML = `<option value="">No order dates</option>`;
    return;
  }
  for (const { date, order_count } of dates) {
    const opt = document.createElement('option');
    opt.value = date;
    const suffix = order_count ? ` (${order_count})` : ' (new)';
    opt.textContent = `${formatDisplayDate(date)}${suffix}`;
    selectEl.appendChild(opt);
  }
  const pick = selectedDate && dates.some((d) => d.date === selectedDate)
    ? selectedDate
    : defaultOrderDate();
  selectEl.value = pick;
}

function setupNewDateButton(btn, dateSelect, onDateReady) {
  btn?.addEventListener('click', () => openNewDateDialog((iso) => {
    populateDateSelect(dateSelect, iso);
    dateSelect.value = iso;
    onDateReady(iso);
  }));
}

function openNewDateDialog(onConfirm) {
  const dialog = $('#new-date-dialog');
  const input = $('#new-date-input');
  input.value = state.bangkokToday;
  dialog.showModal();
  input.focus();

  const form = $('#new-date-form');
  const cancel = () => dialog.close();

  $('#new-date-cancel').onclick = cancel;

  form.onsubmit = (e) => {
    e.preventDefault();
    const iso = input.value;
    if (!iso) return;
    dialog.close();
    state.prefillDate = iso;
    onConfirm(iso);
  };
}

function roundClass(name) {
  if (name.includes('Lunch')) return 'lunch';
  if (name.includes('Afternoon')) return 'afternoon';
  if (name.includes('Dinner')) return 'dinner';
  return '';
}

function roundLabel(name) {
  const map = {
    '01_Lunch': 'Lunch',
    '02_Afternoon': 'Afternoon',
    '03_Dinner': 'Dinner',
  };
  return map[name] || name;
}

// ── Auth & boot ──────────────────────────────────────

function showLogin() {
  $('#view-login').classList.remove('hidden');
  $('#shell').classList.add('hidden');
}

function showShell() {
  $('#view-login').classList.add('hidden');
  $('#shell').classList.remove('hidden');
}

async function boot() {
  state.bangkokToday = bangkokISODate();
  state.config = await api('/api/config');
  state.inboxLabels = state.config.inbox_labels || state.inboxLabels;
  if (state.config.inbox_groups) state.inboxGroups = state.config.inbox_groups;

  const me = await api('/api/me');
  if (!me.authenticated) {
    showLogin();
    return;
  }
  showShell();
  await fetchOrderDates();
  navigate(location.hash.slice(1) || 'orders');
}

$('#login-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const errEl = $('#login-error');
  errEl.classList.add('hidden');
  try {
    await api('/api/login', {
      method: 'POST',
      body: JSON.stringify({ password: $('#login-password').value }),
    });
    showShell();
    await fetchOrderDates();
    navigate('orders');
  } catch {
    errEl.textContent = 'Wrong password';
    errEl.classList.remove('hidden');
  }
});

$('#btn-logout')?.addEventListener('click', async () => {
  try { await api('/api/logout', { method: 'POST' }); } catch { /* ok */ }
  showLogin();
});

function updateShellChrome(route) {
  const tab = route === 'form' ? 'orders' : route;
  $$('.nav-item').forEach((el) => {
    el.classList.toggle('active', el.dataset.route === tab);
  });
}

// ── Routing ──────────────────────────────────────────

function navigate(route, params = {}) {
  if (route === 'new') {
    state.route = 'form';
    state.editingId = null;
    location.hash = 'new';
  } else if (route.startsWith('edit/')) {
    state.route = 'form';
    state.editingId = route.slice(5);
    location.hash = route;
  } else {
    state.route = route;
    state.editingId = null;
    location.hash = route;
  }

  updateShellChrome(state.route);

  render(params);
}

window.addEventListener('hashchange', () => {
  const hash = location.hash.slice(1) || 'orders';
  if (hash.startsWith('edit/')) navigate(hash);
  else navigate(hash);
});

$$('.nav-item').forEach((btn) => {
  btn.addEventListener('click', () => navigate(btn.dataset.route));
});

// ── Render dispatch ──────────────────────────────────

function render(params = {}) {
  const main = $('#main-content');
  if (state.route === 'orders') renderOrders(main);
  else if (state.route === 'summary') renderSummary(main);
  else if (state.route === 'inbox') renderInbox(main);
  else if (state.route === 'form') renderForm(main, params);
}

// ── Orders list ──────────────────────────────────────

async function renderOrders(main) {
  main.innerHTML = '';
  const tpl = $('#tpl-orders').content.cloneNode(true);
  main.appendChild(tpl);

  const dateSelect = $('#orders-date');
  populateDateSelect(dateSelect);
  const showDone = $('#orders-show-done');

  setupNewDateButton($('#orders-new-date'), dateSelect, () => {
    load();
  });

  $('#btn-add-order')?.addEventListener('click', () => navigate('new'));

  async function load() {
    const includeDone = showDone.checked;
    const listEl = $('#orders-list');
    const emptyEl = $('#orders-empty');
    listEl.innerHTML = '<p class="empty">Loading…</p>';

    try {
      const orders = await api(`/api/orders?date=${dateSelect.value}&include_done=${includeDone}`);
      listEl.innerHTML = '';
      if (!orders.length) {
        emptyEl.classList.remove('hidden');
        emptyEl.innerHTML = `
          No orders for ${formatDisplayDate(dateSelect.value)}.
          <br><button type="button" class="btn btn-primary btn-sm empty-add">Add first order</button>`;
        emptyEl.querySelector('.empty-add')?.addEventListener('click', () => {
          state.prefillDate = dateSelect.value;
          navigate('new');
        });
        return;
      }
      emptyEl.classList.add('hidden');
      emptyEl.innerHTML = 'No orders for this date.';

      const grouped = groupByRound(orders);
      for (const [round, items] of grouped) {
        const section = document.createElement('div');
        section.className = 'round-group';
        const boxes = items.reduce((s, o) => s + o.amount, 0);
        section.innerHTML = `
          <div class="round-header">
            <span class="round-badge ${roundClass(round)}">${roundLabel(round)}</span>
            <span class="round-meta">${items.length} orders · ${boxes} boxes</span>
          </div>`;
        const list = document.createElement('div');
        items.forEach((o) => list.appendChild(orderCard(o)));
        section.appendChild(list);
        listEl.appendChild(section);
      }
    } catch (err) {
      listEl.innerHTML = `<p class="error">${esc(err.message)}</p>`;
    }
  }

  dateSelect.addEventListener('change', load);
  showDone.addEventListener('change', load);
  load();
}

function groupByRound(orders) {
  const rounds = state.config.rounds;
  const map = new Map(rounds.map((r) => [r, []]));
  for (const o of orders) {
    const key = o.delivery_time && map.has(o.delivery_time) ? o.delivery_time : '_other';
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(o);
  }
  return [...map.entries()].filter(([, items]) => items.length);
}

function orderCard(order, { clickable = true } = {}) {
  const el = document.createElement('article');
  el.className = `order-card${order.status === 'Done' ? ' done' : ''}`;
  if (clickable) {
    el.addEventListener('click', () => navigate(`edit/${order.id}`));
  }

  const tags = [
    order.fulfillment ? `<span class="tag fulfillment">${esc(order.fulfillment)}</span>` : '',
    order.paid
      ? '<span class="tag paid">Paid</span>'
      : '<span class="tag unpaid">Unpaid</span>',
    order.status === 'Done' ? '<span class="tag done">Done</span>' : '',
  ].join('');

  el.innerHTML = `
    <div class="order-card-top">
      <p class="order-name">${esc(order.name)}</p>
      <span class="order-qty">${order.amount} box${order.amount !== 1 ? 'es' : ''}</span>
    </div>
    <div class="order-tags">${tags}</div>
    ${order.note ? `<p class="order-note">${esc(order.note)}</p>` : ''}
    ${order.address ? `<p class="order-address">📍 ${esc(order.address)}</p>` : ''}
    <div class="order-copy-row">
      <button type="button" class="btn btn-sm btn-ghost copy-msg" data-template="confirm">Copy confirm</button>
      <button type="button" class="btn btn-sm btn-ghost copy-msg" data-template="tracking">Copy tracking</button>
      <a class="btn btn-sm btn-ghost order-label-link" href="/label/${order.id}" target="_blank" rel="noopener">🏷 Label</a>
    </div>
  `;

  el.querySelector('.order-label-link')?.addEventListener('click', (e) => e.stopPropagation());

  el.querySelectorAll('.copy-msg').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const original = btn.textContent;
      btn.disabled = true;
      try {
        const { text } = await api(`/api/orders/${order.id}/message?template=${btn.dataset.template}`);
        await navigator.clipboard.writeText(text);
        btn.textContent = 'Copied ✓';
      } catch {
        btn.textContent = 'Copy failed';
      }
      setTimeout(() => {
        btn.textContent = original;
        btn.disabled = false;
      }, 1500);
    });
  });
  return el;
}

// ── Summary ──────────────────────────────────────────

async function renderSummary(main) {
  main.innerHTML = '';
  main.appendChild($('#tpl-summary').content.cloneNode(true));

  const dateSelect = $('#summary-date');
  populateDateSelect(dateSelect);
  const openOnly = $('#summary-open-only');

  setupNewDateButton($('#summary-new-date'), dateSelect, () => {
    load();
  });

  async function load() {
    const statsEl = $('#summary-stats');
    const roundsEl = $('#summary-rounds');
    statsEl.innerHTML = '<p class="empty">Loading…</p>';
    roundsEl.innerHTML = '';

    try {
      const s = await api(`/api/summary?date=${dateSelect.value}&open_only=${openOnly.checked}`);
      statsEl.innerHTML = `
        <div class="stat-card">
          <div class="stat-label">Orders</div>
          <div class="stat-value">${s.total_orders}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Boxes</div>
          <div class="stat-value">${s.total_boxes}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Unpaid</div>
          <div class="stat-value">${s.unpaid_count}</div>
        </div>
        <div class="stat-card wide">
          <div class="stat-label">Revenue estimate</div>
          <div class="stat-value">${formatBaht(s.grand_total)}</div>
          <div class="stat-sub">${formatBaht(s.box_revenue)} boxes + ${formatBaht(s.delivery_fees)} delivery</div>
        </div>`;

      for (const round of s.rounds) {
        if (!round.order_count) continue;
        const section = document.createElement('div');
        section.className = 'summary-section';
        section.innerHTML = `
          <div class="round-summary-card">
            <div class="round-summary-top">
              <span class="round-badge ${roundClass(round.name)}">${round.label}</span>
              <div class="round-box-hero">${round.box_count}<span>boxes</span></div>
            </div>
            <div class="round-summary-sub">${round.order_count} order${round.order_count !== 1 ? 's' : ''}</div>
            <a class="btn btn-sm btn-ghost round-labels-link" href="/label/round/${dateSelect.value}/${round.name}" target="_blank" rel="noopener">🏷 Labels</a>
          </div>`;

        if (round.deliveries.length) {
          section.appendChild(sectionHeading(`Delivery (${round.deliveries.length})`));
          const list = document.createElement('div');
          list.className = 'summary-list';
          round.deliveries.forEach((o) => list.appendChild(orderCard(o, { clickable: false })));
          section.appendChild(list);
        }
        if (round.pickups.length) {
          section.appendChild(sectionHeading(`Pick-up (${round.pickups.length})`));
          const list = document.createElement('div');
          list.className = 'summary-list';
          round.pickups.forEach((o) => list.appendChild(orderCard(o, { clickable: false })));
          section.appendChild(list);
        }
        roundsEl.appendChild(section);
      }

      if (!roundsEl.children.length) {
        roundsEl.innerHTML = `
          <p class="empty">
            No orders for ${formatDisplayDate(dateSelect.value)}.
            <br><button type="button" class="btn btn-primary btn-sm empty-add">Add first order</button>
          </p>`;
        roundsEl.querySelector('.empty-add')?.addEventListener('click', () => {
          state.prefillDate = dateSelect.value;
          navigate('new');
        });
      }
    } catch (err) {
      statsEl.innerHTML = `<p class="error">${esc(err.message)}</p>`;
    }
  }

  dateSelect.addEventListener('change', load);
  openOnly.addEventListener('change', load);
  load();
}

function sectionHeading(text) {
  const h = document.createElement('h3');
  h.textContent = text;
  return h;
}

// ── Order form ───────────────────────────────────────

async function renderForm(main) {
  main.innerHTML = '';
  main.appendChild($('#tpl-form').content.cloneNode(true));

  const form = $('#order-form');
  const errEl = $('#form-error');
  const isEdit = Boolean(state.editingId);
  $('#form-title').textContent = isEdit ? 'Edit order' : 'New order';

  fillSelect(form.delivery_time, state.config.rounds);
  fillSelect(form.fulfillment, state.config.fulfillment_options);
  fillSelect(form.status, state.config.status_options);

  form.date.value = state.prefillDate || defaultOrderDate();
  if (state.prefillName) {
    form.name.value = state.prefillName;
  }
  if (state.prefillNote) {
    form.note.value = state.prefillNote;
  }
  if (state.prefillPhone) {
    form.phone.value = state.prefillPhone;
  }
  if (state.prefillAddress) {
    form.address.value = state.prefillAddress;
  }
  state.prefillDate = null;
  state.prefillName = null;
  state.prefillNote = null;
  state.prefillPhone = null;
  state.prefillAddress = null;
  form.fulfillment.value = 'Delivery';
  form.delivery_time.value = state.config.rounds[0];
  form.status.value = 'Open';

  if (isEdit) {
    try {
      const order = await api(`/api/orders/${state.editingId}`);
      form.name.value = order.name;
      form.phone.value = order.phone || '';
      form.date.value = order.date || state.bangkokToday;
      form.amount.value = order.amount;
      form.delivery_fee.value = order.delivery_fee || 0;
      form.delivery_time.value = order.delivery_time || state.config.rounds[0];
      form.fulfillment.value = order.fulfillment || 'Delivery';
      form.address.value = order.address || '';
      form.note.value = order.note || '';
      form.paid.checked = order.paid;
      form.status.value = order.status || 'Open';
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove('hidden');
    }
    setupEvidenceSection(state.editingId);
  }

  $('#form-cancel').addEventListener('click', () => navigate('orders'));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    errEl.classList.add('hidden');
    const body = {
      name: form.name.value.trim(),
      phone: form.phone.value.trim(),
      date: form.date.value,
      amount: Number(form.amount.value),
      delivery_fee: Number(form.delivery_fee.value) || 0,
      delivery_time: form.delivery_time.value,
      fulfillment: form.fulfillment.value,
      address: form.address.value.trim(),
      note: form.note.value.trim(),
      paid: form.paid.checked,
      status: form.status.value,
    };

    try {
      if (isEdit) {
        await api(`/api/orders/${state.editingId}`, { method: 'PATCH', body: JSON.stringify(body) });
      } else {
        await api('/api/orders', { method: 'POST', body: JSON.stringify(body) });
      }
      await fetchOrderDates();
      navigate('orders');
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove('hidden');
    }
  });
}

function fillSelect(select, options) {
  select.innerHTML = options.map((o) => `<option value="${esc(o)}">${esc(o.replace(/^\d+_/, '').replace('_', ' '))}</option>`).join('');
}

function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Evidence (payment slips, chat/comment screenshots) ────

function evidenceThumb(item) {
  const isImage = (item.content_type || '').startsWith('image/');
  const preview = isImage
    ? `<img src="${esc(item.url)}" alt="${esc(item.kind)}" loading="lazy">`
    : `<span class="evidence-file-icon">📎</span>`;
  return `
    <a class="evidence-item" href="${esc(item.url)}" target="_blank" rel="noopener">
      ${preview}
      <span class="evidence-tag">${esc(item.kind)}${item.source === 'instagram' ? ' · IG' : ''}</span>
    </a>`;
}

async function loadEvidenceList(orderId, listEl) {
  try {
    const items = await api(`/api/orders/${orderId}/evidence`);
    listEl.innerHTML = items.length
      ? items.map(evidenceThumb).join('')
      : '<p class="empty">No evidence attached yet.</p>';
  } catch (err) {
    listEl.innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}

function setupEvidenceSection(orderId) {
  const section = $('#order-evidence');
  section.classList.remove('hidden');
  const listEl = $('#evidence-list');
  const form = $('#evidence-form');
  const errEl = $('#evidence-error');

  loadEvidenceList(orderId, listEl);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    errEl.classList.add('hidden');
    const file = form.file.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    fd.append('kind', form.kind.value);
    try {
      const res = await fetch(`/api/orders/${orderId}/evidence`, {
        method: 'POST',
        credentials: 'same-origin',
        body: fd,
      });
      if (res.status === 401) {
        showLogin();
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || res.statusText);
      form.reset();
      await loadEvidenceList(orderId, listEl);
    } catch (err) {
      errEl.textContent = err.message;
      errEl.classList.remove('hidden');
    }
  });
}

// ── Paste DM thread → phone/address suggestions (no Meta needed) ────

function setupPasteExtract() {
  const textarea = $('#paste-dm-text');
  const btn = $('#paste-extract-btn');
  const resultEl = $('#paste-extract-result');
  if (!textarea || !btn) return;

  btn.addEventListener('click', async () => {
    const text = textarea.value.trim();
    if (!text) {
      textarea.focus();
      return;
    }
    btn.disabled = true;
    btn.textContent = 'Extracting…';
    try {
      const hints = await api('/api/inbox/extract', {
        method: 'POST',
        body: JSON.stringify({ text }),
      });
      resultEl.classList.remove('hidden');
      resultEl.innerHTML = `
        ${hints.phone ? `<p>Phone: <strong>${esc(hints.phone)}</strong></p>` : '<p class="empty">No phone found.</p>'}
        ${hints.address ? `<p>Address: <strong>${esc(hints.address)}</strong></p>` : '<p class="empty">No address found.</p>'}
        ${hints.phone || hints.address ? '<button type="button" class="btn btn-sm btn-primary paste-apply">Apply to new order</button>' : ''}`;

      resultEl.querySelector('.paste-apply')?.addEventListener('click', () => {
        state.prefillPhone = hints.phone || null;
        state.prefillAddress = hints.address || null;
        navigate('new');
      });
    } catch (err) {
      resultEl.classList.remove('hidden');
      resultEl.innerHTML = `<p class="error">${esc(err.message)}</p>`;
    } finally {
      btn.disabled = false;
      btn.textContent = 'Find phone & address';
    }
  });
}

// ── Inbox (Instagram via Meta Graph API) ─────────────

function formatRelativeTime(iso) {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(diff)) return '';
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${Math.max(mins, 1)}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function parseInboxQueryFlags() {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  if (params.get('ig_connected')) {
    history.replaceState(null, '', location.pathname + location.search + '#inbox');
    return { connected: true, error: null };
  }
  const err = params.get('ig_error');
  if (err) {
    history.replaceState(null, '', location.pathname + location.search + '#inbox');
    return { connected: false, error: decodeURIComponent(err) };
  }
  return { connected: false, error: null };
}

async function renderInbox(main) {
  main.innerHTML = '';
  main.appendChild($('#tpl-inbox').content.cloneNode(true));

  const listEl = $('#inbox-list');
  const emptyEl = $('#inbox-empty');
  const filtersEl = $('#inbox-filters');
  const statusText = $('#inbox-status-text');
  const errEl = $('#inbox-error');
  const connectBtn = $('#inbox-connect-btn');
  const disconnectBtn = $('#inbox-disconnect-btn');
  const flags = parseInboxQueryFlags();
  let inboxData = null;

  const GROUP_META = {
    new: { label: 'New message', hint: 'Needs your reply' },
    pending: { label: 'Pending', hint: 'Replied — waiting to confirm order' },
    replied: { label: 'Replied', hint: 'Done or confirmed' },
  };

  if (flags.error) {
    errEl.textContent = flags.error;
    errEl.classList.remove('hidden');
  }

  setupPasteExtract();

  connectBtn?.addEventListener('click', () => {
    window.location.href = '/api/instagram/auth';
  });

  disconnectBtn?.addEventListener('click', async () => {
    await api('/api/instagram/disconnect', { method: 'POST' });
    await load();
  });

  async function patchThread(id, body) {
    await api(`/api/inbox/${encodeURIComponent(id)}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
    await load();
  }

  function threadCard(t, labels) {
    const el = document.createElement('article');
    el.className = `inbox-thread${t.replied ? ' replied' : ''}`;
    const statusTag = t.group === 'new'
      ? '<span class="tag new-msg">New message</span>'
      : t.group === 'pending'
        ? '<span class="tag label">Pending</span>'
        : '<span class="tag replied">Replied</span>';

    el.innerHTML = `
      <div class="inbox-thread-top">
        <p class="inbox-handle">@${esc(t.ig_handle)} · ${esc(t.display_name || t.ig_handle)}</p>
        <span class="inbox-time">${formatRelativeTime(t.updated_at)}</span>
      </div>
      <p class="inbox-preview">${esc(t.preview || '(No message preview)')}</p>
      <div class="inbox-tags">
        ${statusTag}
        ${t.label ? `<span class="tag label">${esc(t.label)}</span>` : ''}
      </div>
      <div class="inbox-label-row">
        <select class="inbox-label-select" aria-label="Label">
          <option value="">— Label —</option>
          ${labels.map((l) => `<option value="${esc(l)}"${t.label === l ? ' selected' : ''}>${esc(l)}</option>`).join('')}
        </select>
      </div>
      <div class="inbox-actions">
        <button type="button" class="btn btn-ghost inbox-reply">${t.replied ? 'Mark unread' : 'Mark replied'}</button>
        <a class="btn btn-ghost" href="https://ig.me/m/${encodeURIComponent(t.ig_handle)}" target="_blank" rel="noopener">Open IG</a>
        <button type="button" class="btn btn-primary inbox-order">Add order</button>
      </div>
      <div class="inbox-link-row">
        <input type="text" class="inbox-order-id" placeholder="Order ID to link" value="${esc(t.linked_order_id || '')}">
        <button type="button" class="btn btn-ghost inbox-link-btn">Link</button>
        <button type="button" class="btn btn-ghost inbox-extract-btn"${t.linked_order_id ? '' : ' disabled'}>Extract from chat</button>
      </div>
      <div class="inbox-extract-result hidden"></div>`;

    el.querySelector('.inbox-label-select')?.addEventListener('change', (e) => {
      patchThread(t.id, { label: e.target.value || null });
    });

    el.querySelector('.inbox-reply')?.addEventListener('click', () => {
      patchThread(t.id, { replied: !t.replied });
    });

    el.querySelector('.inbox-order')?.addEventListener('click', () => {
      state.prefillName = t.display_name || t.ig_handle;
      if (t.preview) state.prefillNote = t.preview;
      navigate('new');
    });

    const orderIdInput = el.querySelector('.inbox-order-id');
    const extractBtn = el.querySelector('.inbox-extract-btn');

    el.querySelector('.inbox-link-btn')?.addEventListener('click', () => {
      patchThread(t.id, { linked_order_id: orderIdInput.value.trim() || null });
    });

    extractBtn?.addEventListener('click', async () => {
      const resultEl = el.querySelector('.inbox-extract-result');
      const linkedOrderId = orderIdInput.value.trim();
      extractBtn.disabled = true;
      extractBtn.textContent = 'Extracting…';
      try {
        const q = linkedOrderId ? `?linked_order_id=${encodeURIComponent(linkedOrderId)}` : '';
        const hints = await api(`/api/inbox/${encodeURIComponent(t.id)}/extract${q}`);
        resultEl.classList.remove('hidden');
        resultEl.innerHTML = `
          ${hints.phone ? `<p>Phone: <strong>${esc(hints.phone)}</strong> <button type="button" class="btn btn-sm btn-ghost apply-phone">Apply</button></p>` : '<p class="empty">No phone found.</p>'}
          ${hints.address ? `<p>Address: <strong>${esc(hints.address)}</strong> <button type="button" class="btn btn-sm btn-ghost apply-address">Apply</button></p>` : '<p class="empty">No address found.</p>'}
          <p class="empty">${hints.evidence_saved.length ? `${hints.evidence_saved.length} slip image(s) saved as evidence.` : hints.image_urls.length ? `${hints.image_urls.length} image(s) found — link an order first to save them.` : 'No images found.'}</p>`;

        resultEl.querySelector('.apply-phone')?.addEventListener('click', async () => {
          if (!linkedOrderId) return;
          await api(`/api/orders/${linkedOrderId}`, { method: 'PATCH', body: JSON.stringify({ phone: hints.phone }) });
        });
        resultEl.querySelector('.apply-address')?.addEventListener('click', async () => {
          if (!linkedOrderId) return;
          await api(`/api/orders/${linkedOrderId}`, { method: 'PATCH', body: JSON.stringify({ address: hints.address }) });
        });
      } catch (err) {
        resultEl.classList.remove('hidden');
        resultEl.innerHTML = `<p class="error">${esc(err.message)}</p>`;
      } finally {
        extractBtn.disabled = false;
        extractBtn.textContent = 'Extract from chat';
      }
    });

    return el;
  }

  function renderFilters(counts) {
    filtersEl.innerHTML = '';
    filtersEl.classList.remove('hidden');
    for (const g of state.inboxGroups) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = `inbox-filter${state.inboxFilter === g.id ? ' active' : ''}`;
      const n = counts[g.id] ?? 0;
      btn.textContent = n ? `${g.label} (${n})` : g.label;
      btn.addEventListener('click', () => {
        state.inboxFilter = g.id;
        paint(inboxData);
      });
      filtersEl.appendChild(btn);
    }
  }

  function paint(data) {
    inboxData = data;
    const labels = data.status?.labels || state.inboxLabels;
    const groups = data.groups || {};
    const counts = data.counts || {};
    listEl.innerHTML = '';
    renderFilters(counts);

    const filter = state.inboxFilter;
    const sections = filter === 'all'
      ? ['new', 'pending', 'replied']
      : [filter];

    let totalShown = 0;
    for (const key of sections) {
      const items = groups[key] || [];
      if (!items.length) continue;
      totalShown += items.length;

      const section = document.createElement('div');
      section.className = 'inbox-group';
      const meta = GROUP_META[key];
      section.innerHTML = `
        <div class="inbox-group-header">
          <span class="inbox-group-badge ${key}">${meta.label}</span>
          <span class="inbox-group-meta">${items.length} · ${meta.hint}</span>
        </div>`;
      const wrap = document.createElement('div');
      wrap.className = 'inbox-list';
      items.forEach((t) => wrap.appendChild(threadCard(t, labels)));
      section.appendChild(wrap);
      listEl.appendChild(section);
    }

    if (!totalShown) {
      emptyEl.classList.remove('hidden');
      emptyEl.textContent = filter === 'all'
        ? 'No Instagram messages yet.'
        : `No ${state.inboxGroups.find((g) => g.id === filter)?.label?.toLowerCase() || filter} messages.`;
    } else {
      emptyEl.classList.add('hidden');
    }
  }

  async function load() {
    listEl.innerHTML = '<p class="empty">Loading…</p>';
    filtersEl.classList.add('hidden');
    emptyEl.classList.add('hidden');
    errEl?.classList.add('hidden');

    try {
      const data = await api('/api/inbox');
      const st = data.status || {};
      const connected = data.connected;

      if (connected) {
        const account = st.ig_username ? `@${st.ig_username}` : 'Instagram';
        statusText.textContent = `Connected to ${account}. Group: New → Pending → Replied.`;
        connectBtn?.classList.add('hidden');
        disconnectBtn?.classList.remove('hidden');
      } else {
        statusText.textContent = st.oauth_available
          ? 'Connect your Instagram business account to sync DMs.'
          : 'Set META_APP_ID, META_APP_SECRET, and META_REDIRECT_URI to enable Instagram sync.';
        connectBtn?.classList.toggle('hidden', !st.oauth_available);
        disconnectBtn?.classList.add('hidden');
        listEl.innerHTML = '';
        emptyEl.classList.remove('hidden');
        emptyEl.textContent = 'Connect Instagram to load your inbox.';
        return;
      }

      if (flags.connected) {
        errEl.textContent = 'Instagram connected successfully.';
        errEl.style.color = 'var(--success)';
        errEl.classList.remove('hidden');
      }

      paint(data);
    } catch (err) {
      listEl.innerHTML = `<p class="error">${esc(err.message)}</p>`;
    }
  }

  await load();
}

boot();

// Enable iPhone frame only on desktop-width viewports (real phones use full screen).
(function initDevicePreview() {
  const mq = window.matchMedia('(min-width: 430px)');
  const apply = () => document.documentElement.classList.toggle('device-preview', mq.matches);
  apply();
  mq.addEventListener('change', apply);
})();
