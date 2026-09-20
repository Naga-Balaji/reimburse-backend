# Reimburse — Architecture & System Design

*Structured for a video walkthrough. Each section = ~1 minute of screen time.*

---

## 0. The Pattern — Code Organization Mirrors Product Thinking

Before diving into features, the *shape* of the codebase itself is a product decision. Every folder answers a **product question**, not a technical one. If a reviewer opens the repo, they should see how you *think* — not just what you built.

```
reimburse/
│
├── 📁 core/                  ⟵  "What is our business?"
│   │                             All domain logic lives here. If you understand
│   │                             this folder, you understand the product.
│   │
│   ├── 📄 models.py             The vocabulary: TravelRequest, Claim, Item, Approval
│   │                             (what things exist and how they relate)
│   │
│   ├── 📄 parsers.py            "How do we read the messy inbox?"
│   │                             Deterministic email extractors — Uber, MakeMyTrip,
│   │                             hotel invoices, duplicate detection, noise filtering
│   │
│   ├── 📄 llm.py                "When rules aren't enough, ask an advisor"
│   │                             OpenRouter client + AI insights + rule-based fallback
│   │
│   ├── 📄 views.py              "Who is allowed to do what, and when?"
│   │                             Role-scoped querysets + workflow transitions
│   │
│   ├── 📄 serializers.py        "What shape does data take when it leaves the server?"
│   │                             Auto-computed totals, cached fields, nested details
│   │
│   └── 📄 urls.py               "What are the verbs of our system?"
│                                 /submit, /approve, /disburse, /hold, /follow_up, /ai_insights
│
├── 📁 config/                ⟵  "Framework plumbing" — deliberately thin
│                                 Settings, top-level routes, WSGI. This is Django, not the product.
│
├── 📁 frontend/src/
│   │
│   ├── 📁 api/               ⟵  "How does the client talk to the server?"
│   │                             Single Axios instance, Token injected once,
│   │                             401 → auto-logout. All calls go through here.
│   │
│   └── 📁 components/        ⟵  "What are the surfaces our users touch?"
│       │
│       │  ── Role-scoped dashboards ──
│       ├── 🎭 Dashboard.jsx           Router: renders the right dashboard per role
│       ├── 🎭 AdminDashboard.jsx      Admin = oversight (see everything, act on nothing)
│       │
│       │  ── Claim lifecycle ──
│       ├── 📋 ClaimsList.jsx          List view, auto-filtered by route context
│       ├── 📋 ClaimDetail.jsx         The workhorse — stepper, sub-tree, expense table
│       ├── 📋 ImportInbox.jsx         "Read my emails" — the 25-min pain reducer
│       │
│       │  ── Travel Request lifecycle ──
│       ├── ✈️  TravelRequests.jsx      List + filter + card view
│       ├── ✈️  TravelRequestDetail.jsx Full detail + Finance communication thread
│       ├── ✈️  NewTravelRequest.jsx    Pre-trip planning form
│       │
│       │  ── Finance actions (money moving) ──
│       ├── 💰 AdvanceReview.jsx       Full-context page (not one-click) — money is hard to reverse
│       │
│       │  ── Approver aids ──
│       ├── 🧠 AIInsights.jsx          "AI advises, human decides" with cache indicator
│       ├── 👤 EmployeeContext.jsx     Past history, spending patterns, plan-vs-actual
│       ├── 📎 ProofViewer.jsx         See the actual receipt inline — trust with own eyes
│       │
│       │  ── Admin surfaces ──
│       ├── 📖 PolicyView.jsx          "What are the rules the system enforces?"
│       ├── 🌳 OrganizationView.jsx    Hierarchy tree — who approves whom
│       │
│       │  ── Shell ──
│       ├── 🖼️  Layout.jsx              Dark navy sidebar, role-based nav
│       └── 🔐 Login.jsx               Split-panel with quick-login for all 5 roles
│
├── 📁 pack/                  ⟵  "The spec — read this before anything else"
│   ├── sample_emails/            15 real emails from one trip (the actual test data)
│   ├── receipts/                 2 image bills (hotel + dinner)
│   ├── expense_policy.md         The rules the app must enforce
│   ├── PROBLEM_STATEMENT.md      The ask
│   └── employee_master.csv       People and hierarchy
│
├── 📄 populate_sample_data.py   ⟵ "Give me a clean demo state in one command"
├── 📄 ARCHITECTURE.md           ⟵ You are here (product thinking)
├── 📄 SUBMISSION_NOTE.md        ⟵ Design decisions with why-not tradeoffs
├── 📄 DEPLOYMENT.md             ⟵ How to ship this (Railway + Vercel, 30 min)
└── 📄 README.md                 ⟵ Get running in 5 min
```

