/* Admin console, part 2: customer segmentation, product awareness campaigns, and the add-new forms. */
(function () {
  const LQ = window.LQ, esc = LQ.esc, inr = LQ.inr, num = LQ.num;
  const V = LQ.views.admin;
  const pct = (x) => (x == null ? '-' : Math.round(x * 100) + '%');
  const kpi = (label, value, extra) => '<div class="card kpi"><div class="label">' + label + '</div><div class="value">' + value + '</div><div class="sub">' + (extra || '') + '</div></div>';

  // ================= SEGMENTS =================
  V.segments = async function (root) {
    root.innerHTML = LQ.loading();
    const d = await LQ.api('/admin/segments');
    const S = d.segments, live = S.filter((s) => s.count > 0);
    const big = live.reduce((a, b) => (b.count > a.count ? b : a), live[0]);
    const core = S.filter((s) => s.segment === 'Champion' || s.segment === 'Loyal');
    const coreShare = core.reduce((a, s) => a + s.spend_share, 0), coreN = core.reduce((a, s) => a + s.count, 0);
    const wb = S.filter((s) => s.segment === 'At risk' || s.segment === 'Hibernating').reduce((a, s) => a + s.count, 0);
    root.innerHTML = '<div class="page-head"><div><h1>Customer segments</h1><p>Groups the AI learned from raw order history (recency, frequency, spend and each customer\'s own buying rhythm). Pick a group to see who is in it or to advertise to it.</p></div>' +
      '<button class="btn primary" data-act="promoNew">📣 New awareness campaign</button></div>' +
      '<div class="grid g4">' + kpi('Customers', num(d.total), S.filter((s) => s.count).length + ' segments in use') +
      kpi('Largest segment', big ? esc(big.segment) : '-', big ? num(big.count) + ' customers · ' + pct(big.share) : '') +
      kpi('Champions + Loyal', pct(coreShare) + ' of spend', num(coreN) + ' customers drive this') +
      kpi('Win-back pool', num(wb), 'At risk and hibernating customers') + '</div>' +
      '<div class="grid g3 mt">' + S.map((s) => '<div class="card seg"><div class="row between"><h3>' + esc(s.segment) + '</h3><span class="chip brand">' + num(s.count) + ' · ' + pct(s.share) + '</span></div>' +
        LQ.progress(s.share * 3) + '<p class="small muted" style="margin:8px 0 4px">' + esc(s.meaning) + '</p>' +
        (s.count ? '<dl class="kv"><dt>Avg spend 12m</dt><dd>' + inr(s.spend_12m_avg) + '</dd><dt>Avg order</dt><dd>' + (s.aov_avg ? inr(s.aov_avg) : '-') + '</dd><dt>Orders 12m</dt><dd>' + s.orders_avg + '</dd><dt>Days since order</dt><dd>' + (s.recency_avg != null ? s.recency_avg : '-') + '</dd><dt>Churn risk</dt><dd>' + pct(s.churn_avg) + '</dd><dt>Yearly value</dt><dd>' + inr(s.clv_avg) + '</dd></dl>' +
          '<p class="xs muted" style="margin-top:6px">Likes: ' + (s.top_categories.length ? s.top_categories.map(esc).join(', ') : 'no history yet') + '</p>' +
          (s.top_traits.length ? '<div class="row" style="margin-top:4px">' + s.top_traits.map((t) => '<span class="chip">' + esc(t) + '</span>').join('') + '</div>' : '') : '') +
        '<div class="notice small mt"><b>Play:</b> ' + esc(s.play) + '</div>' +
        '<div class="row mt"><button class="btn sm" data-act="segCustomers" data-seg="' + esc(s.segment) + '"' + (s.count ? '' : ' disabled') + '>View customers</button>' +
        '<button class="btn sm primary" data-act="promoNew" data-seg="' + esc(s.segment) + '"' + (s.count ? '' : ' disabled') + '>📣 Advertise</button></div></div>').join('') + '</div>' +
      '<div class="grid g-side mt"><div class="card"><h3>Segments by tier</h3><p class="xs muted mb">How many customers of each behaviour segment sit in each loyalty tier. Click a number to open that group.</p><div class="tablewrap"><table><thead><tr><th>Segment</th>' +
      d.tiers.map((t) => '<th class="right">' + LQ.tier(t) + '</th>').join('') + '<th class="right">Total</th></tr></thead><tbody>' +
      S.map((s) => '<tr><td><b>' + esc(s.segment) + '</b></td>' + d.tiers.map((t) => '<td class="right">' + (s.tiers[t] ? '<a href="#" data-act="segCustomers" data-seg="' + esc(s.segment) + '" data-tier="' + esc(t) + '">' + num(s.tiers[t]) + '</a>' : '<span class="muted">0</span>') + '</td>').join('') + '<td class="right"><b>' + num(s.count) + '</b></td></tr>').join('') + '</tbody></table></div></div>' +
      '<div class="card"><h3>Share of 12-month spend</h3>' + LQ.hbars(S.filter((s) => s.count), { label: (r) => r.segment, value: 'spend_12m_total', fmt: inr }) + '</div></div>';
  };
  LQ.actions.segCustomers = (el, e) => { if (e && e.preventDefault) e.preventDefault(); LQ.customerFilter(el.dataset.seg || '', el.dataset.tier || ''); };

  // ================= PROMOTIONS (product awareness campaigns) =================
  const promo = { product: null, segs: new Set(), tiers: new Set(), seg: null, results: [] };
  const STATUS = { active: ['Running', 'good'], paused: ['Paused', 'warn'], ended: ['Ended', ''], scheduled: ['Scheduled', 'brand'] };
  const mini = (v, l, sub) => '<div class="mini"><b>' + v + '</b><span>' + l + '</span>' + (sub ? '<i>' + sub + '</i>' : '') + '</div>';
  const funnel = (b) => '<div class="minis">' + mini(num(b.reached), 'Reached', num(b.impressions) + ' views') + mini(num(b.clickers), 'Clicked', pct(b.ctr) + ' of reached') + mini(num(b.carters), 'Added to cart', pct(b.cart_rate) + ' of clicked') +
    mini(num(b.buyers), 'Bought', pct(b.conversion) + ' of reached') + mini(inr(b.revenue), 'Revenue', num(b.units) + ' units') + '</div>';
  const segTable = (rows) => rows.length ? '<div class="tablewrap"><table><thead><tr><th>Segment</th><th class="right">Reached</th><th class="right">Clicked</th><th class="right">CTR</th><th class="right">Bought</th><th class="right">Revenue</th></tr></thead><tbody>' +
    rows.map((r) => '<tr><td>' + esc(r.segment) + '</td><td class="right">' + num(r.reached) + '</td><td class="right">' + num(r.clickers) + '</td><td class="right">' + pct(r.ctr) + '</td><td class="right">' + num(r.buyers) + '</td><td class="right">' + inr(r.revenue) + '</td></tr>').join('') + '</tbody></table></div>' : '';

  V.promotions = async function (root) {
    root.innerHTML = LQ.loading();
    const list = await LQ.api('/admin/promotions');
    const running = list.filter((c) => c.status === 'active');
    root.innerHTML = '<div class="page-head"><div><h1>Product awareness campaigns</h1><p>Advertise a product to the customer segments and tiers you choose. They see a "Featured for you" card in their portal, and views, clicks, carts and purchases are tracked here.</p></div>' +
      '<div class="row"><button class="btn" data-act="promoRefresh">↻ Refresh results</button><button class="btn primary" data-act="promoNew">📣 New awareness campaign</button></div></div>' +
      '<div class="grid g4">' + kpi('Running now', num(running.length), num(list.length) + ' campaigns in total') +
      kpi('Customers targeted', num(running.reduce((a, c) => a + c.audience, 0)), 'Across running campaigns (people can overlap)') +
      kpi('Live clicks', num(list.reduce((a, c) => a + c.live.clickers, 0)), 'Real customers only') +
      kpi('Live attributed sales', inr(list.reduce((a, c) => a + c.live.revenue, 0)), 'Orders placed after seeing the ad') + '</div>' +
      '<div class="notice small mt"><b>How to read this.</b> Live numbers come from real portal activity. A purchase counts only if the customer saw or clicked the ad first and ordered the product before the campaign ended (plus 7 days). With no real shoppers, press <b>Simulate traffic</b> to fill a campaign with clearly labelled illustrative numbers, and clear them any time.</div>' +
      (list.length ? list.map((c) => {
        const st = STATUS[c.status] || [c.status, ''], hasSim = c.simulated.reached > 0, hasLive = c.live.reached > 0;
        return '<div class="card mt" id="promo' + c.id + '"><div class="row between"><div class="row"><span style="font-size:34px">' + esc(c.product.emoji) + '</span><div><h3 style="margin:0">' + esc(c.name) + ' ' + LQ.chip(st[0], st[1]) + '</h3>' +
          '<div class="small muted">' + esc(c.product.name) + ' · ' + inr(c.product.price) + ' · ' + num(c.product.stock) + ' in stock</div></div></div>' +
          '<div class="row">' + (c.status === 'active' ? '<button class="btn sm" data-act="promoStatus" data-id="' + c.id + '" data-status="paused">Pause</button>' : '') +
          (c.status === 'paused' ? '<button class="btn sm good" data-act="promoStatus" data-id="' + c.id + '" data-status="active">Resume</button>' : '') +
          (c.status === 'active' || c.status === 'paused' ? '<button class="btn sm" data-act="promoStatus" data-id="' + c.id + '" data-status="ended">End now</button>' : '') +
          '<button class="btn sm" data-act="promoSim" data-id="' + c.id + '">Simulate traffic</button>' +
          (hasSim ? '<button class="btn sm" data-act="promoClearSim" data-id="' + c.id + '">Clear simulated</button>' : '') +
          '<button class="btn sm bad" data-act="promoDelete" data-id="' + c.id + '">Delete</button></div></div>' +
          '<p class="small" style="margin:10px 0 4px"><b>“' + esc(c.headline) + '”</b>' + (c.message ? ' ' + esc(c.message) : '') + '</p>' +
          '<div class="row small muted mb"><span>Audience <b>' + num(c.audience) + '</b></span><span>·</span><span>Segments: ' + (c.segments.length ? c.segments.map(esc).join(', ') : 'everyone') + '</span><span>·</span><span>Tiers: ' + (c.tiers.length ? c.tiers.map(esc).join(', ') : 'all') + '</span><span>·</span><span>' + (c.exclude_buyers ? 'skips past buyers' : 'includes past buyers') + '</span><span>·</span><span>' + LQ.date(c.starts_at) + ' to ' + LQ.date(c.ends_at) + '</span></div>' +
          '<div class="small" style="margin:8px 0 4px"><b>Live</b> ' + (hasLive ? '' : '<span class="muted">No real views yet. They appear when targeted customers open their portal.</span>') + '</div>' + (hasLive ? funnel(c.live) : '') +
          (hasSim ? '<div class="small" style="margin:12px 0 4px"><b>Simulated</b> ' + LQ.chip('Illustrative, not real', 'warn') + '</div>' + funnel(c.simulated) : '') +
          ((hasLive || hasSim) ? '<details class="mt"><summary class="small">Results by segment</summary>' + (hasLive ? '<p class="xs muted" style="margin-top:8px">Live</p>' + segTable(c.live_by_segment) : '') + (hasSim ? '<p class="xs muted" style="margin-top:8px">Simulated</p>' + segTable(c.simulated_by_segment) : '') + '</details>' : '') + '</div>';
      }).join('') : '<div class="empty card mt">No campaigns yet. Click “New awareness campaign” or use the Advertise button on a segment.</div>');
  };
  const reload = () => { const root = LQ.$('#view'); return V.promotions(root); };
  LQ.actions.promoRefresh = () => reload();
  LQ.actions.promoStatus = async (el) => { await LQ.api('/admin/promotions/' + el.dataset.id + '/status', { body: { status: el.dataset.status } }); LQ.toast('Campaign updated', 'good'); reload(); };
  LQ.actions.promoSim = async (el) => { await LQ.api('/admin/promotions/' + el.dataset.id + '/simulate', { method: 'POST' }); LQ.toast('Simulated traffic added (labelled, separate from live numbers)', 'good'); reload(); };
  LQ.actions.promoClearSim = async (el) => { await LQ.api('/admin/promotions/' + el.dataset.id + '/simulated', { method: 'DELETE' }); LQ.toast('Simulated traffic cleared', 'good'); reload(); };
  LQ.actions.promoDelete = async (el) => { if (!confirm('Delete this campaign and its tracking data?')) return; await LQ.api('/admin/promotions/' + el.dataset.id, { method: 'DELETE' }); LQ.toast('Campaign deleted', 'good'); reload(); };

  // ----- composer -----
  LQ.actions.promoNew = async (el) => {
    const d = await LQ.api('/admin/segments');
    promo.product = null; promo.results = []; promo.segs = new Set(el && el.dataset && el.dataset.seg ? [el.dataset.seg] : []); promo.tiers = new Set(); promo.seg = d;
    LQ.modal('<h2>New awareness campaign</h2><p class="small muted mb">Choose what to advertise and who should see it. Nothing is sent anywhere else: customers see a card in their own portal.</p>' +
      '<div class="form-row"><label class="f">1. Product to advertise</label><div id="prPicked" class="small muted">Nobody picked yet. Search below.</div><input type="search" id="prSearch" data-input="prSearch" placeholder="Search products by name or SKU…" autocomplete="off"><div id="prResults"></div></div>' +
      '<div class="form-row"><label class="f">2. Customer segments (none ticked = everyone)</label><div class="checks">' + d.segments.map((s) => '<label class="chk"><input type="checkbox" data-change="prSeg" value="' + esc(s.segment) + '"' + (promo.segs.has(s.segment) ? ' checked' : '') + (s.count ? '' : ' disabled') + '> ' + esc(s.segment) + ' <span class="muted xs">' + num(s.count) + '</span></label>').join('') + '</div></div>' +
      '<div class="form-row"><label class="f">3. Loyalty tiers (none ticked = all tiers)</label><div class="checks">' + d.tiers.map((t) => '<label class="chk"><input type="checkbox" data-change="prTier" value="' + esc(t) + '"> ' + esc(t) + '</label>').join('') + '</div></div>' +
      '<div class="form-row"><label class="chk"><input type="checkbox" id="pr_ex" data-change="prRefresh" checked> Skip customers who already bought this product</label></div>' +
      '<div class="grid g2"><div class="form-row"><label class="f">Headline</label><input type="text" id="pr_head" maxlength="90" placeholder="e.g. Fresh on the shelf: try our new range"></div>' +
      '<div class="form-row"><label class="f">Runs for (days)</label><input type="number" id="pr_days" min="1" max="90" value="14" data-change="prRefresh"></div></div>' +
      '<div class="form-row"><label class="f">Message (optional)</label><input type="text" id="pr_msg" maxlength="240" placeholder="One short line shown under the headline"></div>' +
      '<div class="form-row"><label class="f">Campaign name (internal, optional)</label><input type="text" id="pr_name" maxlength="80"></div>' +
      '<div id="prPreview" class="notice small mb">Pick a product to see who would be reached.</div>' +
      '<div class="row"><button class="btn primary" data-act="promoCreate">Launch campaign</button><button class="btn" data-act="closeModal">Cancel</button></div>', true);
  };
  const promoBody = () => ({ product_id: promo.product && promo.product.id, segments: [...promo.segs], tiers: [...promo.tiers], exclude_buyers: LQ.$('#pr_ex').checked,
    headline: LQ.$('#pr_head').value.trim(), message: LQ.$('#pr_msg').value.trim(), name: LQ.$('#pr_name').value.trim(), days: Number(LQ.$('#pr_days').value || 14) });
  async function refreshPreview() {
    const box = LQ.$('#prPreview'); if (!box) return;
    if (!promo.product) { box.innerHTML = 'Pick a product to see who would be reached.'; return; }
    try {
      const r = await LQ.api('/admin/promotions/preview', { body: promoBody() });
      box.innerHTML = '<b>' + num(r.audience) + ' of ' + num(r.of_customers) + ' customers</b> would see this' + (r.already_bought ? ' (' + num(r.already_bought) + ' skipped because they already bought it)' : '') + '.' +
        (r.by_segment.length ? '<div class="row" style="margin-top:6px">' + r.by_segment.map((s) => '<span class="chip">' + esc(s.segment) + ' ' + num(s.count) + '</span>').join('') + '</div>' : '') +
        (r.category_fit != null ? '<div class="xs muted" style="margin-top:6px">' + pct(r.category_fit) + ' of this audience already buys mostly in this product\'s category' + (r.category_fit < 0.1 ? ', so expect lower interest. Consider widening to segments that like it.' : '.') + '</div>' : '');
    } catch (e) { box.innerHTML = '<span style="color:var(--bad)">' + esc(e.message) + '</span>'; }
  }
  LQ.inputs.prSearch = LQ.debounce(async (el) => {
    const q = el.value.trim(), box = LQ.$('#prResults'); if (!box) return;
    if (q.length < 2) { box.innerHTML = ''; return; }
    const d = await LQ.api('/admin/products?q=' + encodeURIComponent(q));
    promo.results = d.items.filter((p) => p.active).slice(0, 6);
    box.innerHTML = promo.results.length ? promo.results.map((p) => '<div class="pick" data-act="prPick" data-id="' + p.id + '"><span>' + esc(p.emoji) + ' ' + esc(p.name) + ' <span class="muted xs">' + esc(p.unit || '') + '</span></span><span class="small">' + inr(p.price) + ' · ' + (p.stock > 0 ? p.stock + ' in stock' : '<b style="color:var(--bad)">out of stock</b>') + '</span></div>').join('') : '<div class="small muted">No active products match.</div>';
  }, 250);
  LQ.actions.prPick = (el) => {
    promo.product = promo.results.find((p) => p.id == el.dataset.id);
    LQ.$('#prPicked').innerHTML = '<b>' + esc(promo.product.emoji) + ' ' + esc(promo.product.name) + '</b> · ' + inr(promo.product.price) + (promo.product.stock <= 0 ? ' <span style="color:var(--bad)">(out of stock: customers will not see it until restocked)</span>' : '');
    LQ.$('#prResults').innerHTML = ''; LQ.$('#prSearch').value = '';
    if (!LQ.$('#pr_head').value) LQ.$('#pr_head').value = 'Have you tried ' + promo.product.name + '?';
    refreshPreview();
  };
  LQ.changes.prSeg = (el) => { el.checked ? promo.segs.add(el.value) : promo.segs.delete(el.value); refreshPreview(); };
  LQ.changes.prTier = (el) => { el.checked ? promo.tiers.add(el.value) : promo.tiers.delete(el.value); refreshPreview(); };
  LQ.changes.prRefresh = () => refreshPreview();
  LQ.actions.promoCreate = async () => {
    if (!promo.product) { LQ.toast('Pick a product first', 'bad'); return; }
    const c = await LQ.api('/admin/promotions', { body: promoBody() });
    LQ.closeModal(); LQ.toast('Campaign launched to ' + num(c.audience) + ' customers', 'good');
    if (location.hash === '#/admin/promotions') reload(); else location.hash = '#/admin/promotions';
  };

  // ================= ADD NEW: customer, admin, category =================
  LQ.actions.newCustomer = () => LQ.modal('<h2>Add customer</h2><p class="small muted mb">Creates a login right away. They start with no order history, so the agent shows popular products until they buy something.</p>' +
    '<div class="grid g2"><div class="form-row"><label class="f">Full name</label><input type="text" id="nc_name" maxlength="60"></div><div class="form-row"><label class="f">City (optional)</label><input type="text" id="nc_city"></div>' +
    '<div class="form-row"><label class="f">Email (optional)</label><input type="text" id="nc_email"></div><div class="form-row"><label class="f">Welcome points (optional)</label><input type="number" id="nc_pts" min="0" max="10000" value="0"></div>' +
    '<div class="form-row"><label class="f">Username (blank = automatic)</label><input type="text" id="nc_user" placeholder="e.g. user170"></div><div class="form-row"><label class="f">Password (blank = 1234)</label><input type="text" id="nc_pw"></div></div>' +
    '<div class="row"><button class="btn primary" data-act="createCustomer">Create customer</button><button class="btn" data-act="closeModal">Cancel</button></div>');
  LQ.actions.createCustomer = async () => {
    const v = (id) => LQ.$('#' + id).value.trim();
    const r = await LQ.api('/admin/customers', { body: { name: v('nc_name'), city: v('nc_city'), email: v('nc_email'), welcome_points: Number(v('nc_pts') || 0), username: v('nc_user'), password: v('nc_pw') } });
    LQ.closeModal(); LQ.toast('Created ' + r.username + ' (' + r.password_note + ')', 'good'); location.hash = '#/admin/customers/' + r.id;
  };
  LQ.actions.newCategory = () => LQ.modal('<h2>Add product category</h2><p class="small muted mb">The category appears in the shop, product forms, analytics and recommendations straight away.</p>' +
    '<div class="grid g2"><div class="form-row"><label class="f">Category name</label><input type="text" id="nk_name" maxlength="40" placeholder="e.g. Garden Supplies"></div><div class="form-row"><label class="f">Emoji</label><input type="text" id="nk_emoji" maxlength="8" placeholder="🌱"></div></div>' +
    '<div class="form-row"><label class="f">Usual days between repeat purchases (blank = one-off items)</label><input type="number" id="nk_cycle" min="1" max="365" placeholder="e.g. 30 for monthly refills"><p class="xs muted">Used by the replenishment signal. Leave blank for durable goods like furniture.</p></div>' +
    '<div class="row"><button class="btn primary" data-act="createCategory">Create category</button><button class="btn" data-act="closeModal">Cancel</button></div>');
  LQ.actions.createCategory = async () => {
    const v = (id) => LQ.$('#' + id).value.trim();
    const c = await LQ.api('/admin/categories', { body: { name: v('nk_name'), emoji: v('nk_emoji'), cycle: v('nk_cycle') } });
    LQ.state.cats = await LQ.api('/categories'); LQ.state.cats.forEach((x) => { LQ.CAT_COLOR[x.key] = x.color; });
    LQ.closeModal(); LQ.toast('Category “' + c.name + '” created. Add products to it next.', 'good');
    if (location.hash.indexOf('#/admin/products') === 0) V.products(LQ.$('#view'));
  };
  LQ.actions.newAdmin = () => LQ.modal('<h2>Add admin account</h2><p class="small muted mb">Admins can see everything in this console. Give the password to the person directly.</p>' +
    '<div class="grid g2"><div class="form-row"><label class="f">Full name</label><input type="text" id="na_name" maxlength="60"></div><div class="form-row"><label class="f">Username</label><input type="text" id="na_user" maxlength="24" placeholder="e.g. ops2"></div></div>' +
    '<div class="form-row"><label class="f">Password (4+ characters)</label><input type="text" id="na_pw"></div>' +
    '<div class="row"><button class="btn primary" data-act="createAdmin">Create admin</button><button class="btn" data-act="closeModal">Cancel</button></div>');
  LQ.actions.createAdmin = async () => {
    const v = (id) => LQ.$('#' + id).value.trim();
    await LQ.api('/admin/admins', { body: { name: v('na_name'), username: v('na_user'), password: LQ.$('#na_pw').value } });
    LQ.closeModal(); LQ.toast('Admin account created', 'good'); if (location.hash === '#/admin/rules') V.rules(LQ.$('#view'));
  };
})();
