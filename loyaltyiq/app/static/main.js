/* App shell: login page, navigation, router, cart drawer. */
(function () {
  const LQ = window.LQ, esc = LQ.esc;
  LQ.state.cats = [];

  const CUSTOMER_NAV = [['home', 'Home'], ['shop', 'Shop'], ['orders', 'My orders'], ['rewards', 'Rewards'], ['assistant', 'Assistant']];
  const ADMIN_NAV = [['admin', 'Dashboard'], ['admin/approvals', 'Approvals'], ['admin/orders', 'Orders'], ['admin/products', 'Products'], ['admin/customers', 'Customers'], ['admin/segments', 'Segments'], ['admin/promotions', 'Promotions'], ['admin/rules', 'Rules'], ['admin/ai', 'AI and personas']];

  LQ.refreshMe = async function () {
    LQ.state.me = await LQ.api('/me');
    paintWho();
    return LQ.state.me;
  };

  // Pending approvals badge in the admin nav.
  LQ.refreshBadges = async function () {
    const me = LQ.state.me;
    if (!me || me.role !== 'admin') return;
    try {
      const d = await LQ.api('/admin/approvals');
      const dot = LQ.$('#apprDot');
      if (dot) { dot.textContent = d.items.length > 99 ? '99+' : d.items.length; dot.hidden = !d.items.length; }
    } catch (e) { /* the badge is cosmetic */ }
  };

  function paintWho() {
    const me = LQ.state.me, el = LQ.$('#who');
    if (!el || !me) return;
    el.innerHTML = me.role === 'admin' ? '<span class="badge-role">Admin</span>' :
      LQ.tier(me.tier) + ' <span class="small" style="font-weight:700">' + LQ.num(me.points) + ' pts</span>' + (me.pending_points ? ' <span class="xs muted">(+' + LQ.num(me.pending_points) + ' pending)</span>' : '');
  }

  // ---------- login ----------
  async function renderLogin() {
    LQ.state.me = null;
    LQ.$('#root').innerHTML = '<div class="login-wrap"><section class="login-left"><div style="font-size:44px">🛍️</div><h1>LoyaltyIQ</h1>' +
      '<p style="font-size:17px;opacity:.95">An AI that learns how each customer shops, recommends what they will actually want, and runs a tiered rewards programme.</p>' +
      '<ul style="padding-left:18px"><li>Ten distinct shopper personas, each with their own behaviour</li><li>Recommendations explained in plain language</li><li>Bronze to Platinum tiers with an approval workflow</li><li>An admin console that controls the rules and the data</li></ul>' +
      '<p class="small" style="opacity:.75">Prototype with synthetic data and fictional brands. Prices are in rupees.</p>' +
      '<p class="small" style="opacity:.9;border-top:1px solid rgba(255,255,255,.25);padding-top:14px"><b>AI-Powered Customer Purchase Behaviour and Product Recommendation Agent</b><br>Etavari Pruthvi Teja · Galeti Varshalatha · Samuel Jebaraj · Gangula Chaitanya</p></section>' +
      '<section class="login-right"><div><h2>Sign in</h2><p class="muted small">Every password is <b>1234</b>. Pick a demo account below or type a username.</p></div>' +
      '<form id="loginForm" class="card" autocomplete="off"><div class="grid g2"><div class="form-row"><label class="f" for="lu">Username</label><input id="lu" type="text" placeholder="user1 or admin" autocapitalize="none" required></div>' +
      '<div class="form-row"><label class="f" for="lp">Password</label><input id="lp" type="password" placeholder="1234" required></div></div><div class="row"><button class="btn primary" type="submit">Sign in</button><span id="loginErr" class="small" style="color:var(--bad)"></span></div></form>' +
      '<details class="card" id="regBox"><summary><b>New here? Create an account</b></summary><p id="regPromo" class="small muted" style="margin:8px 0"></p><div class="grid g2">' +
      '<div class="form-row"><label class="f" for="rn_name">Full name</label><input id="rn_name" type="text" maxlength="60" autocomplete="name"></div>' +
      '<div class="form-row"><label class="f" for="rn_city">City (optional)</label><input id="rn_city" type="text"></div>' +
      '<div class="form-row"><label class="f" for="rn_user">Username</label><input id="rn_user" type="text" maxlength="24" autocapitalize="none" autocomplete="off"></div>' +
      '<div class="form-row"><label class="f" for="rn_pw">Password (4+ characters)</label><input id="rn_pw" type="password" autocomplete="new-password"></div></div>' +
      '<p id="regErr" class="small" style="color:var(--bad)"></p><button class="btn primary" type="button" data-act="register">Create account and sign in</button></details>' +
      '<div><h3 class="mb">Demo accounts</h3><div id="demoGrid" class="demo-grid">' + LQ.loading() + '</div></div></section></div>';
    LQ.$('#loginForm').addEventListener('submit', (e) => { e.preventDefault(); doLogin(LQ.$('#lu').value, LQ.$('#lp').value); });
    LQ.api('/welcome-offer').then((w) => {
      const parts = [w.discount_pct > 0 ? w.discount_pct + '% off' : '', w.bonus_points_pct > 0 ? w.bonus_points_pct + '% extra points' : ''].filter(Boolean);
      const box = LQ.$('#regPromo');
      if (box) box.innerHTML = w.enabled && parts.length ? '🎁 New accounts get <b>' + parts.join(' and ') + '</b> on their first order.' : 'Create a free account to start earning loyalty points.';
    }).catch(() => {});
    try {
      const list = await LQ.api('/demo-logins');
      LQ.$('#demoGrid').innerHTML = list.map((d) => '<button type="button" class="demo" data-act="demoLogin" data-quick="' + (d.quick ? 1 : 0) + '" data-u="' + esc(d.username) + '"><b>' + esc(d.name) + '</b><span class="u">' + esc(d.username) + '</span><div class="small" style="color:var(--brand-ink);font-weight:600">' + esc(d.label) + '</div><div class="xs muted">' + esc(d.blurb) + '</div></button>').join('');
    } catch (e) { LQ.$('#demoGrid').innerHTML = '<div class="empty">Could not load demo accounts.</div>'; }
  }
  async function doLogin(u, p) {
    const err = LQ.$('#loginErr');
    if (err) err.textContent = '';
    try {
      LQ.state.me = await LQ.api('/login', { body: { username: u, password: p } });
    } catch (e) { if (err) err.textContent = e.message; else LQ.fail(e); return; }
    LQ.state.cart = {}; LQ.state.products = {};
    location.hash = LQ.state.me.role === 'admin' ? '#/admin' : '#/home';
    await boot();
  }
  LQ.actions.register = async () => {
    const v = (id) => LQ.$('#' + id).value.trim(), err = LQ.$('#regErr');
    err.textContent = '';
    try {
      LQ.state.me = await LQ.api('/register', { body: { name: v('rn_name'), username: v('rn_user'), password: LQ.$('#rn_pw').value, city: v('rn_city') } });
    } catch (e) { err.textContent = e.message; return; }
    LQ.state.cart = {}; LQ.state.products = {};
    location.hash = '#/home';
    await boot();
  };
  LQ.actions.demoLogin = (el) => {
    if (el.dataset.quick === '1') return doLogin(el.dataset.u, '1234');
    LQ.$('#lu').value = el.dataset.u; LQ.$('#lp').value = ''; LQ.$('#lp').focus();
    LQ.toast('The password for this account was changed on this server. Type it in.');
  };
  LQ.actions.logout = async () => { try { await LQ.api('/logout', { body: {} }); } catch (e) { /* already out */ } LQ.state.me = null; location.hash = '#/login'; renderLogin(); };

  // ---------- shell ----------
  function renderShell() {
    const me = LQ.state.me, admin = me.role === 'admin', nav = admin ? ADMIN_NAV : CUSTOMER_NAV;
    LQ.$('#root').innerHTML = '<header class="topbar"><a class="logo" href="' + (admin ? '#/admin' : '#/home') + '"><span>🛍️</span><span>Loyalty<b>IQ</b></span></a>' +
      '<nav class="nav" id="nav" aria-label="Main">' + nav.map((n) => '<a href="#/' + n[0] + '" data-r="' + n[0] + '">' + n[1] + (n[0] === 'admin/approvals' ? '<span class="dot" id="apprDot" hidden></span>' : '') + '</a>').join('') + '</nav>' +
      '<div class="row" style="gap:12px;flex-shrink:0"><span id="who" class="row" style="gap:6px"></span>' +
      (admin ? '' : '<button class="btn" data-act="openCart" aria-label="Open cart">🛒 <span id="cartCount" class="chip brand" hidden>0</span></button>') +
      '<span class="small muted hide-sm">' + esc(me.name) + '</span><button class="btn sm" data-act="logout">Log out</button></div></header>' +
      '<main class="main" id="view"></main>' +
      (admin ? '' : '<div class="drawer-wrap" id="cartWrap"><div class="drawer" role="dialog" aria-label="Shopping cart"><header><h3>Your cart</h3><button class="btn sm" data-act="closeCart" aria-label="Close cart">✕</button></header><div class="body" id="cartBody"></div><footer id="cartFoot"></footer></div></div>');
    paintWho();
    if (!admin) { LQ.loadCart(); LQ.updateCartBadge(); }
  }
  document.addEventListener('mousedown', (e) => { if (e.target.id === 'cartWrap') LQ.cart.close(); });

  // ---------- router ----------
  function highlight(path) {
    document.querySelectorAll('#nav a').forEach((a) => {
      const r = a.dataset.r;
      a.classList.toggle('on', r === 'admin' ? path === 'admin' : path === r || path.startsWith(r + '/'));
    });
  }
  LQ.route = async function () {
    const me = LQ.state.me;
    if (!me) return renderLogin();
    const path = (location.hash.replace(/^#\/?/, '') || (me.role === 'admin' ? 'admin' : 'home')).split('?')[0];
    const parts = path.split('/'), root = LQ.$('#view');
    if (!root) return;
    const admin = me.role === 'admin';
    if (parts[0] === 'login') { location.hash = admin ? '#/admin' : '#/home'; return; }
    if (admin !== (parts[0] === 'admin')) { location.hash = admin ? '#/admin' : '#/home'; return; }
    highlight(path);
    window.scrollTo(0, 0);
    if (LQ.cart && LQ.$('#cartWrap')) LQ.cart.close();
    const A = LQ.views.admin, C = LQ.views.customer;
    const table = admin ? {
      admin: () => A.dashboard(root), 'admin/approvals': () => A.approvals(root), 'admin/orders': () => A.orders(root), 'admin/products': () => A.products(root),
      'admin/customers': () => A.customers(root), 'admin/segments': () => A.segments(root), 'admin/promotions': () => A.promotions(root), 'admin/rules': () => A.rules(root), 'admin/ai': () => A.ai(root),
    } : { home: () => C.home(root), shop: () => C.shop(root), orders: () => C.orders(root), rewards: () => C.rewards(root), assistant: () => C.assistant(root) };
    let fn = table[path];
    if (!fn && admin && parts[1] === 'customers' && parts[2]) fn = () => A.customer360(root, parts[2]);
    if (!fn) { location.hash = admin ? '#/admin' : '#/home'; return; }
    const token = (LQ.route.token = (LQ.route.token || 0) + 1);
    root.innerHTML = LQ.loading();
    try { await fn(); } catch (e) { if (token === LQ.route.token && e.message !== 'Please log in') { root.innerHTML = '<div class="card empty">Something went wrong: ' + esc(e.message) + '<br><button class="btn mt" onclick="LQ.route()">Try again</button></div>'; } }
    if (admin) LQ.refreshBadges();
  };
  window.addEventListener('hashchange', () => { if (LQ.state.me || location.hash !== '#/login') LQ.route(); });

  // ---------- boot ----------
  async function boot() {
    try { LQ.state.me = await LQ.api('/me'); } catch (e) { LQ.state.me = null; }
    if (!LQ.state.me) { renderLogin(); return; }
    try {
      LQ.state.cats = await LQ.api('/categories');
      LQ.state.cats.forEach((c) => { LQ.CAT_COLOR[c.key] = c.color; });
    } catch (e) { LQ.state.cats = []; }
    renderShell();
    LQ.route();
  }
  boot();
})();