### Why this structure is a product statement

**1. `core/` is thin and coherent** — 4 files (`models`, `parsers`, `llm`, `views`) capture the entire business. If a new engineer joined, they'd be productive in a day. This is a signal that we understood the domain before writing code.

**2. `parsers.py` is a first-class citizen** — not buried in `utils/`. Reading the inbox IS the product; it deserves its own file. If we'd hidden it in `helpers/email.py`, it would tell a different story about what we thought mattered.

**3. `llm.py` is separated from `views.py`** — AI is an *integration*, not the *core*. Business logic in views works even if the LLM is down. This mirrors the "AI as advisor, not decider" product call — even in file structure.

**4. `components/` is grouped by user journey, not by widget type** — files for "claim lifecycle" sit next to each other, not scattered by "modals/", "tables/", "forms/". A reviewer reading the codebase can walk the user journey by scrolling.

**5. `AdminDashboard.jsx` exists but has no approve buttons** — the code structure enforces the product principle. An admin who wanted to approve a claim would have to *write new code*. That's intentional friction.

**6. `AdvanceReview.jsx` is its own file (not a modal in Dashboard)** — because financial actions deserve dedicated surface. Modal-vs-page is a product decision, and the file split reflects it.

**7. `pack/` is preserved in-repo** — normally you'd `.gitignore` sample data. Here it stays because it *is* the spec. The reviewer should always be able to go back to source.

### The rule I follow

> **If a folder name is a noun, it's a data structure. If it's a verb or a user concern, it's product thinking.**

Compare:
- `utils/` (bad — bucket for miscellaneous) vs `parsers/` (good — a concrete capability)
- `helpers/api.js` (bad — vague) vs `api/client.js` (good — one job)
- `services/emailService.js` (bad — over-engineered) vs `core/parsers.py` (good — direct)

Every file in this repo tries to answer *one product question*. If two files would answer the same question, they get merged. If one file tries to answer three questions, it gets split.

**That's what "product mindset in the code" means — the shape of the codebase should teach the reader what the product is.**

---

## 1. The Problem (30 sec)

The problem statement said: employees spend 25–30 minutes assembling a paper form from scattered emails after every trip, errors slip in, and payments take weeks. **Three pain points:**

1. Manual data assembly from a messy inbox
2. Errors from hand entry
3. No visibility into where money is

**Critical read of the spec:** the pack contains 15 emails — Uber duplicates, hotel folios with mixed reimbursable/non-reimbursable items, colleague forwards, promo noise, failed payments. **The pack IS the spec.** Anyone who ignored the emails and just built a form missed the point.

---

## 2. Product Decisions — Why These Features (2 min)

Every feature is a call about a tradeoff. Here's what I chose and why:

### 2.1 Hybrid parser (not pure LLM)
- **Deterministic pattern parsers first** — Uber, MakeMyTrip, hotel invoices all have predictable templates. Regex hits 100% on the sample pack, runs in <100ms, costs nothing.
- **LLM fallback opt-in** for unknown senders via OpenRouter.
- **Why not just LLM?** Speed, cost, reliability. LLM is for the *16th* format we haven't seen.

### 2.2 AI as advisor, not decider
- AI Verification Assistant surfaces recommendations to managers/finance, but humans always click Approve.
- **Rule-based fallback** produces the same shape when LLM is rate-limited.
- **Why?** Accountability. If AI auto-approves and it's wrong, who's responsible?

