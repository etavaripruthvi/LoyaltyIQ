# LoyaltyIQ

**AI-Powered Customer Purchase Behaviour and Product Recommendation Agent**

Authors: Etavari Pruthvi Teja (25WU0201075), Galeti Varshalatha (25WU0201079), Samuel Jebaraj (25WU0201246), Gangula Chaitanya (25WU0201322). See [AUTHORS.md](AUTHORS.md).

An AI-powered customer behaviour and product recommendation prototype with a tiered loyalty programme, a central admin console and ten distinct shopper personas. It is a working web app: customers browse a store of about 1,200 products, buy things, and watch their points, tier and recommendations change. An admin manages the catalogue, approves points on flagged orders and tunes the rules.

Everything runs on synthetic data with fictional brands. Prices are in rupees. Products use emojis instead of photos.

## Run it on your computer (VS Code)

You need Python 3.10 or newer.

```bash
# 1. Open this folder in VS Code, then open its terminal (Ctrl+`)
python -m venv .venv

# 2. Activate the virtual environment
#    Windows (PowerShell):  .venv\Scripts\Activate.ps1
#    macOS / Linux:         source .venv/bin/activate

# 3. Install and run
pip install -r requirements.txt
python run.py
```

Open <http://localhost:5000>. The first start creates the database and fills it with demo data, which takes a few seconds.

You can also press **F5** in VS Code and choose "LoyaltyIQ: run app". "LoyaltyIQ: reset data and run" wipes the database and builds a fresh one.

Useful options: `python run.py --port 8000`, `python run.py --reset`, `python run.py --debug` (auto-reload while you edit code).

## Log in

One login page for everyone. Every password is `1234`.

| Username | Who |
|---|---|
| `admin` | Admin console |
| `user1` | Divya Rao, **deal-hunter**: discounted staples in frequent small baskets |
| `user2` | Pranav Mehta, **premium shopper**: high-value baskets of premium brands |
| `user3` | Tarun Iyer, **tech enthusiast**: electronics and games in bursts |
| `user4` | Meera Nair, **busy parent**: weekly groceries, dairy, baby and home |
| `user5` | Farhan Qureshi, **fitness fanatic**: sports gear and healthy food monthly |
| `user6` | Tanya Kapoor, **trend follower**: fashion and beauty, many returns |
| `user7` | Gopal Sharma, **festive gifter**: big gift baskets around festivals |
| `user8` | Sana Fernandes, **student**: small low-budget baskets |
| `user9` | Lakshmi Venkat, **lapsed regular**: used to buy often, went quiet |
| `user10` | Nikhil Joshi, **new customer**: one order, tests cold start |

`user11` and up are about 300 background customers with varied behaviour that make the recommender and the dashboards realistic. The login page has a one-click card for each of the first eleven.

## What to try

**As a customer** (for example `user1`, then `user10`)
- **Home**: tier progress, your agent's *next best action*, spending charts, what the AI learned about your shopping style, and recommended products with a plain-language reason on each.
- **Shop**: search, filter by category, offers and stock, add to cart, redeem points, place an order.
- **Sign up**: on the login page choose *New here? Create an account*. A new account gets **10% off and 5% extra points on its first order**, applied automatically at checkout and shown on Home and in the cart. It is used once per account, and it is edited or switched off under Rules.
- After buying, return to Home: recommendations change (you stop being offered things you just bought).
- **Rewards**: tier ladder, points ledger with pending, active and expired points.
- **Assistant**: ask "how many points do I have?", "what should I buy?" or "how do I reach Gold?".

**As admin** (`admin`)
- **Dashboard**: revenue, orders, points liability, churn risk, and the agent's lists (who to win back, who is close to the next tier, whose points expire soon).
- **Approvals**: orders that are large or look risky wait here with the reasons shown. Approve, adjust the points, reject, or act in bulk. Place an order of more than ₹20,000 as a customer to see it arrive.
- **Orders**, **Products** (edit price, stock, visibility inline; add products and new categories), **Customers** (a full Customer 360 page with the agent's reasoning, a bonus-points form and the ledger; add customers with their own login).
- **Segments**: the seven behaviour groups the AI learned (Champion, Loyal, Promising, New, Prospect, At risk, Hibernating) with size, spend, churn risk, favourite categories, a segment-by-tier table and a suggested play for each. Click through to the customers in any group.
- **Promotions**: product awareness (advertising) campaigns. Pick a product, choose the segments and tiers to reach, write a headline, and matching customers see a *Featured for you* card on their Home page. Views, clicks, add-to-carts and attributed purchases are tracked. *Simulate traffic* fills a campaign with clearly labelled illustrative numbers for demos, kept separate from live numbers.
- **Rules**: points rate, redemption limits, tiers, approval mode, offer budget, the **new-account offer** (on/off, discount %, extra points %, optional ₹ cap), recommender weights, points campaigns, admin accounts (add another admin), audit log. Changes apply immediately.
- **AI and personas**: model quality figures, and for each persona what was built in versus what the AI worked out from raw orders.

## How it works

```
Customer portal ─┐                         ┌─ Products, stock, prices
                 ├─ REST API (Flask) ──────┼─ Orders, loyalty ledger, approvals
Admin console ───┘      │                  └─ Rules, campaigns, offers, audit log
                        │
        Analytics → Recommender → Agent → Chat assistant
            (all read from the same SQLite database)
