/* Admin console: dashboard, approvals, orders, products, customers, rules, AI and personas. */
(function () {
  const LQ = window.LQ, esc = LQ.esc, inr = LQ.inr, num = LQ.num;
  const V = (LQ.views.admin = {});
  const kpi = (label, value, extra, href) => '<div class="card kpi"' + (href ? ' style="cursor:pointer" onclick="location.hash=\'' + href + '\'"' : '') + '><div class="label">' + label + '</div><div class="value">' + value + '</div><div class="small muted">' + (extra || '') + '</div></div>';
  const riskColor = (s) => (s >= 70 ? 'var(--bad)' : s >= 40 ? 'var(--gold)' : 'var(--good)');
  const risk = (s) => '<span class="riskbar"><i style="width:' + s + '%;background:' + riskColor(s) + '"></i></span><b class="small">' + s + '</b>';
  const sugg = (s) => LQ.chip({ approve: 'Suggest: approve', review: 'Suggest: review', hold: 'Suggest: hold' }[s], { approve: 'good', review: 'warn', hold: 'bad' }[s]);

  // ================= DASHBOARD =================
  V.dashboard = async function (root) {
    root.innerHTML = LQ.loading();
    const o = await LQ.api('/admin/overview');
    const ag = o.agent;
    root.innerHTML = '<div class="page-head"><div><h1>Dashboard</h1><p>Store performance, loyalty health and what the AI agent recommends you act on</p></div>' +
      '<button class="btn" data-act="runExpiry">Run points expiry</button></div>' +
      '<div class="grid g4">' +
      kpi('Revenue · 30 days', inr(o.revenue_30d) + ' ' + LQ.delta(o.revenue_30d, o.revenue_prev_30d), 'vs previous 30 days') +
      kpi('Orders · 30 days', num(o.orders_30d) + ' ' + LQ.delta(o.orders_30d, o.orders_prev_30d), num(o.active_buyers_30d) + ' active buyers · avg ' + inr(o.aov_30d)) +
      kpi('Pending approvals', num(o.pending_approvals), num(o.pending_points) + ' points waiting · click to review', '#/admin/approvals') +
      kpi('Points liability', inr(o.points.liability_rs), num(o.points.active_points) + ' active · ' + num(o.points.expiring_30d_points) + ' expiring in 30d') + '</div>' +
      '<div class="grid g4 mt">' +
      kpi('Customers', num(o.customers), o.tier_distribution.map((t) => t.tier[0] + ':' + t.count).join(' · '), '#/admin/customers') +
      kpi('High churn risk', num(o.high_churn_count), inr(o.value_at_risk) + ' yearly value at risk', '#/admin/customers') +
      kpi('Stock alerts', num(o.out_of_stock + o.low_stock), o.out_of_stock + ' out of stock · ' + o.low_stock + ' low', '#/admin/products') +
      kpi('Catalogue', num(o.products), 'products live') + '</div>' +
      '<div class="grid g-side mt"><div class="card"><h3>Revenue by month</h3>' + LQ.barChart(o.revenue_by_month, { y: 'revenue', label: (r) => LQ.month(r.ym), fmt: inr, title: 'Revenue by month' }) + '</div>' +
      '<div class="card"><h3>Revenue by category · 30 days</h3>' + LQ.hbars(o.revenue_by_category.slice(0, 8), { label: (r) => r.emoji + ' ' + r.name, value: 'revenue', fmt: inr }) + '</div></div>' +
      '<div class="grid g3 mt"><div class="card"><h3>Loyalty tiers</h3>' + LQ.hbars(o.tier_distribution, { label: (r) => r.tier, value: 'count', color: (r) => ({ Bronze: 'var(--bronze)', Silver: 'var(--silver)', Gold: 'var(--gold)', Platinum: 'var(--platinum)' }[r.tier] || 'var(--brand)') }) + '</div>' +
      '<div class="card"><h3>Behaviour segments</h3>' + LQ.hbars(o.segments, { label: (r) => r.segment, value: 'count' }) + '</div>' +
      '<div class="card"><h3>Top products · 30 days</h3>' + o.top_products.map((p) => '<div class="row between small" style="padding:5px 0"><span>' + esc(p.emoji) + ' ' + esc(p.name) + '</span><b>' + inr(p.revenue) + '</b></div>').join('') + '</div></div>' +
      '<h2 class="mt2">🤖 Agent portfolio: who to act on</h2><div class="grid g3">' +
      '<div class="card"><h3>Win-back candidates <span class="chip bad">' + ag.win_back.count + '</span></h3><p class="xs muted mb">Highest churn risk × yearly value</p>' + (ag.win_back.top.length ? ag.win_back.top.map((c) =>
        '<div class="row between small" style="padding:5px 0;cursor:pointer" onclick="location.hash=\'#/admin/customers/' + c.customer_id + '\'"><span>' + esc(c.name) + ' <span class="muted xs">' + c.recency_days + 'd quiet</span></span><span>' + LQ.pct(c.churn_risk) + ' · ' + inr(c.clv_12m) + '</span></div>').join('') : '<div class="empty">None</div>') + '</div>' +
      '<div class="card"><h3>Close to next tier <span class="chip good">' + ag.upgrade_candidates.count + '</span></h3><p class="xs muted mb">Small nudge, big loyalty gain</p>' + ag.upgrade_candidates.top.map((c) =>
        '<div class="row between small" style="padding:5px 0;cursor:pointer" onclick="location.hash=\'#/admin/customers/' + c.customer_id + '\'"><span>' + esc(c.name) + ' ' + LQ.tier(c.tier) + '</span><span>' + inr(c.gap) + ' to ' + esc(c.next_tier) + '</span></div>').join('') + '</div>' +
      '<div class="card"><h3>Points expiring in 30 days</h3><p class="xs muted mb">Offer budget used: ' + inr(ag.offer_budget.committed) + ' of ' + inr(ag.offer_budget.budget) + ' (' + ag.offer_budget.offers_issued + ' offers, ' + ag.offer_budget.offers_used + ' used)</p>' +
      LQ.progress(ag.offer_budget.committed / Math.max(1, ag.offer_budget.budget)) + '<div class="mt">' + ag.expiring.map((c) => '<div class="row between small" style="padding:5px 0;cursor:pointer" onclick="location.hash=\'#/admin/customers/' + c.customer_id + '\'"><span>' + esc(c.name) + '</span><b>' + num(c.points) + ' pts</b></div>').join('') + '</div></div></div>';
  };
  LQ.actions.runExpiry = async () => { const r = await LQ.api('/admin/run-expiry', { method: 'POST' }); LQ.toast(r.expired_batches + ' expired batches processed', 'good'); V.dashboard(LQ.$('#view')); };

  // ================= APPROVALS =================
  const appr = { tab: 'pending', sel: new Set() };
  V.approvals = async function (root) {
    root.innerHTML = LQ.loading();
    const d = await LQ.api('/admin/approvals' + (appr.tab === 'history' ? '?status=history' : ''));
    appr.items = d.items; appr.sel = new Set();
    const modeTxt = d.mode === 'all' ? 'Every order waits here for approval.' : 'Only large orders (≥ ' + inr(d.threshold) + ') or risky ones (score ≥ ' + d.risk_threshold + ') wait here. Everything else is auto-approved.';
    root.innerHTML = '<div class="page-head"><div><h1>Points approvals</h1><p>' + modeTxt + ' <a href="#/admin/rules">Change rules</a></p></div>' +
      (appr.tab === 'pending' ? '<div class="row"><button class="btn" data-act="selSafe">Select low-risk</button><button class="btn good" data-act="bulkApprove">Approve selected</button><button class="btn bad" data-act="bulkReject">Reject selected</button></div>' : '') + '</div>' +
      '<div class="tabs"><a class="' + (appr.tab === 'pending' ? 'on' : '') + '" data-act="apprTab" data-tab="pending">Pending</a><a class="' + (appr.tab === 'history' ? 'on' : '') + '" data-act="apprTab" data-tab="history">Decided</a></div>' +
      (d.items.length ? '<div class="card"><div class="tablewrap"><table><thead><tr>' + (appr.tab === 'pending' ? '<th></th>' : '') + '<th>Order</th><th>Customer</th><th class="right">Value</th><th class="right">Points</th><th>Risk</th><th>Why it was flagged</th><th></th></tr></thead><tbody>' +
        d.items.map((o) => '<tr>' + (appr.tab === 'pending' ? '<td><input type="checkbox" data-change="selRow" data-id="' + o.id + '" aria-label="Select order ' + o.id + '"></td>' : '') +
          '<td><b>#' + o.id + '</b><div class="xs muted">' + LQ.datetime(o.created_at) + '</div><div class="xs">' + o.items.map((i) => esc(i.emoji) + '×' + i.qty).join(' ') + '</div></td>' +
          '<td><a href="#/admin/customers/' + o.customer_id + '">' + esc(o.customer) + '</a><div>' + LQ.tier(o.tier) + '</div></td><td class="right">' + inr(o.total_paid) + (o.points_redeemed ? '<div class="xs muted">used ' + o.points_redeemed + ' pts</div>' : '') + '</td>' +
          '<td class="right"><b>' + num(o.points_earned) + '</b></td><td class="nowrap">' + risk(o.risk_score) + '<div>' + (appr.tab === 'pending' ? sugg(o.suggestion) : LQ.pointsStatus(o.points_status)) + '</div></td>' +
          '<td>' + (o.flags.length ? o.flags.map((f) => '<span class="flag">⚠ ' + esc(f.text) + '</span>').join('') : '<span class="xs muted">No risk flags (approval mode is "all")</span>') + (appr.tab === 'history' ? '<div class="xs muted">' + esc(o.reviewed_by || '') + ': ' + esc(o.review_note || '') + '</div>' : '') + '</td>' +
          '<td class="nowrap">' + (appr.tab === 'pending' ? '<button class="btn sm good" data-act="approve" data-id="' + o.id + '">Approve</button> <button class="btn sm" data-act="adjust" data-id="' + o.id + '">Adjust</button> <button class="btn sm bad" data-act="reject" data-id="' + o.id + '">Reject</button>' : '') + '</td></tr>').join('') +
        '</tbody></table></div></div>' : '<div class="empty card">🎉 Nothing waiting. All caught up.</div>');
  };
  LQ.actions.apprTab = (el) => { appr.tab = el.dataset.tab; V.approvals(LQ.$('#view')); };
  LQ.changes.selRow = (el) => { el.checked ? appr.sel.add(Number(el.dataset.id)) : appr.sel.delete(Number(el.dataset.id)); };
  LQ.actions.selSafe = () => document.querySelectorAll('[data-change=selRow]').forEach((c) => { const o = appr.items.find((x) => x.id == c.dataset.id); c.checked = o.suggestion !== 'hold'; c.checked ? appr.sel.add(o.id) : appr.sel.delete(o.id); });
  async function decide(id, body) { await LQ.api('/admin/approvals/' + id, { body }); LQ.toast('Saved', 'good'); LQ.refreshBadges(); V.approvals(LQ.$('#view')); }
  LQ.actions.approve = (el) => decide(el.dataset.id, { action: 'approve' });
  LQ.actions.reject = (el) => LQ.modal('<h2>Reject points for order #' + el.dataset.id + '</h2><p class="small muted mb">The customer keeps the order but earns no points. Add a reason for the audit log.</p>' +
    '<div class="form-row"><label class="f">Reason</label><input type="text" id="rejNote" placeholder="e.g. Suspected resale"></div><div class="row"><button class="btn bad" data-act="rejectGo" data-id="' + el.dataset.id + '">Reject points</button><button class="btn" data-act="closeModal">Cancel</button></div>');
  LQ.actions.rejectGo = async (el) => { const n = LQ.$('#rejNote').value; LQ.closeModal(); await decide(el.dataset.id, { action: 'reject', note: n }); };
  LQ.actions.adjust = (el) => { const o = appr.items.find((x) => x.id == el.dataset.id); LQ.modal('<h2>Adjust and approve order #' + o.id + '</h2><p class="small muted mb">Calculated: ' + o.points_earned + ' points. Enter the number to credit.</p>' +
    '<div class="form-row"><label class="f">Points to credit</label><input type="number" id="adjPts" min="0" value="' + o.points_earned + '"></div><div class="form-row"><label class="f">Note</label><input type="text" id="adjNote" placeholder="Why the change?"></div>' +
    '<div class="row"><button class="btn good" data-act="adjustGo" data-id="' + o.id + '">Approve with this amount</button><button class="btn" data-act="closeModal">Cancel</button></div>'); };
  LQ.actions.adjustGo = async (el) => { const p = LQ.$('#adjPts').value, n = LQ.$('#adjNote').value; LQ.closeModal(); await decide(el.dataset.id, { action: 'approve', points: Number(p), note: n }); };
  async function bulk(action) {
    if (!appr.sel.size) { LQ.toast('Select at least one order first', 'bad'); return; }
    const r = await LQ.api('/admin/approvals/bulk', { body: { order_ids: [...appr.sel], action, note: 'Bulk ' + action } });
    LQ.toast(r.done + ' ' + action + 'd' + (r.failed ? ', ' + r.failed + ' skipped' : ''), 'good'); LQ.refreshBadges(); V.approvals(LQ.$('#view'));
  }
  LQ.actions.bulkApprove = () => bulk('approve');
  LQ.actions.bulkReject = () => { if (confirm('Reject points for all selected orders?')) return bulk('reject'); };

  // ================= ORDERS =================
  const ord = { status: '', q: '', page: 1 };
  V.orders = async function (root) {
    root.innerHTML = '<div class="page-head"><div><h1>Orders</h1><p>All customer orders</p></div></div><div class="card flat mb"><div class="row"><select class="inline" data-change="ordStatus" aria-label="Status filter"><option value="">All statuses</option>' +
      ['placed', 'delivered', 'cancelled', 'returned'].map((s) => '<option' + (ord.status === s ? ' selected' : '') + '>' + s + '</option>').join('') + '</select><input type="search" class="grow" style="min-width:200px" placeholder="Search by customer name or order number" value="' + esc(ord.q) + '" data-input="ordSearch"></div></div><div id="ordBox">' + LQ.loading() + '</div>';
    loadOrders();
  };
  async function loadOrders() {
    const d = await LQ.api('/admin/orders?' + new URLSearchParams({ status: ord.status, q: ord.q, page: ord.page }));
    LQ.$('#ordBox').innerHTML = '<div class="card"><div class="tablewrap"><table><thead><tr><th>Order</th><th>Customer</th><th>Date</th><th class="right">Total</th><th>Status</th><th>Points</th><th>Risk</th></tr></thead><tbody>' +
      d.items.map((o) => '<tr class="click" data-act="orderDetail" data-id="' + o.id + '"><td><b>#' + o.id + '</b></td><td>' + esc(o.customer) + '</td><td class="small">' + LQ.datetime(o.created_at) + '</td><td class="right">' + inr(o.total_paid) + '</td><td>' + LQ.statusChip(o.status) + '</td><td>' + num(o.points_earned) + ' ' + LQ.pointsStatus(o.points_status) + '</td><td>' + risk(o.risk_score) + '</td></tr>').join('') +
      '</tbody></table></div></div>' + LQ.pagerHtml(d.page, d.pages, 'ordPage');
  }
  LQ.changes.ordStatus = (el) => { ord.status = el.value; ord.page = 1; loadOrders(); };
  LQ.inputs.ordSearch = LQ.debounce((el) => { ord.q = el.value; ord.page = 1; loadOrders().catch(LQ.fail); }, 300);
  LQ.actions.ordPage = (el) => { ord.page = Number(el.dataset.page); loadOrders(); };
  LQ.actions.orderDetail = async (el) => {
    const o = await LQ.api('/admin/orders/' + el.dataset.id);
    LQ.modal('<div class="row between"><h2>Order #' + o.id + '</h2><div class="row">' + LQ.statusChip(o.status) + LQ.pointsStatus(o.points_status) + '</div></div><p class="small muted">' + LQ.datetime(o.created_at) + ' · <a href="#/admin/customers/' + o.customer_id + '" data-act="closeModal">Customer #' + o.customer_id + '</a></p>' +
      '<div class="tablewrap mt"><table><tbody>' + o.items.map((i) => '<tr><td>' + esc(i.emoji) + ' ' + esc(i.name) + ' <span class="muted">' + esc(i.unit) + '</span></td><td class="right">×' + i.qty + '</td><td class="right">' + inr(i.unit_price * i.qty) + '</td></tr>').join('') + '</tbody></table></div>' +
      '<dl class="kv mt"><dt>Subtotal</dt><dd>' + inr(o.subtotal) + '</dd><dt>Points used</dt><dd>' + o.points_redeemed + ' (' + inr(o.redeem_value) + ')</dd>' + (o.new_account_discount ? '<dt>New-account discount</dt><dd>−' + inr(o.new_account_discount) + '</dd>' : '') + '<dt>Paid</dt><dd>' + inr(o.total_paid) + '</dd><dt>Points earned</dt><dd>' + o.points_earned + (o.new_account_points ? ' (incl. ' + o.new_account_points + ' new-account bonus)' : '') + '</dd><dt>Risk score</dt><dd>' + o.risk_score + '</dd></dl>' +
      (o.flags.length ? '<div class="mt">' + o.flags.map((f) => '<span class="flag">⚠ ' + esc(f.text) + '</span>').join('') + '</div>' : '') +
      '<div class="row mt">' + (o.status === 'placed' ? '<button class="btn good" data-act="setStatus" data-id="' + o.id + '" data-s="delivered">Mark delivered</button><button class="btn bad" data-act="setStatus" data-id="' + o.id + '" data-s="cancelled">Cancel</button>' : '') +
      (o.status === 'delivered' ? '<button class="btn bad" data-act="setStatus" data-id="' + o.id + '" data-s="returned">Mark returned</button>' : '') + '<button class="btn" data-act="closeModal">Close</button></div>', true);
  };
  LQ.actions.setStatus = async (el) => {
    if (el.dataset.s !== 'delivered' && !confirm('Mark order #' + el.dataset.id + ' as ' + el.dataset.s + '? Stock is restored and points are reversed.')) return;
    await LQ.api('/admin/orders/' + el.dataset.id + '/status', { body: { status: el.dataset.s } });
    LQ.closeModal(); LQ.toast('Order ' + el.dataset.s, 'good'); LQ.refreshBadges(); loadOrders();
  };

  // ================= PRODUCTS =================
  const prod = { category: '', stock: '', q: '', page: 1 };
  V.products = async function (root) {
    root.innerHTML = '<div class="page-head"><div><h1>Products and stock</h1><p>Edit prices, offers and inventory. Changes go live in the store immediately.</p></div><div class="row"><button class="btn" data-act="newCategory">+ Add category</button><button class="btn primary" data-act="newProduct">+ Add product</button></div></div>' +
      '<div class="card flat mb"><div class="row"><select class="inline" data-change="prodCat" aria-label="Category"><option value="">All categories</option>' + LQ.state.cats.map((c) => '<option value="' + c.key + '"' + (prod.category === c.key ? ' selected' : '') + '>' + esc(c.name) + '</option>').join('') + '</select>' +
      '<select class="inline" data-change="prodStock" aria-label="Stock filter"><option value="">Any stock</option><option value="low"' + (prod.stock === 'low' ? ' selected' : '') + '>Low stock</option><option value="out"' + (prod.stock === 'out' ? ' selected' : '') + '>Out of stock</option></select>' +
      '<input type="search" class="grow" style="min-width:200px" placeholder="Search name or SKU" value="' + esc(prod.q) + '" data-input="prodSearch"></div></div><div id="prodBox">' + LQ.loading() + '</div>';
    loadProducts();
  };
  async function loadProducts() {
    const d = await LQ.api('/admin/products?' + new URLSearchParams({ category: prod.category, stock: prod.stock, q: prod.q, page: prod.page }));
    LQ.$('#prodBox').innerHTML = '<div class="card"><div class="small muted mb">' + num(d.total) + ' products</div><div class="tablewrap"><table><thead><tr><th>Product</th><th>Price ₹</th><th>MRP ₹</th><th>Cost ₹</th><th>Stock</th><th>Live</th><th></th></tr></thead><tbody>' +
      d.items.map((p) => '<tr data-pid="' + p.id + '"><td><span style="font-size:20px">' + esc(p.emoji) + '</span> <b>' + esc(p.name) + '</b><div class="xs muted">' + esc(p.sku) + ' · ' + esc(p.unit) + ' · ' + esc((LQ.state.cats.find((c) => c.key === p.category) || {}).name) + '</div></td>' +
        '<td><input type="number" style="width:84px" data-f="price" value="' + p.price + '" step="0.01" aria-label="Price"></td><td><input type="number" style="width:84px" data-f="mrp" value="' + p.mrp + '" step="0.01" aria-label="MRP"></td>' +
        '<td><input type="number" style="width:84px" data-f="cost" value="' + p.cost + '" step="0.01" aria-label="Cost"></td><td><input type="number" style="width:76px;' + (p.stock === 0 ? 'border-color:var(--bad)' : p.stock <= p.reorder_level ? 'border-color:var(--gold)' : '') + '" data-f="stock" value="' + p.stock + '" aria-label="Stock"></td>' +
        '<td><input type="checkbox" data-f="active"' + (p.active ? ' checked' : '') + ' aria-label="Live"></td><td class="nowrap"><button class="btn sm primary" data-act="saveProduct" data-id="' + p.id + '">Save</button> <button class="btn sm" data-act="restock" data-id="' + p.id + '">+50</button></td></tr>').join('') +
      '</tbody></table></div></div>' + LQ.pagerHtml(d.page, d.pages, 'prodPage');
  }
  LQ.changes.prodCat = (el) => { prod.category = el.value; prod.page = 1; loadProducts(); };
  LQ.changes.prodStock = (el) => { prod.stock = el.value; prod.page = 1; loadProducts(); };
  LQ.inputs.prodSearch = LQ.debounce((el) => { prod.q = el.value; prod.page = 1; loadProducts().catch(LQ.fail); }, 300);
  LQ.actions.prodPage = (el) => { prod.page = Number(el.dataset.page); loadProducts(); };
  LQ.actions.saveProduct = async (el) => {
    const tr = el.closest('tr'), body = {};
    tr.querySelectorAll('[data-f]').forEach((i) => { body[i.dataset.f] = i.type === 'checkbox' ? i.checked : Number(i.value); });
    await LQ.api('/admin/products/' + el.dataset.id, { method: 'PUT', body }); LQ.toast('Product saved', 'good'); loadProducts();
  };
  LQ.actions.restock = async (el) => { await LQ.api('/admin/products/' + el.dataset.id + '/restock', { body: { qty: 50 } }); LQ.toast('Added 50 units', 'good'); loadProducts(); };
  LQ.actions.newProduct = () => LQ.modal('<h2>Add product</h2><div class="grid g2"><div class="form-row"><label class="f">Name</label><input type="text" id="np_name" placeholder="e.g. House Brand Mango Pickle"></div>' +
    '<div class="form-row"><label class="f">Category</label><select id="np_cat">' + LQ.state.cats.map((c) => '<option value="' + c.key + '">' + esc(c.name) + '</option>').join('') + '</select></div>' +
    '<div class="form-row"><label class="f">Emoji</label><input type="text" id="np_emoji" placeholder="🥭"></div><div class="form-row"><label class="f">Pack size / variant</label><input type="text" id="np_unit" placeholder="500 g"></div>' +
    '<div class="form-row"><label class="f">Selling price ₹</label><input type="number" id="np_price" min="0"></div><div class="form-row"><label class="f">MRP ₹ (optional)</label><input type="number" id="np_mrp" min="0"></div>' +
    '<div class="form-row"><label class="f">Cost ₹ (optional)</label><input type="number" id="np_cost" min="0"></div><div class="form-row"><label class="f">Opening stock</label><input type="number" id="np_stock" min="0" value="50"></div></div>' +
    '<div class="row"><button class="btn primary" data-act="createProduct">Create product</button><button class="btn" data-act="closeModal">Cancel</button></div>');
  LQ.actions.createProduct = async () => {
    const v = (id) => LQ.$('#' + id).value.trim(), body = { name: v('np_name'), category: v('np_cat'), price: Number(v('np_price')), stock: Number(v('np_stock') || 0) };
    if (v('np_emoji')) body.emoji = v('np_emoji'); if (v('np_unit')) body.unit = v('np_unit'); if (v('np_mrp')) body.mrp = Number(v('np_mrp')); if (v('np_cost')) body.cost = Number(v('np_cost'));
    await LQ.api('/admin/products', { body }); LQ.closeModal(); LQ.toast('Product created', 'good'); loadProducts();
  };

  // ================= CUSTOMERS =================
  const cu = { q: '', tier: '', segment: '', sort: 'id', page: 1 };
  LQ.customerFilter = (segment, tier) => { cu.segment = segment || ''; cu.tier = tier || ''; cu.q = ''; cu.page = 1; if (location.hash === '#/admin/customers') V.customers(LQ.$('#view')); else location.hash = '#/admin/customers'; };
  V.customers = async function (root) {
    root.innerHTML = '<div class="page-head"><div><h1>Customers</h1><p>Behaviour segments, churn risk and value, learned from orders</p></div><div class="row"><a class="btn" href="#/admin/segments">View segments</a><button class="btn primary" data-act="newCustomer">+ Add customer</button></div></div><div class="card flat mb"><div class="row"><input type="search" class="grow" style="min-width:200px" placeholder="Search name or user1…" value="' + esc(cu.q) + '" data-input="cuSearch"><select class="inline" data-change="cuTier" id="cuTier" aria-label="Tier"></select><select class="inline" data-change="cuSeg" id="cuSeg" aria-label="Segment"></select>' +
      '<select class="inline" data-change="cuSort" aria-label="Sort">' + [['id', 'Sort: ID'], ['spend', 'Highest spend'], ['churn', 'Highest churn risk'], ['clv', 'Highest value'], ['points', 'Most points'], ['name', 'Name']].map((o) => '<option value="' + o[0] + '"' + (cu.sort === o[0] ? ' selected' : '') + '>' + o[1] + '</option>').join('') + '</select></div></div><div id="cuBox">' + LQ.loading() + '</div>';
    loadCustomers();
  };
  async function loadCustomers() {
    const d = await LQ.api('/admin/customers?' + new URLSearchParams(cu));
    const fill = (id, label, list, cur) => { const s = LQ.$('#' + id); if (s) s.innerHTML = '<option value="">' + label + '</option>' + list.map((x) => '<option' + (x === cur ? ' selected' : '') + '>' + esc(x) + '</option>').join(''); };
    fill('cuTier', 'All tiers', d.tiers, cu.tier); fill('cuSeg', 'All segments', d.segments, cu.segment);
    LQ.$('#cuBox').innerHTML = '<div class="card"><div class="small muted mb">' + num(d.total) + ' customers</div><div class="tablewrap"><table><thead><tr><th>Customer</th><th>Tier</th><th>Segment</th><th class="right">Spend 12m</th><th class="right">Points</th><th>Last order</th><th>Churn risk</th><th class="right">Yearly value</th></tr></thead><tbody>' +
      d.items.map((c) => '<tr class="click" onclick="location.hash=\'#/admin/customers/' + c.id + '\'"><td><b>' + esc(c.name) + '</b> ' + (c.is_showcase ? '<span class="chip brand">' + esc(c.username) + '</span>' : '<span class="xs muted">' + esc(c.username) + '</span>') + '<div class="xs muted">' + esc(c.city) + '</div></td><td>' + LQ.tier(c.tier) + '</td><td>' + LQ.chip(c.segment, { Champion: 'good', Loyal: 'good', 'At risk': 'warn', Hibernating: 'bad', New: 'brand' }[c.segment]) + '</td>' +
        '<td class="right">' + inr(c.spend_12m) + '<div class="xs muted">' + c.orders_12m + ' orders</div></td><td class="right">' + num(c.points) + '</td><td class="small">' + (c.recency_days != null ? c.recency_days + ' days ago' : 'never') + '</td><td>' + (c.churn_risk != null ? risk(Math.round(c.churn_risk * 100)) : '') + '</td><td class="right">' + inr(c.clv_12m) + '</td></tr>').join('') + '</tbody></table></div></div>' + LQ.pagerHtml(d.page, d.pages, 'cuPage');
  }
  LQ.inputs.cuSearch = LQ.debounce((el) => { cu.q = el.value; cu.page = 1; loadCustomers().catch(LQ.fail); }, 300);
  LQ.changes.cuTier = (el) => { cu.tier = el.value; cu.page = 1; loadCustomers(); };
  LQ.changes.cuSeg = (el) => { cu.segment = el.value; cu.page = 1; loadCustomers(); };
  LQ.changes.cuSort = (el) => { cu.sort = el.value; cu.page = 1; loadCustomers(); };
  LQ.actions.cuPage = (el) => { cu.page = Number(el.dataset.page); loadCustomers(); };

  V.customer360 = async function (root, id) {
    root.innerHTML = LQ.loading();
    const d = await LQ.api('/admin/customers/' + id);
    const c = d.customer, a = d.analysis, f = a.features, t = a.tier, p = a.points, nba = a.next_best_action;
    LQ.register(a.recommendations);
    const kind = { earn: 'Order points', bonus: 'Bonus', redeem: 'Redeemed', expire: 'Expired', reverse: 'Reversed', refund: 'Refund' };
    root.innerHTML = '<p class="small"><a href="#/admin/customers">← All customers</a></p><div class="page-head"><div><h1>' + esc(c.name) + ' ' + LQ.tier(t.tier) + '</h1><p>' + esc(c.username) + ' · ' + esc(c.city) + ' · joined ' + LQ.date(c.joined_at) + ' · segment <b>' + esc(f.segment) + '</b></p></div>' +
      '<button class="btn" data-act="editCustomer" data-id="' + c.id + '" data-name="' + esc(c.name) + '" data-city="' + esc(c.city) + '">Edit details</button></div>' +
      '<div class="grid g4">' + kpi('Spend · 12 months', inr(f.spend_12m), f.n_orders + ' orders · avg ' + inr(f.aov)) + kpi('Points', num(p.active), num(p.pending) + ' pending · ' + num(p.expiring_30d) + ' expiring soon') +
      kpi('Churn risk', LQ.pct(f.churn_risk || 0), f.recency_days != null ? 'last order ' + Math.round(f.recency_days) + ' days ago' : 'no orders') + kpi('Yearly value (est.)', inr(f.clv_12m), 'RFM ' + f.rfm.join('-')) + '</div>' +
      '<div class="grid g-side mt"><div><div class="card nba"><span class="chip brand">🤖 Agent next best action · priority ' + nba.priority + '</span><h2 style="margin-top:8px">' + esc(nba.title) + '</h2><p>' + esc(nba.message) + '</p><div class="row" style="margin:8px 0">' + nba.why.map((w) => '<span class="chip">' + esc(w) + '</span>').join('') + '</div>' +
      (nba.offer ? '<div class="notice small">Offer: ' + nba.offer.multiplier + 'x points for ' + nba.offer.days + ' days · estimated cost ' + inr(nba.offer.cost_est) + ' · ' + (nba.offer.allowed ? '<b>within guardrails</b>' : '<b>blocked: ' + esc(nba.offer.blocked_reason) + '</b>') + '</div>' : '') +
      '<p class="xs muted mt">All candidate actions: ' + a.actions.map((x) => esc(x.code) + ' (' + x.priority + ')').join(' · ') + '</p></div>' +
      '<div class="card mt"><h3>Recommendations the customer sees</h3><div class="tablewrap"><table><tbody>' + a.recommendations.map((r) => '<tr><td>' + esc(r.emoji) + ' <b>' + esc(r.name) + '</b> <span class="muted xs">' + esc(r.unit) + '</span></td><td class="right">' + inr(r.price) + '</td><td class="small">' + esc(r.reason) + '</td><td class="xs muted">' + Object.entries(r.signals).sort((x, y) => y[1] - x[1]).slice(0, 3).map((e) => e[0] + ' ' + e[1].toFixed(2)).join(' · ') + '</td></tr>').join('') + '</tbody></table></div></div>' +
      '<div class="card mt"><h3>Recent orders</h3><div class="tablewrap"><table><tbody>' + d.orders.map((o) => '<tr class="click" data-act="orderDetail" data-id="' + o.id + '"><td><b>#' + o.id + '</b></td><td class="small">' + LQ.date(o.created_at) + '</td><td class="small">' + o.items.slice(0, 3).map((i) => esc(i.emoji)).join(' ') + (o.items.length > 3 ? ' +' + (o.items.length - 3) : '') + '</td><td class="right">' + inr(o.total_paid) + '</td><td>' + LQ.statusChip(o.status) + '</td><td>' + num(o.points_earned) + ' ' + LQ.pointsStatus(o.points_status) + '</td></tr>').join('') + '</tbody></table></div></div></div>' +
      '<div class="grid" style="align-content:start"><div class="card"><h3>Behaviour learned</h3><div class="row mb">' + a.traits.map((x) => '<span class="chip brand" title="' + esc(x.detail) + '">' + esc(x.label) + '</span>').join('') + '</div>' +
      '<dl class="kv"><dt>Usual gap</dt><dd>' + (f.median_gap ? Math.round(f.median_gap) + ' days' : '-') + '</dd><dt>Overdue ratio</dt><dd>' + (f.overdue_ratio != null ? f.overdue_ratio + 'x' : '-') + '</dd><dt>Discount share</dt><dd>' + LQ.pct(f.discount_share) + '</dd><dt>Premium share</dt><dd>' + LQ.pct(f.premium_share) + '</dd><dt>Festive share</dt><dd>' + LQ.pct(f.festival_share) + '</dd><dt>Return rate</dt><dd>' + LQ.pct(f.return_rate) + '</dd><dt>Top categories</dt><dd>' + f.top_categories.map((x) => esc(x.name)).join(', ') + '</dd></dl>' +
      '<div class="notice small mt"><b>Ground truth persona:</b> ' + esc(c.persona_label) + '<br><span class="xs">Hidden from the AI. Compare it with the traits above.</span></div></div>' +
      '<div class="card"><h3>Loyalty</h3>' + LQ.progress(t.progress) + '<p class="small muted">' + (t.next_tier ? inr(t.gap_to_next) + ' to ' + esc(t.next_tier) : 'Top tier') + ' · ' + t.multiplier + 'x points' + (t.at_risk ? ' · <b style="color:var(--warn)">drops to ' + esc(t.drop_to) + ' on ' + LQ.date(t.drop_date) + '</b>' : '') + '</p></div>' +
      '<div class="card"><h3>Grant bonus points</h3><div class="form-row"><label class="f">Points</label><input type="number" id="bp" min="1" max="10000" placeholder="e.g. 200"></div><div class="form-row"><label class="f">Reason (required)</label><input type="text" id="br" placeholder="e.g. Service recovery"></div><button class="btn primary" data-act="grantBonus" data-id="' + c.id + '">Grant points</button></div>' +
      '<div class="card"><h3>Points ledger</h3><div class="tablewrap"><table><tbody>' + d.ledger.slice(0, 12).map((l) => '<tr><td class="xs">' + LQ.date(l.created_at) + '</td><td class="small">' + kind[l.kind] + (l.status !== 'active' ? ' ' + LQ.chip(l.status, 'warn') : '') + '</td><td class="right" style="font-weight:700;color:' + (l.points < 0 ? 'var(--bad)' : 'var(--good)') + '">' + (l.points > 0 ? '+' : '') + l.points + '</td></tr>').join('') + '</tbody></table></div></div></div></div>';
  };
  LQ.actions.grantBonus = async (el) => {
    await LQ.api('/admin/customers/' + el.dataset.id + '/bonus', { body: { points: Number(LQ.$('#bp').value), reason: LQ.$('#br').value } });
    LQ.toast('Bonus points granted', 'good'); V.customer360(LQ.$('#view'), el.dataset.id);
  };
  LQ.actions.editCustomer = (el) => LQ.modal('<h2>Edit customer</h2><div class="form-row"><label class="f">Name</label><input type="text" id="ec_name" value="' + el.dataset.name + '"></div><div class="form-row"><label class="f">City</label><input type="text" id="ec_city" value="' + el.dataset.city + '"></div>' +
    '<div class="row"><button class="btn primary" data-act="saveCustomer" data-id="' + el.dataset.id + '">Save</button><button class="btn" data-act="closeModal">Cancel</button></div>');
  LQ.actions.saveCustomer = async (el) => { await LQ.api('/admin/customers/' + el.dataset.id, { method: 'PUT', body: { name: LQ.$('#ec_name').value, city: LQ.$('#ec_city').value } }); LQ.closeModal(); LQ.toast('Customer updated', 'good'); V.customer360(LQ.$('#view'), el.dataset.id); };

  // ================= RULES =================
  V.rules = async function (root) {
    root.innerHTML = LQ.loading();
    const [{ settings: S }, camps, audit, offers, admins] = await Promise.all([LQ.api('/admin/settings'), LQ.api('/admin/campaigns'), LQ.api('/admin/audit'), LQ.api('/admin/offers'), LQ.api('/admin/admins')]);
    LQ.rulesTiers = S.loyalty.tiers.map((t) => Object.assign({}, t));
    const fld = (label, path, val, attrs) => '<div class="form-row"><label class="f">' + label + '</label><input type="number" data-s="' + path + '" value="' + val + '" ' + (attrs || 'step="any" min="0"') + '></div>';
    const W = S.recommender, NA = S.new_account_offer;
    root.innerHTML = '<div class="page-head"><div><h1>Loyalty rules</h1><p>Everything here is live: tiers, earning, approvals, guardrails and the recommender mix</p></div><div class="row"><button class="btn" data-act="resetRules">Reset to defaults</button><button class="btn primary" data-act="saveRules">Save changes</button></div></div>' +
      '<div class="grid g2"><div class="card"><h3>Earning and redeeming</h3><div class="grid g2">' + fld('Points per ₹100', 'loyalty.points_per_100', S.loyalty.points_per_100) + fld('₹ value of 1 point', 'loyalty.point_value', S.loyalty.point_value) + fld('Minimum redemption (pts)', 'loyalty.min_redeem', S.loyalty.min_redeem) +
      fld('Max share of order payable by points %', 'loyalty.max_redeem_pct', S.loyalty.max_redeem_pct, 'min="0" max="100"') + fld('Points expire after (days)', 'loyalty.expiry_days', S.loyalty.expiry_days, 'min="30"') + fld('Welcome bonus (pts)', 'loyalty.welcome_bonus', S.loyalty.welcome_bonus) + '</div></div>' +
      '<div class="card"><h3>Approval and guardrails</h3><div class="form-row"><label class="f">Which orders need admin approval</label><select data-s="approval.mode"><option value="flagged_only"' + (S.approval.mode === 'flagged_only' ? ' selected' : '') + '>Only large or risky orders</option><option value="all"' + (S.approval.mode === 'all' ? ' selected' : '') + '>Every order</option></select></div><div class="grid g2">' +
      fld('Large order threshold ₹', 'approval.large_order_threshold', S.approval.large_order_threshold) + fld('Risk score threshold (0-100)', 'approval.risk_threshold', S.approval.risk_threshold, 'min="1" max="100"') +
      fld('Monthly offer budget ₹', 'offers.monthly_budget', S.offers.monthly_budget) + fld('Max cost per offer ₹', 'offers.per_customer_cap', S.offers.per_customer_cap) + '</div>' +
      '<p class="xs muted">Offers committed this month: ' + inr(offers.budget.committed) + ' of ' + inr(offers.budget.budget) + '</p></div></div>' +
      '<div class="card mt"><h3>New-account offer</h3><p class="small muted mb">Given automatically to every customer who signs up (or is added by an admin) while it is on. It applies to their first order only, one use per account.</p><div class="grid g4">' +
      '<div class="form-row"><label class="f">Offer</label><select data-s="new_account_offer.enabled"><option value="1"' + (NA.enabled ? ' selected' : '') + '>On</option><option value="0"' + (NA.enabled ? '' : ' selected') + '>Off</option></select></div>' +
      fld('Discount on first order %', 'new_account_offer.discount_pct', NA.discount_pct, 'step="any" min="0" max="50"') + fld('Extra points on first order %', 'new_account_offer.bonus_points_pct', NA.bonus_points_pct, 'step="any" min="0" max="100"') +
      fld('Max discount ₹ (0 = no cap)', 'new_account_offer.max_discount', NA.max_discount) + '</div></div>' +
      '<div class="card mt"><h3>Tiers <span class="row"><button class="btn sm" data-act="addTier">+ Add tier</button><button class="btn sm" data-act="delTier">Remove last</button></span></h3><p class="small muted mb">Based on approved spend in the last 365 days. The first tier must start at ₹0.</p><div id="tierRows"></div></div>' +
      '<div class="card mt"><h3>Recommender mix</h3><p class="small muted mb">How much each signal contributes to the ranking. Check the effect on the AI page.</p><div class="grid g4">' +
      [['w_cf_item', 'Similar items bought together'], ['w_cf_user', 'Similar customers'], ['w_content', 'Category, price, brand fit'], ['w_popularity', 'Popularity'], ['w_replenish', 'Restock timing'], ['w_promo', 'Discounts'], ['w_campaign', 'Points campaigns'], ['w_margin', 'Margin']].map((x) => fld(x[1], 'recommender.' + x[0], W[x[0]], 'step="0.01" min="0" max="2"')).join('') + '</div></div>' +
      '<div class="card mt"><h3>Admin accounts <button class="btn sm" data-act="newAdmin">+ Add admin</button></h3><div class="tablewrap"><table><tbody>' + admins.map((a) => '<tr><td><b>' + esc(a.display_name) + '</b></td><td class="muted">' + esc(a.username) + '</td></tr>').join('') + '</tbody></table></div></div>' +
      '<div class="grid g2 mt"><div class="card"><h3>Points campaigns</h3><div class="tablewrap"><table><tbody>' + camps.map((c) => '<tr><td><b>' + esc(c.name) + '</b><div class="xs muted">' + (c.category ? esc((LQ.state.cats.find((x) => x.key === c.category) || {}).name) : 'All categories') + ' · ' + LQ.date(c.starts_at) + ' to ' + LQ.date(c.ends_at) + '</div></td><td>' + c.multiplier + 'x</td><td class="right"><button class="btn sm" data-act="toggleCamp" data-id="' + c.id + '" data-on="' + (c.active ? 0 : 1) + '">' + (c.active ? 'Pause' : 'Resume') + '</button></td></tr>').join('') + '</tbody></table></div>' +
      '<h4 class="mt">New campaign</h4><div class="grid g2"><div class="form-row"><label class="f">Name</label><input type="text" id="cp_name" placeholder="Weekend dairy 2x"></div><div class="form-row"><label class="f">Category</label><select id="cp_cat"><option value="">All categories</option>' + LQ.state.cats.map((c) => '<option value="' + c.key + '">' + esc(c.name) + '</option>').join('') + '</select></div>' +
      '<div class="form-row"><label class="f">Multiplier</label><input type="number" id="cp_mult" value="2" step="0.5" min="1" max="10"></div><div class="form-row"><label class="f">Days</label><input type="number" id="cp_days" value="7" min="1"></div></div><button class="btn primary" data-act="createCampaign">Start campaign</button></div>' +
      '<div class="card"><h3>Audit log</h3><div class="tablewrap" style="max-height:420px;overflow:auto"><table><tbody>' + audit.map((a) => '<tr><td class="xs nowrap">' + LQ.datetime(a.ts) + '</td><td class="small"><b>' + esc(a.actor) + '</b> ' + esc(a.action) + '<div class="xs muted">' + esc(a.detail || '') + '</div></td></tr>').join('') + '</tbody></table></div></div></div>';
    paintTiers();
  };
  function paintTiers() {
    LQ.$('#tierRows').innerHTML = '<div class="tablewrap"><table><thead><tr><th>Name</th><th>From spend ₹ / year</th><th>Points multiplier</th><th>Perks (comma separated)</th></tr></thead><tbody>' + LQ.rulesTiers.map((t, i) => '<tr data-ti="' + i + '"><td><input type="text" data-tf="name" value="' + esc(t.name) + '"></td><td><input type="number" data-tf="min_spend" value="' + t.min_spend + '"' + (i === 0 ? ' disabled' : '') + '></td><td><input type="number" step="0.05" min="1" data-tf="multiplier" value="' + t.multiplier + '"></td><td><input type="text" data-tf="perks" value="' + esc((t.perks || []).join(', ')) + '"></td></tr>').join('') + '</tbody></table></div>';
  }
  function readTiers() { document.querySelectorAll('#tierRows tr[data-ti]').forEach((tr) => { const t = LQ.rulesTiers[tr.dataset.ti]; tr.querySelectorAll('[data-tf]').forEach((i) => { const k = i.dataset.tf; t[k] = k === 'perks' ? i.value.split(',').map((s) => s.trim()).filter(Boolean) : (k === 'name' ? i.value : Number(i.value)); }); }); }
  LQ.actions.addTier = () => { readTiers(); const last = LQ.rulesTiers[LQ.rulesTiers.length - 1]; LQ.rulesTiers.push({ name: 'New tier', min_spend: last.min_spend * 2 || 1000, multiplier: last.multiplier + 0.25, perks: [] }); paintTiers(); };
  LQ.actions.delTier = () => { readTiers(); if (LQ.rulesTiers.length > 2) LQ.rulesTiers.pop(); paintTiers(); };
  LQ.actions.saveRules = async () => {
    readTiers();
    const body = { loyalty: { tiers: LQ.rulesTiers }, approval: {}, offers: {}, recommender: {}, new_account_offer: {} };
    document.querySelectorAll('[data-s]').forEach((i) => { const [sec, k] = i.dataset.s.split('.'); body[sec][k] = i.tagName === 'SELECT' ? i.value : Number(i.value); });
    await LQ.api('/admin/settings', { method: 'PUT', body }); LQ.toast('Rules saved and live', 'good'); LQ.refreshBadges(); V.rules(LQ.$('#view'));
  };
  LQ.actions.resetRules = async () => { if (!confirm('Reset all rules to the defaults?')) return; await LQ.api('/admin/settings/reset', { method: 'POST' }); LQ.toast('Defaults restored'); V.rules(LQ.$('#view')); };
  LQ.actions.toggleCamp = async (el) => { await LQ.api('/admin/campaigns/' + el.dataset.id, { method: 'PUT', body: { active: el.dataset.on === '1' } }); V.rules(LQ.$('#view')); };
  LQ.actions.createCampaign = async () => { await LQ.api('/admin/campaigns', { body: { name: LQ.$('#cp_name').value, category: LQ.$('#cp_cat').value, multiplier: Number(LQ.$('#cp_mult').value), days: Number(LQ.$('#cp_days').value) } }); LQ.toast('Campaign started', 'good'); V.rules(LQ.$('#view')); };

  // ================= AI AND PERSONAS =================
  V.ai = async function (root) {
    root.innerHTML = LQ.loading();
    const [pers, mq] = await Promise.all([LQ.api('/admin/personas'), LQ.api('/admin/model-quality')]);
    const r = mq.recommender, ch = mq.churn;
    root.innerHTML = '<div class="page-head"><div><h1>AI and personas</h1><p>How well the models work, and whether they recover the behaviours we built into the ten personas</p></div><button class="btn" data-act="reEval">Re-run evaluation</button></div>' +
      '<div class="grid g4">' + kpi('Recommender hit rate', LQ.pct(r.hit_rate), 'popular-items baseline ' + LQ.pct(r.baseline_hit_rate) + ' · ' + r.lift_vs_popularity + 'x lift') + kpi('Category hit rate', LQ.pct(r.category_hit_rate), 'baseline ' + LQ.pct(r.baseline_category_hit_rate)) +
      kpi('Precision@' + r.k, LQ.pct(r.precision), 'recall ' + LQ.pct(r.recall) + ' · coverage ' + LQ.pct(r.catalogue_coverage)) + kpi('Churn model AUC', ch.auc != null ? ch.auc : 'n/a', ch.n_samples + ' snapshots · tested on a later time slice') + '</div>' +
      '<p class="small muted mt">Recommender test: trained on orders before ' + r.holdout_days + ' days ago, then checked whether the top ' + r.k + ' contained what ' + r.customers + ' customers bought afterwards. Evaluated ' + LQ.datetime(mq.evaluated_at) + '.</p>' +
      '<div class="card mt"><h3>Ten personas: built-in behaviour vs what the AI inferred</h3><p class="small muted mb">Every figure below is computed from raw orders. The AI never sees the persona label.</p><div class="tablewrap"><table><thead><tr><th>Persona</th><th class="right">Customers</th><th class="right">Orders / yr</th><th class="right">Avg order</th><th class="right">Deal share</th><th class="right">Premium</th><th class="right">Festive</th><th class="right">Returns</th><th class="right">Churn</th><th>Top category</th><th>Inferred traits</th></tr></thead><tbody>' +
      pers.map((p) => '<tr><td><b>' + esc(p.label) + '</b> <span class="chip brand">' + esc(p.username) + '</span><div class="xs muted" style="max-width:260px">' + esc(p.blurb) + '</div></td><td class="right">' + p.customers + '</td><td class="right">' + (p.avg_orders_12m != null ? p.avg_orders_12m.toFixed(1) : '-') + '</td><td class="right">' + inr(p.avg_order_value) + '</td><td class="right">' + LQ.pct(p.discount_share) + '</td><td class="right">' + LQ.pct(p.premium_share) + '</td><td class="right">' + LQ.pct(p.festival_share) + '</td><td class="right">' + LQ.pct(p.return_rate) + '</td><td class="right">' + LQ.pct(p.churn_risk) + '</td><td class="small">' + esc(p.top_categories.join(', ')) + '</td><td>' + p.inferred_traits.map((t) => '<span class="chip">' + esc(t) + '</span>').join(' ') + '</td></tr>').join('') + '</tbody></table></div></div>' +
      '<div class="card mt"><h3>How it works</h3><ul class="small" style="margin:0;padding-left:18px"><li><b>Behaviour analytics:</b> features per customer (frequency, basket, discount and brand-tier mix, seasonality, returns), cadence-aware RFM segments, 12-month value.</li><li><b>Churn model:</b> gradient boosting trained on monthly snapshots, labelled by "no order in the next 90 days", with a seasonal rule so festive buyers are not flagged off-season.</li><li><b>Recommender:</b> item-to-item and user-to-user collaborative filtering, content fit, popularity, learned restock timing, offers and campaigns, with stock and ownership rules and category diversity.</li><li><b>Agent:</b> scores candidate actions (win-back, tier protection, upgrade nudge, expiring points, restock, redeem, discover) and checks any offer against your budget guardrails.</li></ul></div>';
  };
  LQ.actions.reEval = async () => { LQ.toast('Re-running evaluation…'); await LQ.api('/admin/model-quality?refresh=1'); V.ai(LQ.$('#view')); };
})();