### 2.3 Two-stage approval (TR pre-trip, Claim post-trip)
- Pre-trip: manager approves the *plan* (dates, estimated cost, advance)
- Post-trip: manager approves the *actuals* (real receipts, policy compliance)
- **Why?** Reviewer's job genuinely differs. Pre-trip you're validating intent; post-trip you're auditing spending.

### 2.4 Tiered approval (per policy §2)
- ₹25k: manager only
- ₹25–75k: + HoD
- ₹75k–2L: + Div Head
- Above ₹2L: + MD
- Applied to *both* Travel Requests AND Expense Claims
- **Why?** Amount-based accountability. Small trips shouldn't need MD sign-off; big ones shouldn't slip through.

### 2.5 Advance disbursement as separate audit track
- Finance actions form a distinct sub-tree under the main approval flow
- Advance disbursement, final settlement, recovery — each is a distinct event with amount, reference, timestamp, who
- **Why?** Two accountability chains: business (approve *whether* to pay) + finance (record *what was paid*).

### 2.6 Employee↔Finance communication thread
- When Finance holds an advance, employee sees the reason + can reply
- **Why?** Silent holds erode trust. Every held advance has a two-way audit trail.

### 2.7 Full-context review pages (not one-click buttons)
- Disbursing advance → dedicated page with outstanding advances, historical variance, policy cap, editable amount
- **Why?** Financial actions are hard to reverse. Notification-level UX is dangerous for money movement.

### 2.8 Proof document inline viewer
- Every expense item can attach `.eml`, `.pdf`, images, `.txt`
- Approvers click the pill → full-screen viewer opens (native `<img>` for images, iframe for PDFs, header-parsed view for `.eml`)
- **Why?** Text references like "hotel_invoice_1188.png" are useless. Approver has to trust the number blindly. Now they can verify with their eyes.

### 2.9 AI insights caching with content-hash invalidation
- LLM call is expensive (60s on free tier). Cache result per claim.
- Invalidate cache when claim content changes (signal on ExpenseItem save)
- **Why?** Manager, HoD, and Finance all view the same claim — no reason to run LLM 3 times.

### 2.10 Admin as policy owner, not operational role
- Admin has visibility (system overview, policy view, org tree)
- No "approve" buttons on admin dashboard
- **Why?** Operational workflow must not depend on admin being available. Admins govern policy; they don't process transactions.

---

## 3. Tech Stack (30 sec)

| Layer | Choice | Reason |
|-------|--------|--------|
| Backend | **Django 6.1 + DRF** | Fastest way to expose a domain with role-based permissions. Model changes → migrations → API in minutes. |
| Frontend | **React 18 + Tailwind CSS** | Component reuse. Tailwind for Atlassian-style density without a design system. |
| Font/Theme | **Inter + Atlassian palette** | Financial-grade tabular numerals; enterprise SaaS aesthetic. |
| Database | **SQLite (dev), PostgreSQL-ready** | One-file dev; switch DATABASE_URL to Postgres for prod. |
| LLM | **OpenRouter multi-model** | DeepSeek V4 Flash (free) primary, `openrouter/free` fallback. Anthropic key would upgrade quality/speed. |
| Auth | **DRF Token auth** | Simple bearer token in `Authorization` header. No CSRF, no session state. |
| File storage | **Django FileField, local** | S3 for prod (one config change). |
| State mgmt | **React hooks + localStorage** | No Redux — small enough not to need it. |
| Routing | **React Router v6** | Standard. |

**Why not TypeScript?** 48-hour prototype. Type safety is worth it at scale, not at velocity.

**Why not Next.js?** No server-side rendering needed. This is an internal tool, not a public site.

---

## 4. System Design (2 min)

### 4.1 High-level architecture

