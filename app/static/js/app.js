/** Maguro frontend — vanilla JS SPA */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = {
  config: null,
  orderDates: [],
  route: 'orders',
  editingId: null,
  prefillDate: null,
  bangkokToday: '',
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

  $$('.nav-item').forEach((el) => {
    el.classList.toggle('active', el.dataset.route === route || (route === 'form' && el.dataset.route === 'new'));
  });

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
  `;
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
  state.prefillDate = null;
  form.fulfillment.value = 'Delivery';
  form.delivery_time.value = state.config.rounds[0];
  form.status.value = 'Open';

  if (isEdit) {
    try {
      const order = await api(`/api/orders/${state.editingId}`);
      form.name.value = order.name;
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
  }

  $('#form-cancel').addEventListener('click', () => navigate('orders'));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    errEl.classList.add('hidden');
    const body = {
      name: form.name.value.trim(),
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

boot();