```

- **One central database and one set of services.** The customer portal and the admin console are two clients of the same API, so an admin edit is visible to customers on their next click.
- **Loyalty.** Bronze, Silver, Gold and Platinum, decided by approved spend over the last 12 months. 1 point per ₹100 times the tier multiplier, plus campaign multipliers. Points are an append-only ledger with FIFO redemption and expiry; cancelling or returning an order reverses its points. Only flagged or large orders wait for admin approval, the rest are approved automatically (switchable to "every order" in Rules).
- **Behaviour analytics.** Per-customer features, cadence-aware RFM segments, a 12-month value estimate, and a gradient-boosting churn model trained on time-sliced snapshots. Shopper traits are inferred from orders only; the persona label is never shown to the models.
- **Recommender.** A blend of item-to-item and user-to-user collaborative filtering, content fit, popularity, learned restock timing, discounts, points campaigns and margin, with rules for stock, things you already own and category variety. Every recommendation carries a reason.
- **Agent.** Scores possible actions (welcome, win-back, protect tier, nudge to next tier, expiring points, restock, redeem, discover) and picks the best one per customer. Any points offer is checked against a monthly budget and a per-customer cap.

Measured on the seeded data (see the AI page): the recommender's top 10 contains something the customer later bought for 75% of customers, against 42% for a "most popular items" baseline, and the churn model scores an AUC of about 0.87 on a later time slice. These numbers come from synthetic data that was generated with known behaviour, so they show that the machinery works, not how it would perform on real shoppers.

## Put it on GitHub and make it a live website

GitHub itself only hosts static pages, and this app needs a Python server, so you push the code to GitHub and let a free host run it.

**1. Push to GitHub**
```bash
git init
git add .
git commit -m "LoyaltyIQ prototype"
git branch -M main
git remote add origin https://github.com/<your-username>/loyaltyiq.git
git push -u origin main
```
Create the empty repository on github.com first. The `.gitignore` keeps the local database and virtual environment out. A GitHub Actions workflow runs the tests on every push.

**2a. Deploy on Render (free)**
1. Sign in at render.com with GitHub.
2. **New > Blueprint**, choose your repository. It reads `render.yaml` and sets everything up.
3. Wait for the build. You get a public `https://….onrender.com` address.

**2b. Or use GitHub Codespaces** (no host needed, good for a quick look)
Open the repo on GitHub, **Code > Codespaces > Create**, then run `pip install -r requirements.txt && python run.py`. Codespaces offers to forward port 5000 and gives you a link.

**2c. Or Docker anywhere:** `docker build -t loyaltyiq . && docker run -p 8000:8000 loyaltyiq`.

Things to know about free hosting:
- The free tier **sleeps after inactivity** and takes about half a minute to wake.
- The database lives on the host's temporary disk, so it is **re-created from the seed whenever the app restarts**. Orders and edits made during testing will not survive a restart. That is fine for exploring; for keeping data you would move to a hosted database.
- The app deliberately runs a **single worker**, because SQLite is one file and the recommendation model is held in memory.
- Anyone with the link can log in with `1234`. For a public link, set an `ADMIN_PASSWORD` environment variable in your host's dashboard so strangers cannot use the admin console.

## Configuration (all optional)

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | 5000 locally | Port to listen on |
| `SECRET_KEY` | dev value | Session signing key. Set a random value on any public deployment (Render does this for you) |
| `ADMIN_PASSWORD` | `1234` | Admin password |
| `DEMO_PASSWORD` | `1234` | Password for `user1` and up |
| `N_CUSTOMERS` | 300 | Background customers to generate |
| `REGISTER_LIMIT_PER_HOUR` | 8 | Sign-ups allowed per connection per hour (the new-account offer is worth farming, so this is capped) |
| `SEED` | 42 | Random seed, same seed gives the same data |
| `DATABASE_PATH` / `DATA_DIR` | `data/loyaltyiq.db` | Where SQLite lives |
| `ANTHROPIC_API_KEY` | unset | Turns on the optional Claude layer that rephrases assistant answers. Without it, the built-in rule-based assistant is used |
| `LLM_MODEL` | `claude-sonnet-5-5` | Model for that layer |

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```
49 end-to-end tests cover login and roles, checkout and stock, points earning, redemption and expiry, approvals, cancellation reversals, tier maths, admin edits and their effect on customers, persona-specific recommendations, cold start, offer guardrails and the recommender against its baseline.

## Honest limitations

- The data is synthetic. The personas are built in, so recovering them is a check that the pipeline works, not proof of real-world accuracy.
- The optional Claude layer has not been run against the live API. With no key set (the default) it is not used.
- Awareness-campaign attribution counts a real order for the product after the customer first saw or clicked the ad. It shows association, not proof the ad caused the sale. Simulated traffic is illustrative only.
- New shopper personas and new AI signals are code changes. Customers, categories, products, admins, tiers and campaigns can all be added from the admin console.
- Sign-up has no email or phone verification, so anyone can open accounts and claim the new-account offer. The per-hour limit slows this down but does not stop it. Verify email or phone before a real launch.
- The new-account offer applies once per account and is not given back if the first order is cancelled. The discount lowers the amount the approval and risk checks look at, so a first order just over a threshold can slip under it.
- Tier perks such as free delivery or early access are shown as text but are not enforced by the store.
- There is no payment step, address, delivery tracking or email. Orders are placed instantly and an admin can mark them delivered.
- Login is deliberately minimal for a demo (shared easy passwords, session cookie). Do not reuse this authentication for anything real.
- SQLite with one worker is fine for a handful of testers, not for load.

## Project layout

```
app/
  api.py              REST endpoints (customer and admin)
  services/           loyalty, store, risk, analytics, recommender, agent, categories, segments, awareness
  seed/               catalogue, personas, data generator
  static/             the web UI (index.html, util.js, customer.js, admin.js, admin2.js, main.js, styles.css)
tests/                end-to-end tests
run.py                local dev server
wsgi.py, Procfile     production entry (gunicorn)
render.yaml, Dockerfile, .github/workflows
```