```
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│  React SPA       │  REST   │  Django + DRF    │   ORM   │   SQLite /       │
│  (localhost:3000)│ ──────► │  (localhost:8000)│ ──────► │   PostgreSQL     │
│                  │  JSON   │                  │         │                  │
│  - Layout        │         │  - Viewsets      │         │  - UserProfile   │
│  - Dashboard/*   │ ◄────── │  - Serializers   │         │  - TravelRequest │
│  - ClaimDetail   │  Token  │  - Parsers       │         │  - ExpenseClaim  │
│  - AIInsights    │         │  - LLM client    │         │  - ExpenseItem   │
│  - AdvanceReview │         │                  │         │  - Approval      │
└──────────────────┘         └────────┬─────────┘         │  - TRApproval    │
                                      │                    └──────────────────┘
                                      ▼
                            ┌──────────────────┐
                            │  OpenRouter      │
                            │  (Claude/DeepSeek│
                            │   etc.)          │
                            └──────────────────┘
```

### 4.2 Request flow

**Example: Employee submits claim**
```
1. Employee UI → POST /api/expense-claims/{id}/submit/
2. Django auth middleware validates Token
3. ExpenseClaimViewSet.submit action:
   - Validates ownership + status='draft'
   - Sets status='submitted', submitted_at=now
   - ApprovalWorkflowHelper computes required levels from net amount
   - Creates Approval records (pending)
4. Signal fires (ExpenseItem save/delete) → invalidates AI insights cache
5. Response: updated claim JSON
6. React re-fetches, UI updates workflow stepper
```

**Example: Manager opens claim (with AI insights)**
```
1. Manager UI → GET /api/expense-claims/{id}/ai_insights/
2. ExpenseClaimViewSet.ai_insights action:
   - Checks role (manager|finance|admin)
   - Computes claim.content_hash (items + amounts + status)
   - If cached hash matches → returns cached JSON instantly
3. Otherwise:
   - Gathers context (claim, past history, peer baseline, policy)
   - Calls OpenRouter with prompt + JSON schema
   - LLM returns structured recommendation
   - If LLM fails → rule-based fallback with same shape
   - Cache with new hash
4. UI renders panel: recommendation, checks, employee behavior, attention items
```

### 4.3 Role-based access

Not per-endpoint permissions — done at the **queryset level**:
- Employee: `.filter(employee=user)` — sees only own
- Manager: `own | direct_reports | indirect_reports_of_subordinate_managers`
- Finance: `.filter(status__in=['approved', 'paid', 'rejected'])` — never sees drafts
- Admin: `.all()`

This means one line of code = policy enforcement. No leaks.

### 4.4 Policy enforcement

**Not in views, in the model.** `ExpenseItem.save()` calls `apply_policy()`:
```python
def apply_policy(self):
    if self.category == 'lodging':
        # Check per-night limit for city tier
        # Split excess into disallowed_amount
```
So every code path — API, admin, seed script — gets the same validation.

### 4.5 Approval workflow computation

Dynamic per claim value (policy §2):
```python
def get_required_approval_levels(amount):
    if amount <= 25000: return ['manager', 'finance']
    if amount <= 75000: return ['manager', 'dept_head', 'finance']
    if amount <= 200000: return ['manager', 'dept_head', 'div_head', 'finance']
    return ['manager', 'dept_head', 'div_head', 'md_ceo', 'finance']
```

When employee submits → these Approval records get created.
Each approver's role is determined by `employee.reporting_manager` chain, NOT static assignment. So a manager creating their own claim automatically goes to their HoD (per policy §2.2).

### 4.6 Caching strategy

**AI Insights** are content-hashed. When ExpenseItem changes → post_save signal invalidates cache:
```python
@receiver([post_save, post_delete], sender=ExpenseItem)
def invalidate_ai_insights_on_item_change(sender, instance, **kwargs):
    claim = instance.claim
    claim.invalidate_ai_cache()
```
So the LLM only re-runs when the claim actually changes.

---

## 5. Database Structure (2 min)

### 5.1 Entity Relationship Diagram

