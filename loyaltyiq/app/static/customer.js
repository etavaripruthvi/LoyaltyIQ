/* Customer portal: home (insights and agent), shop, cart and checkout, orders, rewards, assistant. */
(function () {
  const LQ = window.LQ, esc = LQ.esc, inr = LQ.inr, num = LQ.num;
  const V = (LQ.views.customer = {});

  // ================= HOME =================
  V.home = async function (root) {
    root.innerHTML = LQ.loading();
    const [d, recs, promos] = await Promise.all([LQ.api('/customer/overview'), LQ.api('/customer/recommendations?k=8'), LQ.api('/customer/promotions').catch(() => [])]);
    LQ.register(recs); LQ.register(promos.map((x) => x.product)); d.next_best_action.items.forEach((i) => LQ.register([i])); d.actions.forEach((a) => LQ.register(a.items));
    const t = d.tier, p = d.points, nba = d.next_best_action, ins = d.insights, tot = ins.totals;
    const first = d.profile.name.split(' ')[0];
    const toNext = t.next_tier ? 'You are <b>' + inr(t.gap_to_next) + '</b> away from <b>' + esc(t.next_tier) + '</b>' : 'You are at our top tier';
    const na = d.new_account_offer;
    const naBanner = na ? '<div class="card promo-card mb" style="grid-template-columns:auto 1fr auto"><div class="big">🎁</div><div><span class="chip brand">New-account offer</span><h3 style="margin:6px 0 2px;display:block">Welcome! ' + naParts(na) + ' on your first order</h3>' +
      '<p class="small muted">Applied automatically at checkout' + (na.max_discount ? ' (discount up to ' + inr(na.max_discount) + ')' : '') + '. One use per account.</p></div><div class="cta"><a class="btn primary" href="#/shop">Start shopping</a></div></div>' : '';
    const offerBanner = naBanner + (d.active_offer ? '<div class="notice good mb">🎉 <b>' + d.active_offer.multiplier + 'x points</b> is active on your next order (' + esc(d.active_offer.reason || 'special offer') + '), valid until ' + LQ.date(d.active_offer.expires_at) + '.</div>' : '');
    const camps = d.campaigns.length ? '<div class="row mb">' + d.campaigns.map((c) => LQ.chip('⚡ ' + c.name, 'brand')).join('') + '</div>' : '';
    const savings = tot.deal_savings + tot.points_savings;
    root.innerHTML =
      '<div class="hero"><div><div class="row"><span class="small" style="opacity:.85">Welcome back</span>' + LQ.tier(t.tier) + '</div><h1>' + esc(first) + ', here is your loyalty snapshot</h1>' +
      '<p style="opacity:.9">' + toNext + (t.next_tier ? ' (' + t.next_tier + ' earns ' + (d.tiers.find((x) => x.name === t.next_tier) || {}).multiplier + 'x points).' : '.') + '</p>' +
      '<div style="margin:12px 0 6px">' + LQ.progress(t.progress) + '</div><div class="small" style="opacity:.85">' + inr(t.spend_12m) + ' spent in the last 12 months · you earn <b>' + t.multiplier + 'x</b> points' +
      (t.at_risk ? ' · <b>' + esc(t.tier) + ' status ends ' + LQ.date(t.drop_date) + '</b> unless you shop ' + inr(t.retain_gap) + ' more' : '') + '</div></div>' +
      '<div class="grid g3" style="align-content:center"><div class="stat"><b>' + num(p.active) + '</b><span>Points ≈ ' + inr(p.active * d.rules.point_value) + '</span></div>' +
      '<div class="stat"><b>' + num(p.pending) + '</b><span>Pending approval</span></div><div class="stat"><b>' + num(p.expiring_30d) + '</b><span>Expiring in 30 days</span></div></div></div>' +
      '<div class="mt">' + offerBanner + camps + '</div>' + promoCards(promos) +
      '<div class="grid g-side"><div>' + nbaCard(nba, true) +
      '<div class="grid g2 mt"><div class="card"><h3>Your spending</h3>' + LQ.barChart(ins.monthly, { y: 'spend', label: (r) => LQ.month(r.month), fmt: inr, title: 'Monthly spend' }) + '</div>' +
      '<div class="card"><h3>Where it goes</h3>' + LQ.hbars(ins.categories.slice(0, 6), { label: (r) => r.emoji + ' ' + r.name, value: 'spend', fmt: inr, color: () => 'var(--brand)' }) + '</div></div></div>' +
      '<div class="grid" style="align-content:start"><div class="grid g2"><div class="card tight kpi"><div class="label">Spent (12m)</div><div class="value">' + inr(tot.spend) + '</div></div>' +
      '<div class="card tight kpi"><div class="label">Orders</div><div class="value">' + num(tot.orders) + '</div></div>' +
      '<div class="card tight kpi"><div class="label">Avg basket</div><div class="value">' + inr(tot.aov) + '</div></div>' +
      '<div class="card tight kpi"><div class="label">You saved</div><div class="value" style="color:var(--good)">' + inr(savings) + '</div></div></div>' +
      '<div class="card"><h3>Your shopping style</h3><div class="row mb">' + d.traits.map((x) => '<span class="chip brand" title="' + esc(x.detail) + '">' + esc(x.label) + '</span>').join('') + '</div>' +
      '<p class="small muted">Learned from your orders: ' + (d.behaviour.median_gap ? 'you usually shop every <b>' + Math.round(d.behaviour.median_gap) + ' days</b>, ' : '') + 'about <b>' + LQ.pct(d.behaviour.discount_share) + '</b> of your spend is on discounted items.</p></div>' +
      '<div class="card"><h3>Most bought</h3>' + (ins.top_products.length ? ins.top_products.map((x) => '<div class="row between small" style="padding:4px 0"><span>' + esc(x.emoji) + ' ' + esc(x.name) + '</span><span class="muted">×' + x.qty + '</span></div>').join('') : '<div class="empty">Nothing yet</div>') + '</div></div></div>' +
      (d.actions.length > 1 ? '<h2 class="mt2">More ideas from your agent</h2><div class="grid g3">' + d.actions.slice(1, 4).map((a) => nbaCard(a, false)).join('') + '</div>' : '') +
      '<div class="page-head mt2"><div><h2>Recommended for you</h2><p class="small muted">Ranked by your history, similar shoppers, restock cycles, offers and points campaigns.</p></div><a class="btn" href="#/shop">Browse the store</a></div>' +
      '<div class="pgrid">' + recs.map((r) => LQ.productCard(r, { reason: true })).join('') + '</div>';
    promos.forEach((x) => track(x.campaign_id, 'impression'));
  };

  const naParts = (na) => [na.discount_pct > 0 ? '<b>' + na.discount_pct + '% off</b>' : '', na.bonus_points_pct > 0 ? '<b>' + na.bonus_points_pct + '% extra points</b>' : ''].filter(Boolean).join(' and ');

  // ----- product awareness campaigns: "Featured for you" cards, with view/click/cart tracking -----
  const track = (camp, kind) => LQ.api('/customer/events', { body: { campaign_id: Number(camp), kind: kind, surface: 'home' } }).catch(() => {});
  function promoCards(list) {
    if (!list.length) return '';
    return list.map((x) => { const p = x.product; return '<div class="card promo-card mt"><div class="big">' + esc(p.emoji) + '</div><div><span class="chip brand">✨ Featured for you</span><h3 style="margin:6px 0 2px;display:block">' + esc(x.headline) + '</h3>' +
      (x.message ? '<p class="small muted">' + esc(x.message) + '</p>' : '') + '<div class="small"><b>' + esc(p.name) + '</b> <span class="muted">' + esc(p.unit || '') + '</span> · <span class="price">' + inr(p.price) + '</span>' +
      (p.mrp > p.price ? ' <span class="mrp">' + inr(p.mrp) + '</span>' : '') + '</div></div><div class="cta row"><button class="btn primary" data-act="promoAddCart" data-camp="' + x.campaign_id + '" data-id="' + p.id + '">Add to cart</button>' +
      '<button class="btn" data-act="promoOpen" data-camp="' + x.campaign_id + '" data-name="' + esc(p.name) + '">See in store</button></div></div>'; }).join('');
  }
  LQ.actions.promoAddCart = (el) => { track(el.dataset.camp, 'click'); track(el.dataset.camp, 'add_to_cart'); LQ.addToCart(Number(el.dataset.id), 1); };
  LQ.actions.promoOpen = (el) => { track(el.dataset.camp, 'click'); shop.category = ''; shop.q = el.dataset.name; shop.page = 1; location.hash = '#/shop'; };

  function nbaCard(a, big) {
    const o = a.offer;
    return '<div class="card nba"><div class="row between"><span class="chip brand">' + (big ? '🤖 Your next best action' : '💡 ' + esc(a.title)) + '</span></div>' +
      (big ? '<h2 style="margin-top:8px">' + esc(a.title) + '</h2>' : '') + '<p>' + esc(a.message) + '</p>' +
      '<div class="row" style="margin:8px 0">' + a.why.map((w) => '<span class="chip">' + esc(w) + '</span>').join('') + '</div>' +
      (a.items.length ? '<div class="minis">' + a.items.slice(0, big ? 4 : 2).map(LQ.mini).join('') + '</div>' : '') +
      '<div class="row" style="margin-top:12px">' +
      (o ? (o.allowed ? '<button class="btn primary" data-act="activateOffer" data-code="' + esc(a.code) + '">Activate ' + o.multiplier + 'x points for ' + o.days + ' days</button>' :
        '<span class="chip warn">Offer unavailable right now</span>') : '') +
      '<a class="btn" href="#/' + esc(a.cta.route) + '">' + esc(a.cta.label) + '</a></div></div>';
  }
  LQ.actions.activateOffer = async (el) => {
    el.disabled = true;
    try { const r = await LQ.api('/customer/offers/activate', { body: { code: el.dataset.code } }); LQ.toast(r.multiplier + 'x points activated until ' + LQ.date(r.expires_at), 'good'); V.home(LQ.$('#view')); }
    catch (e) { el.disabled = false; throw e; }
  };

  // ================= SHOP =================
  const shop = { category: '', q: '', sort: 'relevance', promo: false, stock: false, page: 1 };
  V.shop = async function (root) {
    root.innerHTML =
      '<div class="page-head"><div><h1>Store</h1><p>' + LQ.state.cats.reduce((a, c) => a + c.count, 0) + ' products across ' + LQ.state.cats.length + ' categories</p></div></div>' +
      '<div class="card flat mb"><div class="row"><div class="grow" style="min-width:220px"><input type="search" id="shopQ" placeholder="Search rice, laptop, shampoo…" value="' + esc(shop.q) + '" data-input="shopSearch" aria-label="Search products"></div>' +
      '<select class="inline" data-change="shopSort" aria-label="Sort">' + [['relevance', 'Top picks'], ['price_asc', 'Price: low to high'], ['price_desc', 'Price: high to low'], ['discount', 'Biggest discount'], ['rating', 'Rating']].map((o) => '<option value="' + o[0] + '"' + (shop.sort === o[0] ? ' selected' : '') + '>' + o[1] + '</option>').join('') + '</select>' +
      '<label class="small row" style="gap:6px"><input type="checkbox" data-change="shopPromo"' + (shop.promo ? ' checked' : '') + '> On offer</label>' +
      '<label class="small row" style="gap:6px"><input type="checkbox" data-change="shopStock"' + (shop.stock ? ' checked' : '') + '> In stock</label></div></div>' +
      '<div class="catchips mb"><button class="chipbtn' + (!shop.category ? ' on' : '') + '" data-act="shopCat" data-cat="">All</button>' +
      LQ.state.cats.map((c) => '<button class="chipbtn' + (shop.category === c.key ? ' on' : '') + '" data-act="shopCat" data-cat="' + c.key + '">' + c.emoji + ' ' + esc(c.name) + '</button>').join('') + '</div>' +
      '<div id="shopResults">' + LQ.loading() + '</div>';
    loadShop();
  };
  async function loadShop() {
    const box = LQ.$('#shopResults');
    if (!box) return;
    const qs = new URLSearchParams({ category: shop.category, q: shop.q, sort: shop.sort, page: shop.page, promo: shop.promo ? 1 : 0, in_stock: shop.stock ? 1 : 0 });
    const filtered = shop.category || shop.q || shop.promo || shop.stock || shop.sort !== 'relevance';
    const [r, recs] = await Promise.all([LQ.api('/products?' + qs), !filtered && shop.page === 1 ? LQ.api('/customer/recommendations?k=6') : Promise.resolve([])]);
    LQ.register(r.items); LQ.register(recs);
    box.innerHTML = (recs.length ? '<h2>Picked for you</h2><div class="pgrid mb">' + recs.map((x) => LQ.productCard(x, { reason: true })).join('') + '</div><h2 class="mt2">All products</h2>' : '') +
      (r.items.length ? '<div class="pgrid">' + r.items.map((x) => LQ.productCard(x)).join('') + '</div>' : '<div class="empty card">No products match. Try a different search.</div>') +
      LQ.pagerHtml(r.page, r.pages, 'shopPage');
  }
  LQ.actions.shopCat = (el) => { shop.category = el.dataset.cat; shop.page = 1; V.shop(LQ.$('#view')); };
  LQ.actions.shopPage = (el) => { shop.page = Number(el.dataset.page); loadShop().then(() => window.scrollTo({ top: 0, behavior: 'smooth' })); };
  LQ.changes.shopSort = (el) => { shop.sort = el.value; shop.page = 1; loadShop(); };
  LQ.changes.shopPromo = (el) => { shop.promo = el.checked; shop.page = 1; loadShop(); };
  LQ.changes.shopStock = (el) => { shop.stock = el.checked; shop.page = 1; loadShop(); };
  LQ.inputs.shopSearch = LQ.debounce((el) => { shop.q = el.value.trim(); shop.page = 1; loadShop().catch(LQ.fail); }, 300);
  LQ.shopSetSearch = (q) => { shop.q = q; shop.category = ''; shop.page = 1; };

  // ================= CART / CHECKOUT =================
  const cart = (LQ.cart = { redeem: 0 });
  cart.open = () => { LQ.$('#cartWrap').classList.add('open'); cart.refresh(); };
  cart.close = () => LQ.$('#cartWrap').classList.remove('open');
  cart.items = () => Object.values(LQ.state.cart).map((l) => ({ product_id: l.id, qty: l.qty }));
  cart.refresh = async function () {
    const body = LQ.$('#cartBody'), foot = LQ.$('#cartFoot');
    const lines = Object.values(LQ.state.cart);
    if (!lines.length) { body.innerHTML = '<div class="empty">Your cart is empty.<br><a href="#/shop" data-act="closeCart">Start shopping</a></div>'; foot.innerHTML = ''; return; }
    body.innerHTML = lines.map((l) => '<div class="cline"><div style="font-size:26px">' + esc(l.emoji) + '</div><div class="grow"><div class="small" style="font-weight:600">' + esc(l.name) + '</div><div class="xs muted">' + esc(l.unit) + ' · ' + inr(l.price) + '</div></div>' +
      '<div class="stepper"><button data-act="qty" data-id="' + l.id + '" data-d="-1" aria-label="Decrease">−</button><span>' + l.qty + '</span><button data-act="qty" data-id="' + l.id + '" data-d="1" aria-label="Increase">+</button></div>' +
      '<div class="small right" style="min-width:64px"><b>' + inr(l.price * l.qty) + '</b></div></div>').join('');
    foot.innerHTML = '<div class="muted small">Calculating…</div>';
    let q;
    try { q = await LQ.api('/cart/quote', { body: { items: cart.items(), redeem_points: cart.redeem } }); }
    catch (e) {
      if (cart.redeem) { cart.redeem = 0; return cart.refresh(); }
      foot.innerHTML = '<div class="notice bad">' + esc(e.message) + '</div>'; return;
    }
    LQ.state.quote = q;
    const bd = q.points_breakdown;
    foot.innerHTML =
      '<div class="sumrow"><span>Subtotal</span><span>' + inr(q.subtotal) + '</span></div>' +
      (q.product_savings ? '<div class="sumrow" style="color:var(--good)"><span>Offer savings included</span><span>' + inr(q.product_savings) + '</span></div>' : '') +
      (q.max_redeem ? '<div class="form-row row mt" style="gap:8px"><div class="grow small"><b>Use points</b> <span class="muted">(you have ' + num(q.points_available) + ', up to ' + num(q.max_redeem) + ' here)</span></div>' +
        '<input type="number" style="width:90px" min="0" max="' + q.max_redeem + '" step="10" value="' + cart.redeem + '" data-change="redeem" aria-label="Points to redeem"><button class="btn sm" data-act="redeemMax">Max</button></div>' : '') +
      (q.new_account_discount ? '<div class="sumrow" style="color:var(--good)"><span>New-account discount (' + q.new_account_offer.discount_pct + '%)</span><span>−' + inr(q.new_account_discount) + '</span></div>' : '') +
      (q.redeem_value ? '<div class="sumrow" style="color:var(--good)"><span>Points discount</span><span>−' + inr(q.redeem_value) + '</span></div>' : '') +
      '<div class="sumrow total"><span>Total</span><span>' + inr(q.total) + '</span></div>' +
      '<div class="notice mt small">You will earn <b>' + num(q.points_estimate) + ' points</b> (' + esc(q.tier) + ' ' + q.multiplier + 'x' + (bd.campaign_bonus ? ', +' + bd.campaign_bonus + ' campaign' : '') + (bd.offer_bonus ? ', +' + bd.offer_bonus + ' offer' : '') + (bd.new_account ? ', +' + bd.new_account + ' new-account bonus' : '') + ')' +
      (q.welcome_bonus ? ' plus <b>' + q.welcome_bonus + ' welcome bonus</b>' : '') + '.' +
      (q.new_account_offer && q.new_account_offer.bonus_points_pct > 0 && !bd.new_account ? '<br><span class="xs">Your ' + q.new_account_offer.bonus_points_pct + '% extra points applies to the points you earn. This basket is too small to add a whole extra point.</span>' : '') +
      (q.may_need_review ? '<br><span class="xs">Large orders are checked by our team before points are credited.</span>' : '') + '</div>' +
      '<button class="btn primary lg mt" style="width:100%;justify-content:center" data-act="checkout">Place order · ' + inr(q.total) + '</button>';
  };
  LQ.actions.openCart = () => cart.open();
  LQ.actions.closeCart = () => cart.close();
  LQ.actions.qty = (el) => {
    const l = LQ.state.cart[el.dataset.id]; if (!l) return;
    l.qty += Number(el.dataset.d);
    if (l.qty <= 0) delete LQ.state.cart[el.dataset.id];
    else if (l.stock != null && l.qty > l.stock) { l.qty = l.stock; LQ.toast('Only ' + l.stock + ' in stock', 'bad'); }
    LQ.saveCart(); cart.refresh();
  };
  LQ.changes.redeem = (el) => { cart.redeem = Math.max(0, parseInt(el.value || '0', 10) || 0); cart.refresh(); };
  LQ.actions.redeemMax = () => { cart.redeem = LQ.state.quote.max_redeem; cart.refresh(); };
  LQ.actions.checkout = async (el) => {
    el.disabled = true; el.textContent = 'Placing order…';
    const before = LQ.state.me.tier;
    try {
      const r = await LQ.api('/checkout', { body: { items: cart.items(), redeem_points: cart.redeem } });
      LQ.state.cart = {}; cart.redeem = 0; LQ.saveCart(); cart.close();
      const o = r.order, pending = o.points_status === 'pending';
      await LQ.refreshMe();
      LQ.modal('<div class="center"><div style="font-size:54px">🎉</div><h2>Order #' + o.id + ' placed</h2><p class="muted">Total paid ' + inr(o.total_paid) + '</p>' + (o.new_account_discount ? '<p class="small" style="color:var(--good)">You saved ' + inr(o.new_account_discount) + ' with your new-account offer' + (o.new_account_points ? ' and earned ' + o.new_account_points + ' extra points' : '') + '.</p>' : '') + '</div>' +
        '<div class="notice ' + (pending ? 'warn' : 'good') + ' mt">' + (pending ? '<b>' + num(o.points_earned) + ' points are pending.</b> Your order was flagged for a quick check (' + esc((o.flags[0] || {}).text || 'review') + '). They will be added once approved.'
          : '<b>' + num(o.points_earned) + ' points added</b> to your balance.') + '</div>' +
        (r.tier.tier !== before ? '<div class="notice good mt">🏅 You are now <b>' + esc(r.tier.tier) + '</b>!</div>' : '') +
        '<div class="row mt" style="justify-content:center"><a class="btn primary" href="#/orders" data-act="closeModal">View orders</a><button class="btn" data-act="closeModal">Keep shopping</button></div>');
      if (location.hash.startsWith('#/home') || location.hash.startsWith('#/shop')) LQ.route();
    } catch (e) { el.disabled = false; el.textContent = 'Place order'; cart.refresh(); throw e; }
  };

  // ================= ORDERS =================
  V.orders = async function (root) {
    root.innerHTML = LQ.loading();
    const orders = await LQ.api('/customer/orders');
    root.innerHTML = '<div class="page-head"><div><h1>My orders</h1><p>' + orders.length + ' most recent orders</p></div></div>' +
      (orders.length ? orders.map((o) => '<div class="card mb"><div class="row between"><div><b>Order #' + o.id + '</b> <span class="muted small">· ' + LQ.datetime(o.created_at) + '</span></div><div class="row">' + LQ.statusChip(o.status) + LQ.pointsStatus(o.points_status) + '</div></div>' +
        '<div class="mt small">' + o.items.map((i) => '<span class="chip" style="margin:2px">' + esc(i.emoji) + ' ' + esc(i.name) + ' ×' + i.qty + '</span>').join('') + '</div>' +
        '<div class="row between mt"><div class="small muted">Paid <b style="color:var(--ink)">' + inr(o.total_paid) + '</b>' + (o.new_account_discount ? ' · <span style="color:var(--good)">new-account discount −' + inr(o.new_account_discount) + '</span>' : '') + (o.points_redeemed ? ' · used ' + o.points_redeemed + ' pts' : '') + ' · earned <b style="color:var(--ink)">' + num(o.points_earned) + ' pts</b>' +
        (o.points_status === 'pending' && o.flags.length ? '<div class="xs" style="color:var(--warn)">Review reason: ' + esc(o.flags.map((f) => f.text).join('; ')) + '</div>' : '') + '</div>' +
        (o.status === 'placed' ? '<button class="btn sm bad" data-act="cancelOrder" data-id="' + o.id + '">Cancel order</button>' : '') + '</div></div>').join('') : '<div class="empty card">No orders yet. <a href="#/shop">Start shopping</a></div>');
  };
  LQ.actions.cancelOrder = async (el) => {
    if (!confirm('Cancel order #' + el.dataset.id + '? Stock is released and any points are reversed.')) return;
    await LQ.api('/customer/orders/' + el.dataset.id + '/cancel', { method: 'POST' });
    LQ.toast('Order cancelled'); await LQ.refreshMe(); V.orders(LQ.$('#view'));
  };

  // ================= REWARDS =================
  V.rewards = async function (root) {
    root.innerHTML = LQ.loading();
    const d = await LQ.api('/customer/points');
    const s = d.summary, t = d.tier;
    const kind = { earn: 'Order points', bonus: 'Bonus', redeem: 'Redeemed', expire: 'Expired', reverse: 'Reversed', refund: 'Refund' };
    root.innerHTML = '<div class="page-head"><div><h1>Rewards</h1><p>Your points, tier and how they work</p></div></div>' +
      '<div class="grid g4"><div class="card kpi"><div class="label">Active points</div><div class="value">' + num(s.active) + '</div><div class="small muted">worth ' + inr(s.active) + '</div></div>' +
      '<div class="card kpi"><div class="label">Pending approval</div><div class="value">' + num(s.pending) + '</div><div class="small muted">credited once approved</div></div>' +
      '<div class="card kpi"><div class="label">Expiring in 30 days</div><div class="value">' + num(s.expiring_30d) + '</div><div class="small muted">' + (s.expiring_30d_date ? 'from ' + LQ.date(s.expiring_30d_date) : 'none soon') + '</div></div>' +
      '<div class="card kpi"><div class="label">Lifetime earned</div><div class="value">' + num(s.lifetime_earned) + '</div><div class="small muted">' + num(s.lifetime_redeemed) + ' redeemed</div></div></div>' +
      '<div class="card mt"><h3>Tier ladder ' + LQ.tier(t.tier) + '</h3><p class="small muted mb">Tiers are based on approved spend in the last 12 months. Redeeming points never lowers your tier.</p><div class="ladder">' +
      d.tiers.map((x, i) => '<div class="rung' + (x.name === t.tier ? ' on' : '') + '"><div class="row between">' + LQ.tier(x.name) + '<b>' + x.multiplier + 'x</b></div><div class="small muted" style="margin-top:6px">From ' + inr(x.min_spend) + ' / year</div><ul>' + (x.perks || []).map((p) => '<li>' + esc(p) + '</li>').join('') + '</ul></div>').join('') + '</div>' +
      (t.next_tier ? '<div class="mt">' + LQ.progress(t.progress) + '<p class="small muted">' + inr(t.gap_to_next) + ' more to reach ' + esc(t.next_tier) + '</p></div>' : '') +
      (t.at_risk ? '<div class="notice warn mt">Your ' + esc(t.tier) + ' status drops to ' + esc(t.drop_to) + ' on ' + LQ.date(t.drop_date) + ' unless you spend ' + inr(t.retain_gap) + ' more.</div>' : '') + '</div>' +
      (d.campaigns.length ? '<div class="card mt"><h3>Points campaigns running now</h3><div class="row">' + d.campaigns.map((c) => LQ.chip('⚡ ' + c.name + ' until ' + LQ.date(c.ends_at), 'brand')).join('') + '</div></div>' : '') +
      '<div class="card mt"><h3>Points history</h3><div class="tablewrap"><table><thead><tr><th>Date</th><th>Activity</th><th class="right">Points</th><th>Status</th><th>Expires</th></tr></thead><tbody>' +
      d.ledger.map((l) => '<tr><td class="nowrap">' + LQ.date(l.created_at) + '</td><td>' + kind[l.kind] + (l.order_id ? ' <span class="muted">· order #' + l.order_id + '</span>' : '') + '<div class="xs muted">' + esc(l.note || '') + '</div></td>' +
        '<td class="right" style="font-weight:700;color:' + (l.points < 0 ? 'var(--bad)' : 'var(--good)') + '">' + (l.points > 0 ? '+' : '') + l.points + '</td><td>' + (l.status === 'active' ? '' : LQ.chip(l.status, l.status === 'pending' ? 'warn' : 'bad')) +
        '</td><td class="small muted">' + (l.remaining > 0 && l.expires_at ? LQ.date(l.expires_at) : '') + '</td></tr>').join('') + '</tbody></table></div></div>';
  };

  // ================= ASSISTANT =================
  const chat = { msgs: [] };
  V.assistant = async function (root) {
    if (!chat.msgs.length) chat.msgs.push({ from: 'bot', text: 'Hi! I am your loyalty assistant. Ask me about your points, tier, offers or what to buy.', suggestions: ['What is my tier?', 'Recommend something', 'Any offers for me?', 'When do my points expire?'], products: [] });
    root.innerHTML = '<div class="page-head"><div><h1>Assistant</h1><p>Ask about points, tiers, offers and products</p></div></div><div class="card"><div class="chat"><div class="msgs" id="msgs"></div>' +
      '<div class="row mt"><input type="text" id="chatIn" class="grow" placeholder="Type a question…" aria-label="Message" autocomplete="off"><button class="btn primary" data-act="send">Send</button></div></div></div>';
    paintChat();
    LQ.$('#chatIn').addEventListener('keydown', (e) => { if (e.key === 'Enter') LQ.actions.send(); });
  };
  function paintChat() {
    const box = LQ.$('#msgs'); if (!box) return;
    box.innerHTML = chat.msgs.map((m, i) => '<div class="msg ' + m.from + '">' + esc(m.text).replace(/\n/g, '<br>') + '</div>' +
      (m.products && m.products.length ? '<div class="minis" style="max-width:640px">' + m.products.map((p) => { LQ.register([p]); return LQ.mini(p) + (p.reason ? '' : ''); }).join('') + '</div>' : '') +
      (m.suggestions && i === chat.msgs.length - 1 ? '<div class="row">' + m.suggestions.map((s) => '<button class="chip brand" style="border:0;cursor:pointer" data-act="ask" data-q="' + esc(s) + '">' + esc(s) + '</button>').join('') + '</div>' : '')).join('');
    box.scrollTop = box.scrollHeight;
  }
  async function ask(text) {
    if (!text.trim()) return;
    chat.msgs.push({ from: 'me', text: text }); paintChat();
    const r = await LQ.api('/customer/chat', { body: { message: text } });
    chat.msgs.push({ from: 'bot', text: r.reply, products: r.products, suggestions: r.suggestions }); paintChat();
  }
  LQ.actions.send = async () => { const i = LQ.$('#chatIn'); const t = i.value; i.value = ''; await ask(t); };
  LQ.actions.ask = (el) => ask(el.dataset.q);
})();
