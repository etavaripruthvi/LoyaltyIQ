/* Shared helpers: API client, formatting, charts, modal, toast, cart, product cards. */
(function () {
  const LQ = (window.LQ = { state: { me: null, cart: {}, products: {}, quote: null }, actions: {}, changes: {}, inputs: {}, views: {} });

  LQ.$ = (s, r) => (r || document).querySelector(s);
  LQ.esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  LQ.num = (n) => Math.round(Number(n) || 0).toLocaleString('en-IN');
  LQ.inr = (n) => '₹' + LQ.num(n);
  LQ.pct = (x) => Math.round((Number(x) || 0) * 100) + '%';
  const parseTs = (s) => new Date(String(s).replace(' ', 'T') + 'Z');
  LQ.date = (s) => (s ? parseTs(s).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : '');
  LQ.datetime = (s) => (s ? parseTs(s).toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '');
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  LQ.month = (ym) => MONTHS[parseInt(ym.slice(5, 7), 10) - 1];

  LQ.api = async function (path, opts) {
    opts = opts || {};
    const init = { method: opts.method || 'GET', headers: {}, credentials: 'same-origin' };
    if (opts.body !== undefined) { init.method = opts.method || 'POST'; init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
    let res;
    try { res = await fetch('/api' + path, init); } catch (e) { throw new Error('Cannot reach the server. Is it running?'); }
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty body */ }
    if (res.status === 401 && path !== '/login') { LQ.state.me = null; location.hash = '#/login'; throw new Error('Please log in'); }
    if (!res.ok) throw new Error((data && data.error) || 'Request failed (' + res.status + ')');
    return data;
  };

  // ----- toast and modal -----
  LQ.toast = function (msg, kind) {
    const el = document.createElement('div');
    el.className = 'toast ' + (kind || '');
    el.textContent = msg;
    LQ.$('#toasts').appendChild(el);
    setTimeout(() => el.remove(), kind === 'bad' ? 5200 : 3200);
  };
  LQ.fail = (e) => LQ.toast(e.message || String(e), 'bad');
  LQ.modal = function (html, wide) {
    const m = LQ.$('#modal');
    m.innerHTML = '<div class="modal' + (wide ? ' wide' : '') + '" role="dialog" aria-modal="true">' + html + '</div>';
    m.hidden = false;
  };
  LQ.closeModal = () => { const m = LQ.$('#modal'); m.hidden = true; m.innerHTML = ''; };
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') LQ.closeModal(); });
  document.addEventListener('mousedown', (e) => { if (e.target.id === 'modal') LQ.closeModal(); });

  // ----- event delegation: data-act, data-change, data-input -----
  document.addEventListener('click', (e) => {
    const el = e.target.closest('[data-act]');
    if (!el) return;
    const fn = LQ.actions[el.dataset.act];
    if (fn) { e.preventDefault(); Promise.resolve(fn(el, e)).catch(LQ.fail); }
  });
  document.addEventListener('change', (e) => {
    const el = e.target.closest('[data-change]');
    if (el && LQ.changes[el.dataset.change]) Promise.resolve(LQ.changes[el.dataset.change](el, e)).catch(LQ.fail);
  });
  document.addEventListener('input', (e) => {
    const el = e.target.closest('[data-input]');
    if (el && LQ.inputs[el.dataset.input]) LQ.inputs[el.dataset.input](el, e);
  });
  LQ.debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

  // ----- small components -----
  LQ.tier = (name) => '<span class="tier tier-' + LQ.esc(String(name || '').toLowerCase()) + '">' + LQ.esc(name) + '</span>';
  LQ.chip = (t, kind) => '<span class="chip ' + (kind || '') + '">' + LQ.esc(t) + '</span>';
  LQ.progress = (p) => '<div class="progress"><i style="width:' + Math.round(Math.max(0, Math.min(1, p)) * 100) + '%"></i></div>';
  LQ.statusChip = (s) => LQ.chip(s, { delivered: 'good', placed: 'brand', cancelled: 'bad', returned: 'warn', approved: 'good', pending: 'warn', rejected: 'bad' }[s]);
  LQ.pointsStatus = (s) => ({ approved: LQ.chip('Points approved', 'good'), pending: LQ.chip('Awaiting approval', 'warn'), rejected: LQ.chip('Points rejected', 'bad') }[s] || '');
  LQ.loading = () => '<div class="spinner">Loading…</div>';
  LQ.pagerHtml = (page, pages, act) => pages <= 1 ? '' :
    '<div class="pager"><button class="btn sm" data-act="' + act + '" data-page="' + (page - 1) + '"' + (page <= 1 ? ' disabled' : '') + '>← Prev</button><span class="small muted">Page ' + page + ' of ' + pages +
    '</span><button class="btn sm" data-act="' + act + '" data-page="' + (page + 1) + '"' + (page >= pages ? ' disabled' : '') + '>Next →</button></div>';

  LQ.barChart = function (rows, o) {
    if (!rows.length) return '<div class="empty">No data yet</div>';
    const W = 600, H = o.h || 150, pad = 8, bw = (W - pad * 2) / rows.length, max = Math.max(1, ...rows.map((r) => r[o.y]));
    let s = '<svg class="bars" viewBox="0 0 ' + W + ' ' + (H + 26) + '" width="100%" role="img" aria-label="' + LQ.esc(o.title || 'bar chart') + '">';
    rows.forEach((r, i) => {
      const h = Math.max(r[o.y] > 0 ? 2 : 0, (r[o.y] / max) * (H - 18)), x = pad + i * bw + bw * 0.14, w = bw * 0.72;
      s += '<g><title>' + LQ.esc(o.label(r)) + ': ' + (o.fmt || LQ.num)(r[o.y]) + '</title><rect class="b" x="' + x.toFixed(1) + '" y="' + (H - h).toFixed(1) + '" width="' + w.toFixed(1) + '" height="' + h.toFixed(1) + '" rx="3"/>' +
        '<text x="' + (x + w / 2).toFixed(1) + '" y="' + (H + 14) + '" text-anchor="middle">' + LQ.esc(o.label(r)) + '</text></g>';
    });
    return s + '</svg>';
  };
  LQ.hbars = function (rows, o) {
    if (!rows.length) return '<div class="empty">No data yet</div>';
    const max = Math.max(1, ...rows.map((r) => r[o.value]));
    return rows.map((r) => '<div class="hbar"><span class="nm" title="' + LQ.esc(o.label(r)) + '">' + LQ.esc(o.label(r)) + '</span><div class="track"><i style="width:' +
      (r[o.value] / max * 100).toFixed(1) + '%;background:' + (o.color ? o.color(r) : 'var(--brand)') + '"></i></div><span class="right small">' + (o.fmt || LQ.num)(r[o.value]) + '</span></div>').join('');
  };
  LQ.delta = (cur, prev) => {
    if (!prev) return '';
    const d = (cur - prev) / prev * 100;
    return '<span class="delta ' + (d >= 0 ? 'up' : 'down') + '">' + (d >= 0 ? '▲ ' : '▼ ') + Math.abs(d).toFixed(0) + '%</span>';
  };

  // ----- cart (kept per user in localStorage, best effort) -----
  const key = () => 'lq_cart_' + (LQ.state.me ? LQ.state.me.username : 'x');
  LQ.loadCart = () => { try { LQ.state.cart = JSON.parse(localStorage.getItem(key()) || '{}'); } catch (e) { LQ.state.cart = {}; } };
  LQ.saveCart = () => { try { localStorage.setItem(key(), JSON.stringify(LQ.state.cart)); } catch (e) { /* private mode */ } LQ.updateCartBadge(); };
  LQ.cartCount = () => Object.values(LQ.state.cart).reduce((a, l) => a + l.qty, 0);
  LQ.updateCartBadge = () => { const b = LQ.$('#cartCount'); if (b) { b.textContent = LQ.cartCount(); b.hidden = !LQ.cartCount(); } };
  LQ.register = (list) => list.forEach((p) => { LQ.state.products[p.id] = Object.assign(LQ.state.products[p.id] || {}, p); });
  LQ.addToCart = function (id, qty) {
    const p = LQ.state.products[id];
    if (!p) return;
    const line = LQ.state.cart[id] || { id: id, name: p.name, emoji: p.emoji, unit: p.unit, price: p.price, mrp: p.mrp, qty: 0, stock: p.stock };
    if (p.stock != null && p.stock <= line.qty) { LQ.toast('No more stock available for ' + p.name, 'bad'); return; }
    line.qty += qty || 1;
    line.price = p.price; line.stock = p.stock != null ? p.stock : line.stock;
    LQ.state.cart[id] = line;
    LQ.saveCart();
    LQ.toast('Added ' + p.name + ' to your cart');
  };

  LQ.CAT_COLOR = {};
  LQ.productCard = function (p, opts) {
    opts = opts || {};
    const out = p.stock != null && p.stock <= 0;
    const color = p.color || LQ.CAT_COLOR[p.category] || '#eef0ff';
    const disc = p.discount_pct || 0;
    const badges = (p.badges || []).filter((b) => !/off$/.test(b));
    return '<div class="pcard"><div class="thumb" style="background:' + color + '">' + LQ.esc(p.emoji) +
      (disc ? '<span class="tag">' + disc + '% off</span>' : '') + (badges.length ? '<span class="tag2">' + LQ.esc(badges[0]) + '</span>' : '') + '</div>' +
      '<div class="pbody"><div class="pname">' + LQ.esc(p.name) + '</div><div class="punit">' + LQ.esc(p.unit) + (p.rating ? ' · ★ ' + p.rating : '') + '</div>' +
      '<div><span class="price">' + LQ.inr(p.price) + '</span>' + (p.mrp > p.price ? '<span class="mrp">' + LQ.inr(p.mrp) + '</span>' : '') + '</div>' +
      (p.low_stock ? '<div class="xs" style="color:var(--bad)">Only ' + p.stock + ' left</div>' : '') +
      (opts.reason && p.reason ? '<div class="why">' + LQ.esc(p.reason) + '</div>' : '') +
      '<button class="btn sm primary" data-act="add" data-id="' + p.id + '"' + (out ? ' disabled' : '') + '>' + (out ? 'Out of stock' : 'Add to cart') + '</button></div></div>';
  };
  LQ.mini = (p) => '<div class="mini"><div class="t" style="background:' + (LQ.CAT_COLOR[p.category] || '#eef0ff') + '">' + LQ.esc(p.emoji) + '</div><div class="grow"><div class="n">' + LQ.esc(p.name) +
    '</div><div class="xs muted">' + LQ.esc(p.unit) + ' · <b>' + LQ.inr(p.price) + '</b></div></div><button class="btn sm" data-act="add" data-id="' + p.id + '" aria-label="Add ' + LQ.esc(p.name) + '">+</button></div>';

  LQ.actions.add = (el) => LQ.addToCart(Number(el.dataset.id), 1);
  // Links that also close the modal (View orders, Customer #N) must still navigate: the global handler stops the default click.
  LQ.actions.closeModal = (el) => { LQ.closeModal(); const h = el && el.tagName === 'A' && el.getAttribute('href'); if (h && h.charAt(0) === '#') location.hash = h; };
})();