```
                           User (Django built-in)
                             │
                             │ 1:1
                             ▼
                       UserProfile
                       ┌────────────────┐
                       │ role           │
                       │ department     │
                       │ reporting_mgr ─┼──────┐
                       └────────────────┘      │
                             │                 │ hierarchy
                             │                 │ (self-ref)
                             │ 1:N             │
                             ▼                 │
                       TravelRequest ◄─────────┘
                       ┌────────────────────┐
                       │ destination        │
                       │ from/to dates      │
                       │ estimated_cost     │
                       │ advance_requested  │
                       │ status             │
                       │ ── advance track ──│
                       │ advance_disbursed_amount / at / by / ref
                       │ advance_review_note / at / by       (finance hold)
                       │ advance_follow_up_note / at / by    (employee reply)
                       └──────┬─────────────┘
                              │ 1:N          │ 1:N
                              ▼              ▼
                       TRApproval    ExpenseClaim
                       ┌───────────┐ ┌──────────────────┐
                       │ level     │ │ status           │
                       │ decision  │ │ submitted_at     │
                       │ approver  │ │ ai_insights_data │  (cached JSON)
                       │ remarks   │ │ ai_insights_hash │
                       └───────────┘ └──────┬───────────┘
                                            │ 1:N          │ 1:N
                                            ▼              ▼
                                     ExpenseItem      Approval
                                     ┌─────────────┐ ┌───────────┐
                                     │ category    │ │ level     │
                                     │ amount      │ │ decision  │
                                     │ description │ │ approver  │
                                     │ proof_file  │ │ remarks   │
                                     │ is_disallow │ │ decided_at│
                                     │ disallowed_$│ └───────────┘
                                     │ claimed_$   │
                                     │ (lodging:)  │
                                     │ nights,city │
                                     └─────────────┘
```

### 5.2 Each table's job

| Table | What it holds | Cascade behaviour |
|-------|--------------|-------------------|
| `UserProfile` | role, dept, `reporting_manager` FK (self-ref for hierarchy) | CASCADE with User; reporting_manager SET_NULL |
| `TravelRequest` | trip plan + advance disbursement audit + finance/employee thread | CASCADE with employee; disbursed_by SET_NULL (audit) |
| `TRApproval` | per-TR approval level (manager, dept_head, div_head, md_ceo) | CASCADE with TR; approver SET_NULL |
| `ExpenseClaim` | settlement claim + AI insights cache | CASCADE with TR + employee |
| `ExpenseItem` | line items with proof file + policy validation | CASCADE with claim |
| `Approval` | per-claim approval level (manager, dept_head, div_head, md_ceo, finance) | CASCADE with claim; approver SET_NULL |

### 5.3 FK design principle

- **CASCADE** for data ownership (delete a claim → its items go too)
- **SET_NULL** for audit references (delete a user → keep their approval history, just null the "who")

This preserves audit integrity even under user offboarding.

### 5.4 Cached fields on ExpenseClaim

Instead of running the LLM on every view:
- `ai_insights_data` (JSONField) — the last LLM response
- `ai_insights_generated_at` (DateTime)
- `ai_insights_content_hash` (SHA256 of claim state)

On request: compute current hash → if matches stored → return cached. If not → call LLM → store new.

### 5.5 Property vs field

Some things are computed properties (not columns):
- `total_claimed`, `total_disallowed`, `net_reimbursable` — computed from ExpenseItems
- `advance_drawn` — returns disbursed_amount if disbursed, else 0
- `payable_recoverable` — computes net - advance, splits into payable vs recoverable

Why? Single source of truth. If items change, totals recompute automatically.

---

## 6. Code Structure (What Lives Where) (2 min)

```
expense-reimbursement/
├── config/                              ⟵ Django project settings
│   ├── settings.py                        · installed apps, CORS, REST, MEDIA
│   └── urls.py                            · top-level URL routes
│
├── core/                                ⟵ Main app (all business logic)
│   ├── models.py                          · UserProfile, TravelRequest, TRApproval,
│   │                                        ExpenseClaim, ExpenseItem, Approval
│   │                                        + property methods + policy validation
│   │                                        + signal for cache invalidation
│   │
│   ├── serializers.py                     · DRF serializers that shape API JSON
│   │                                        + computed fields (totals, advance status,
│   │                                        travel_request_detail nested)
│   │
│   ├── views.py                           · ViewSets + custom actions
│   │                                        · IsEmployee/IsManager/IsFinance/IsAdmin
│   │                                        · role-scoped querysets
│   │                                        · endpoints: submit, approve, reject, return,
│   │                                          verify_and_pay, disburse_advance,
│   │                                          hold_advance, follow_up_advance,
│   │                                          ai_insights (cached), employee_context,
│   │                                          advance_context, import/emails
│   │                                        · admin_overview, admin_policy, admin_organization
│   │
│   ├── parsers.py                         · Deterministic .eml parsers
│   │                                        · Uber, MakeMyTrip flight/hotel, hotel invoice
│   │                                        · noise/duplicate/colleague detection
│   │
│   ├── llm.py                             · OpenRouter client (multi-model + fallback)
│   │                                        · gather_claim_context()
│   │                                        · generate_ai_insights() with rule-based fallback
│   │
│   ├── urls.py                            · /api/ routes (router.register + custom)
│   ├── admin.py                           · Django admin registration
│   └── migrations/                        · 7 migrations (models evolution)
│
├── frontend/src/
│   ├── App.js                            ⟵ Router with protected routes
│   ├── index.css                         ⟵ Tailwind entry + Inter font import
│   ├── api/client.js                     ⟵ Axios instance with Token interceptor
│   │                                        · 401 → auto-logout
│   │
│   └── components/
│       ├── Layout.jsx                     · Dark navy sidebar, role-based nav
│       ├── Login.jsx                      · Split-screen with quick-login buttons
│       │
│       ├── Dashboard.jsx                  · Router: Employee/Manager/Finance dashboards
│       ├── AdminDashboard.jsx             · Admin: system stats, holds, breakdowns
│       ├── PolicyView.jsx                 · Admin: policy sections
│       ├── OrganizationView.jsx           · Admin: hierarchical tree
│       │
│       ├── TravelRequests.jsx             · TR list (cards, filterable, clickable)
│       ├── TravelRequestDetail.jsx        · TR detail: approval chain, advance status,
│       │                                    Finance communication thread
│       ├── NewTravelRequest.jsx           · Create TR form
│       │
│       ├── ClaimsList.jsx                 · Claims table (auto-filters by route)
│       ├── ClaimDetail.jsx                · Workflow stepper, sub-tree, related TR link,
│       │                                    expense table, action modals (approve/reject/
│       │                                    return/verify), Add Expense modal
│       │
│       ├── ImportInbox.jsx                · Upload .eml → parsed preview with parser
│       │                                    badges → checkbox selection → add to claim
│       ├── ProofViewer.jsx                · Modal viewer for images / PDFs / .eml
│       │                                    (with header parsing) / text
│       │
│       ├── AdvanceReview.jsx              · Full-context Finance disbursement page
│       │                                    + Cancel-with-note modal
│       ├── EmployeeContext.jsx            · Approver's employee-history panel
│       └── AIInsights.jsx                 · AI recommendation panel with cache indicator
│
├── populate_sample_data.py               ⟵ Seed script (users, TRs, historical claims)
├── requirements.txt                       ⟵ Django, DRF, CORS, dotenv, requests
├── .env                                   ⟵ OPENROUTER_API_KEY (gitignored)
├── ARCHITECTURE.md                        ⟵ This file
├── SUBMISSION_NOTE.md                     ⟵ Design decisions writeup
└── README.md                              ⟵ Setup + usage
```

**Key insight for the video:** the backend is *small*. `models.py` + `views.py` + `parsers.py` + `llm.py` = the whole business system. Everything else is Django plumbing.

---

## 7. Deployment (1 min)

### Recommended: **Backend on Railway, Frontend on Vercel** (both free tier)

**Backend (Railway) — 5 minutes:**
```bash
# 1. Push repo to GitHub
git remote add origin git@github.com:you/reimburse.git
git push -u origin main

# 2. On Railway (railway.app):
#    - New Project → Deploy from GitHub → select your repo
#    - Railway auto-detects Django, provisions PostgreSQL
#    - Set env vars:
#         OPENROUTER_API_KEY=<your key>
#         OPENROUTER_MODEL=deepseek/deepseek-v4-flash-0731:free
#         DJANGO_SETTINGS_MODULE=config.settings
#         DEBUG=False
#         ALLOWED_HOSTS=your-app.railway.app
#    - Add build command: pip install -r requirements.txt && python manage.py migrate && python manage.py collectstatic --noinput
#    - Add start command: gunicorn config.wsgi
#    - Deploy → get URL like https://reimburse-production.up.railway.app
```

**Frontend (Vercel) — 3 minutes:**
```bash
# 1. In frontend/, set the API URL:
echo "REACT_APP_API_URL=https://reimburse-production.up.railway.app" > .env.production

# 2. Update api/client.js to use it:
# baseURL: process.env.REACT_APP_API_URL + '/api'

# 3. Deploy:
cd frontend
npx vercel
# → asks a few questions → deploys → gives you URL
```

**One-time backend changes for production:**

Add to `config/settings.py`:
```python
import os, dj_database_url

DEBUG = os.environ.get('DEBUG', 'False') == 'True'
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',')

if os.environ.get('DATABASE_URL'):
    DATABASES = {'default': dj_database_url.parse(os.environ.get('DATABASE_URL'))}

CORS_ALLOWED_ORIGINS = [
    'https://your-frontend.vercel.app',
    'http://localhost:3000',
]

# Static files with WhiteNoise
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
```

Add to `requirements.txt`:
```
gunicorn
whitenoise
dj-database-url
psycopg2-binary
```

**For media files (proof documents)** in production, either:
- Use Django's default (works for demo — files stored on server disk, will reset on Railway redeploy)
- Or add django-storages + AWS S3 (production-ready)

---

## 8. Video Presentation Outline (10-12 min)

**Suggested flow:**

| Minute | Topic | Screen |
|--------|-------|--------|
| 0:00 | Hook: "48 hours, real messy problem, here's what I built" | Login page |
| 0:30 | Problem: 25 min, errors, follow-ups + show the 15 sample emails | pack/sample_emails folder |
| 1:30 | Product decisions overview (bullet through the 10 calls) | ARCHITECTURE.md §2 |
| 3:00 | Live demo — employee flow (import from inbox, submit) | App |
| 5:00 | Live demo — manager flow (AI insights, approve) | App |
| 7:00 | Live demo — finance flow (advance review, disburse, hold with note) | App |
| 8:30 | Live demo — admin flow (system overview, policy view, org tree) | App |
| 9:30 | Architecture: tech stack + system diagram | ARCHITECTURE.md §4 |
| 10:30 | DB design | ARCHITECTURE.md §5 diagram |
| 11:30 | Code structure walk-through | IDE / ARCHITECTURE.md §6 |
| 12:30 | Deployment (mention Railway + Vercel) + what's next | ARCHITECTURE.md §7 |

**Speaking tips:**
- Lead with the *why* not the *what* — reviewers will remember the reasoning
- Show the messy sample emails BEFORE showing the parsed result — the contrast is the pitch
- When showing AI insights, pause and let them see the recommendation appear
- On the sub-tree feature: literally say "notice this is a separate track — this is how finance operations should be modeled"

---

## 9. What I'd Do With More Time

Documented in `SUBMISSION_NOTE.md` — but for video, mention:
1. Email server integration (IMAP polling or Gmail add-on) — replaces manual .eml upload
2. OCR for image receipts — extract dinner-bill amount from the PNG rather than manual entry
3. Feedback loop: every "return with remarks" becomes training data for the AI advisor
4. Slack/Teams approvals — approve without opening the app
5. Full workflow builder (what the demo video showed) — admins can customize policy per-company

---

*This document is the video-prep artifact. Read it, internalise the reasoning behind each choice, and the walkthrough will feel natural.*
