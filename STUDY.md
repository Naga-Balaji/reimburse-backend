# Reimburse — Complete Study Artifact

*Everything in one place: what we were given, what we found in it, what we decided, and how we built it.*

---

# PART A — THE PACK: WHAT WE WERE GIVEN

The problem statement said: *"Read all five files before you write anything. The pack is the specification."*

That's the single most important instruction. Everything below flows from reading the pack carefully.

## A.1 What's in the pack

| File | Type | Size | Purpose |
|------|------|------|---------|
| `PROBLEM_STATEMENT.md` | Prose | Small | The 3 pain points + rules of engagement |
| `expense_policy.md` | Prose | Medium | Nortex NTX-HR-POL-11 Rev 4 — the rules the app must enforce |
| `Travel_Expense_Forms_Template.xlsx` | Excel | Small | Current paper form (2 sheets: Travel Request + Settlement) |
| `employee_master.csv` | CSV | Small | 9 people with roles and reporting hierarchy |
| `sample_emails/` | 15 `.eml` files | Small-medium | One employee's complete inbox for one real trip |
| `receipts/` | 2 `.png` files | Medium | Hotel invoice + dinner bill photos referenced in the emails |

## A.2 The emails — a chronological narrative

The 15 emails are not random samples. They are the **complete lifecycle of one real trip** (Chaitanya Reddy, Pune → Bengaluru, 16–20 Jun 2026), in the order they arrive in a real inbox. That's a deliberate spec choice by the problem setter.

### Pre-trip phase
| # | Email | What it teaches |
|---|-------|-----------------|
| 01 | Chaitanya → Suresh: Travel approval request | **Employees ask manager over email for both approval AND advance in the same message.** Cost, dates, purpose, advance amount all bundled. |
| 02 | Suresh → Chaitanya + Ravi: "Approved" | **Manager's approval is a plain email.** Also warns about the ₹6k/night limit — showing managers already know policy. |
| 03 | Finance SSC → Chaitanya: "Advance ₹20,000 credited, Ref ADV/2026/0619" | **Advance disbursement is a distinct Finance event with its own reference number.** Not the same as claim payment. Also imposes 7-day settlement window. |
| 04 | MakeMyTrip: Flight e-ticket | **Flights are booked centrally on a corporate card ("Nortex Industries Ltd").** Not claimable by employee. |
| 05 | MakeMyTrip: Hotel voucher | **Booking voucher ≠ final invoice.** The employee should claim from the actual hotel invoice at checkout, not this. |

### During-trip phase
| # | Email | What it teaches |
|---|-------|-----------------|
| 06 | Uber receipt 1 (Baner → Pune Airport) | Personal HDFC card — claimable. |
| 07 | Uber receipt 2 (BLR Airport → Hotel) | Same pattern, different route. |
| 08 | Uber: **"Payment failed"** | **Not a receipt.** System should not include this in claim. |
| 09 | Uber receipt 3 (Vertex Tech → Hotel) | The successful retry of email 08. |
| 10 | Uber: **"Fwd: Your Wednesday trip"** | **Same content as email 09, forwarded to self.** Duplicate — must dedupe. |
| 11 | Chaitanya → Chaitanya: "Dinner bill 18 Jun" with PNG attachment | **Self-forwarded with attachment.** Amount is only in the image — parser can extract email metadata but not the amount. Category: business entertainment, 4 attendees noted. |
| 12 | Keys Prime Hotel: **Tax Invoice** with PNG attachment | **Critical.** The folio contains: Room ₹17,250 + Laundry ₹450 + Mini bar ₹380 + In-room dining ₹1,120 + CGST/SGST ₹2,304. **Reimbursable = Room + GST. Non-reimbursable = Laundry + Mini bar + In-room dining.** Must be *split*, not silently dropped. |

### Post-trip phase (noise)
| # | Email | What it teaches |
|---|-------|-----------------|
| 13 | Deepa Nair → Chaitanya: "Fwd: My Chennai trip Uber" | **Colleague trying to sneak their expense into someone else's claim.** Different rider name ("Deepa"), different city (Chennai), different date (12 May). Must reject. |
| 14 | MakeMyTrip Offers: "30% OFF" | Promotional noise. Not a receipt. |
| 15 | Uber receipt (Pune Airport → Baner) | Return trip. Legitimate expense. |

### The full arithmetic (what the correct claim looks like)

| Category | Amount | Notes |
|----------|--------|-------|
| Lodging (room) | ₹17,250 | Reimbursable |
| Lodging (GST on room) | ₹2,304 | Reimbursable (per policy §3.1) |
| Transport (4 Ubers) | ₹3,559.04 | 1,415 + 743 + 172 + 1,229 |
| Entertainment (dinner) | ₹4,000 | Manual entry (amount in image) — flag: >₹2k needs HoD prior approval |
| **Claimed total** | **₹27,113.04** | |
| Laundry disallowed | ₹450 | Non-reimbursable (from hotel folio) |
| Mini bar disallowed | ₹380 | Non-reimbursable |
| In-room dining disallowed | ₹1,120 | Non-reimbursable |
| **Net reimbursable** | **₹27,113.04** | Same as claimed — non-reimb already excluded above |
| Advance drawn | ₹20,000 | From email 03 |
| **Payable to employee** | **₹7,113.04** | Net – Advance |

---

## A.3 Patterns identified

### Pattern 1: Same-sender = identical template
- **All 5 Uber emails** follow the exact same layout: "Thanks for riding, <name>" → "Total INR <amount>" → date → Pickup/Drop → Payment
- **MakeMyTrip flights and hotels** each follow their own template
- **The hotel invoice** has a consistent line-item structure with double-spaced amounts

**Consequence:** deterministic pattern parsers work at 100% accuracy on the sample pack. Regex, not LLM, is the right primary tool.

### Pattern 2: The noise is structured too
- Duplicates: forwarded receipts have "Fwd:" in subject or "Forwarded message" in body
- Failed payments: "Payment failed" in subject or "could not charge" in body
- Promo: from `offers@` addresses, contain "unsubscribe", "sale", "% off"
- Colleague forwards: contain "Fwd:" and the rider name differs from the current employee

**Consequence:** noise detection is also rule-based. We wrote 4 lightweight classifiers instead of an ML noise filter.

### Pattern 3: Hotel folios are the trap
- Everything looks reimbursable (all itemised, all on one bill, all totalled with GST) — but 3 of 6 lines are policy-disallowed
- Employees filling forms manually miss these lines *because they're used to just taking the invoice total*

**Consequence:** the parser must split the folio, mark disallowed items with the reason, and pass room+GST as the reimbursable portion. Silent dropping would violate policy §3.1 ("Tariff in excess of the limit is not reimbursable and must be shown as a disallowed amount, not omitted").

### Pattern 4: Two distinct approval moments, not one
- Email 02 = manager approves the *trip* (before receipts exist)
- Excel Settlement Form § "Approval & Finance Processing" = manager + finance approve the *actual expenses* (after receipts exist)

**Consequence:** the app needs two separate approval flows on two separate objects (`TravelRequest` and `ExpenseClaim`), not a single monolithic workflow.

### Pattern 5: Advance is its own audit event
- Email 03 (advance disbursed) has its own reference `ADV/2026/0619`, is issued by Finance SSC, and appears BEFORE the trip
- Nowhere in the emails does the advance get "settled" — that happens later at claim time

**Consequence:** advance disbursement and claim settlement are TWO Finance events. Our data model records both distinctly (`TravelRequest.advance_disbursed_at` + `ExpenseClaim.status='paid'`) and our UI shows them as two branches under the main workflow (the sub-tree pattern).

### Pattern 6: The 25-minute pain isn't the form — it's the assembly
- The Excel Settlement Form is 50 fields. Filling it takes maybe 10 min if you *already know* the numbers.
- The 25 minutes is spent *hunting through the inbox*, matching receipts to categories, subtracting non-reimbursables, deduplicating.

**Consequence:** the killer feature is Import from Inbox, not a nicer form. A prettier form would save maybe 5 min; ingesting the inbox saves 20+.

### Pattern 7: Policy has both hard rules and soft rules
- **Hard:** lodging over ₹6k/night is disallowed. Non-reimbursable list is absolute.
- **Soft:** business entertainment > ₹2,000 "requires prior HoD approval" — but that approval isn't part of the app; it's an email that should have happened *before* the meal.

**Consequence:** hard rules go into `apply_policy()` (auto-enforced). Soft rules become AI Insights attention items ("this expense may not have prior approval — verify before approving").

---

## A.4 What the pack tells us about personas

Only ONE person's inbox is shown (Chaitanya). But five personas are implied:

| Persona | Evidence in pack | What they need from the app |
|---------|------------------|----------------------------|
| **Employee** | Chaitanya's inbox | Reduce assembly time; know where money is |
| **Reporting Manager** | Suresh's approval email (02) | Fast approve/reject; see policy context |
| **Head of Department** | Meera in employee_master, `Meera Krishnan, Head of Department - Sales` | Same as manager, but only for claims >₹25k |
| **Finance** | "Finance Shared Services" in email 03, `Ravi Menon, Manager - Finance Shared Services` in employee master | Disburse advance; verify + release settlement |
| **MD** | Nandita Shah, `Managing Director` in employee master | Sign off on >₹2L or international; system oversight |

**Consequence:** the app has 4 role-scoped dashboards + admin oversight. Each dashboard shows only what that persona needs to *do*, not everything they *could* see.

---

## A.5 What the pack tells us about the company

Small but important cultural signals:

- **Policy is version-controlled** ("NTX-HR-POL-11 Rev 4 Effective 01 Apr 2026") — Nortex is process-mature
- **Cost centres are used** ("CE110") — they do internal accounting; claims tie back to cost centres
- **Payment run dates are fixed** ("10th and 25th of each month") — batch processing, not real-time
- **Manager notes are professional** ("Approved. Please keep the hotel within the 6000/night limit for Bengaluru, the last few claims have been over.") — managers know policy, will push back on repeat offenders

**Consequence:** the app should feel like enterprise SaaS (Atlassian-esque), not a startup tool. Dark navy sidebar, Inter font, tabular numerals, uppercase section labels. Not gradients and emoji.

---

## A.6 Product decisions derived directly from the pack

Each row: an observation → the decision it forced.

| Observation from pack | Decision |
|-----------------------|----------|
| 15 emails are one worked example | Build for the messy inbox, not a clean form |
| Uber/MakeMyTrip templates are identical | Deterministic parsers first, LLM as fallback |
| Hotel folio mixes reimbursable + disallowed | Split at parse time; never silently drop |
| Email 10 is a duplicate of 09 | Dedupe by (amount, date, route) |
| Email 13 is a colleague forward | Detect by rider-name mismatch |
| Email 08 is a failed payment | Filter subject/body for "payment failed" |
| Emails 01, 02, 03 are pre-trip; 06–15 are during/post | Two-stage approval: TR before, Claim after |
| Advance has its own ref, is a separate Finance event | Model advance disbursement as its own audit track (sub-tree in stepper) |
| Policy §2.2 says approvers can't approve own claim | Level detection uses `employee.reporting_manager`, skips self |
| Policy §2.3 allows "return with remarks" | Claim status can go back to draft with reason |
| Policy tier caps (₹25k, ₹75k, ₹2L) | Dynamic approval chain based on amount |
| Manager knows policy, pushes back on limits | Approver panel must show policy checks + past history |
| Payment runs are on 10th/25th | Finance queue view groups pending settlements |
| Company is process-mature | Enterprise UI (dark sidebar, Inter font, no emoji) |

**This is the crux.** Every feature we built maps back to a specific line or pattern in the pack. Nothing is generic "features I thought would be cool."

---

# PART B — ARCHITECTURE

*(Everything below is what we built based on the analysis above.)*

## 0. The Pattern — Code Organization Mirrors Product Thinking

Before diving into features, the *shape* of the codebase itself is a product decision. Every folder answers a **product question**, not a technical one.

```
reimburse/
│
├── 📁 core/                  ⟵  "What is our business?"
│   │                             All domain logic lives here. If you understand
│   │                             this folder, you understand the product.
│   │
│   ├── 📄 models.py             The vocabulary: TravelRequest, Claim, Item, Approval
│   ├── 📄 parsers.py            "How do we read the messy inbox?"
│   ├── 📄 llm.py                "When rules aren't enough, ask an advisor"
│   ├── 📄 views.py              "Who is allowed to do what, and when?"
│   ├── 📄 serializers.py        "What shape does data take when it leaves the server?"
│   └── 📄 urls.py               "What are the verbs of our system?"
│
├── 📁 config/                ⟵  "Framework plumbing" — deliberately thin
│
├── 📁 frontend/src/
│   │
│   ├── 📁 api/               ⟵  "How does the client talk to the server?"
│   │
│   └── 📁 components/        ⟵  "What are the surfaces our users touch?"
│       │  ── Role-scoped dashboards ──
│       ├── 🎭 Dashboard.jsx           Router: renders the right dashboard per role
│       ├── 🎭 AdminDashboard.jsx      Admin = oversight
│       │
│       │  ── Claim lifecycle ──
│       ├── 📋 ClaimsList.jsx
│       ├── 📋 ClaimDetail.jsx
│       ├── 📋 ImportInbox.jsx         The 25-min pain reducer
│       │
│       │  ── Travel Request lifecycle ──
│       ├── ✈️  TravelRequests.jsx
│       ├── ✈️  TravelRequestDetail.jsx
│       ├── ✈️  NewTravelRequest.jsx
│       │
│       │  ── Finance actions ──
│       ├── 💰 AdvanceReview.jsx       Full-context page (not one-click)
│       │
│       │  ── Approver aids ──
│       ├── 🧠 AIInsights.jsx
│       ├── 👤 EmployeeContext.jsx
│       ├── 📎 ProofViewer.jsx
│       │
│       │  ── Admin surfaces ──
│       ├── 📖 PolicyView.jsx
│       ├── 🌳 OrganizationView.jsx
│       │
│       │  ── Shell ──
│       ├── 🖼️  Layout.jsx
│       └── 🔐 Login.jsx
│
├── 📁 pack/                  ⟵  "The spec — read this before anything else"
│
├── 📄 populate_sample_data.py   ⟵ Clean demo state in one command
├── 📄 STUDY.md                  ⟵ You are here
├── 📄 ARCHITECTURE.md           ⟵ Same as Part B here
├── 📄 SUBMISSION_NOTE.md        ⟵ Design decisions
├── 📄 DEPLOYMENT.md             ⟵ Ship it (Railway + Vercel, 30 min)
└── 📄 README.md                 ⟵ Get running in 5 min
```

**The rule:** *If a folder name is a noun, it's a data structure. If it's a verb or a user concern, it's product thinking.*

## 1. The Problem

Three pain points from the problem statement:
1. Manual data assembly from a messy inbox (25 min)
2. Errors from hand entry
3. No visibility into where money is

The pack is the spec — anyone who ignored the emails missed the point.

## 2. Product Decisions

### 2.1 Hybrid parser (not pure LLM)
- Deterministic patterns first — hits 100% on the pack, runs in <100ms
- LLM fallback opt-in for unknown senders
- Why not just LLM? Speed, cost, reliability

### 2.2 AI as advisor, not decider
- AI recommends, humans approve
- Rule-based fallback when LLM is unavailable
- Why? Accountability — if AI auto-approves and it's wrong, who's responsible?

### 2.3 Two-stage approval
- Pre-trip: manager approves the plan
- Post-trip: manager approves actuals
- Reviewer's job genuinely differs at each stage

### 2.4 Tiered approval (per policy §2)
- ₹25k / ₹75k / ₹2L / above → different escalation chains
- Applied to both TR and Claim

### 2.5 Advance disbursement as separate audit track
- Finance actions are their own sub-tree under the main workflow
- Two accountability chains: business (approve whether) + finance (record what was paid)

### 2.6 Employee↔Finance communication thread
- When Finance holds an advance, employee sees the reason + can reply
- Silent holds erode trust

### 2.7 Full-context review pages (not one-click)
- Advance disbursement opens a dedicated page with outstanding advances, historical variance, editable amount
- Financial actions deserve context, not notifications

### 2.8 Proof document inline viewer
- Every expense item can attach `.eml`, `.pdf`, images
- Approvers verify with their eyes, not blind trust

### 2.9 AI insights caching with content-hash invalidation
- LLM call is expensive (60s on free tier). Cache per claim.
- Invalidate on ExpenseItem save/delete signal

### 2.10 Admin as policy owner, not operational role
- Admin has visibility (system overview, policy view, org tree)
- No "approve" buttons — operational workflow can't depend on admin availability

## 3. Tech Stack

| Layer | Choice | Reason |
|-------|--------|--------|
| Backend | Django 6.1 + DRF | Fastest domain-first API with role permissions |
| Frontend | React 18 + Tailwind | Component reuse, dense enterprise UI |
| Font/Theme | Inter + Atlassian palette | Financial-grade tabular numerals |
| DB | SQLite dev, PostgreSQL-ready | One-file dev; switch DATABASE_URL for prod |
| LLM | OpenRouter multi-model | DeepSeek V4 Flash (free), fallback available |
| Auth | DRF Token auth | Bearer token, no CSRF/session complexity |
| Storage | Django FileField | S3 for prod (one config change) |
| State | React hooks + localStorage | No Redux — small enough not to need it |

## 4. System Design

### 4.1 Architecture diagram

```
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│  React SPA       │  REST   │  Django + DRF    │   ORM   │   SQLite /       │
│  :3000           │ ──────► │  :8000           │ ──────► │   PostgreSQL     │
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
                            │  (multi-model)   │
                            └──────────────────┘
```

### 4.2 Request flow examples

**Employee submits claim:**
```
1. UI → POST /api/expense-claims/{id}/submit/
2. Django auth middleware validates Token
3. ExpenseClaimViewSet.submit:
   - validates ownership + status='draft'
   - sets status='submitted', submitted_at=now
   - ApprovalWorkflowHelper.get_required_levels(net_amount)
   - creates Approval records (pending)
4. Signal fires (ExpenseItem save) → invalidates AI insights cache
5. Response: updated claim JSON
6. React re-fetches, workflow stepper updates
```

**Manager opens claim (with AI insights):**
```
1. UI → GET /api/expense-claims/{id}/ai_insights/
2. ExpenseClaimViewSet.ai_insights:
   - checks role (manager|finance|admin)
   - computes content_hash (items + amounts + status)
   - if cached hash matches → returns cached JSON instantly
3. Otherwise:
   - gathers context (claim + history + peer baseline + policy)
   - calls OpenRouter with prompt + JSON schema
   - LLM returns structured recommendation
   - if LLM fails → rule-based fallback (same shape)
   - cache with new hash
4. UI renders: recommendation, checks, employee behavior, attention items
```

### 4.3 Role-based access

Enforced at the **queryset level**, not per-endpoint:
- Employee: `.filter(employee=user)`
- Manager: `own | direct_reports | indirect_reports_of_subordinate_managers`
- Finance: `.filter(status__in=['approved', 'paid', 'rejected'])`
- Admin: `.all()`

One line of code = policy enforcement.

### 4.4 Policy enforcement

**In the model, not in views.** `ExpenseItem.save()` calls `apply_policy()`:
```python
def apply_policy(self):
    if self.category == 'lodging':
        # Check per-night limit for city tier
        # Split excess into disallowed_amount
```
Every code path (API, admin, seed script) gets the same validation.

### 4.5 Approval workflow computation

Dynamic per claim value (policy §2):
```python
def get_required_approval_levels(amount):
    if amount <= 25000: return ['manager', 'finance']
    if amount <= 75000: return ['manager', 'dept_head', 'finance']
    if amount <= 200000: return ['manager', 'dept_head', 'div_head', 'finance']
    return ['manager', 'dept_head', 'div_head', 'md_ceo', 'finance']
```

Each approver's identity comes from `employee.reporting_manager` chain, NOT static assignment.

### 4.6 Caching strategy

Content-hashed AI insights. When ExpenseItem changes → post_save signal invalidates:
```python
@receiver([post_save, post_delete], sender=ExpenseItem)
def invalidate_ai_insights_on_item_change(sender, instance, **kwargs):
    claim = instance.claim
    claim.invalidate_ai_cache()
```
LLM only re-runs when the claim actually changes.

## 5. Database Structure

### 5.1 ER Diagram

```
                           User (Django built-in)
                             │ 1:1
                             ▼
                       UserProfile
                       ┌────────────────┐
                       │ role           │
                       │ department     │
                       │ reporting_mgr ─┼──────┐ (self-ref hierarchy)
                       └────────────────┘      │
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
                       │ advance_disbursed_amount/at/by/ref
                       │ advance_review_note/at/by       (finance hold)
                       │ advance_follow_up_note/at/by    (employee reply)
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
                                     │ nights,city │  (lodging)
                                     └─────────────┘
```

### 5.2 Table responsibilities

| Table | What it holds |
|-------|--------------|
| `UserProfile` | role, dept, reporting_manager FK (self-ref) |
| `TravelRequest` | trip plan + advance disbursement audit + finance/employee thread |
| `TRApproval` | per-TR approval per level (manager/dept_head/div_head/md_ceo) |
| `ExpenseClaim` | settlement claim + AI insights cache |
| `ExpenseItem` | line items with proof file + policy validation |
| `Approval` | per-claim approval per level |

### 5.3 FK design principle

- **CASCADE** for data ownership (delete a claim → its items go too)
- **SET_NULL** for audit references (delete a user → keep their approval history, null the "who")

Preserves audit integrity under user offboarding.

### 5.4 Cached fields

`ExpenseClaim` has three fields dedicated to caching AI insights:
- `ai_insights_data` (JSONField) — last LLM response
- `ai_insights_generated_at` (DateTime)
- `ai_insights_content_hash` (SHA256 of claim state)

### 5.5 Computed properties (not columns)

- `total_claimed`, `total_disallowed`, `net_reimbursable` — sum from items
- `advance_drawn` — returns disbursed amount, else 0
- `payable_recoverable` — computes net − advance

Single source of truth.

## 6. Code Structure (Detailed)

```
expense-reimbursement/
├── config/                              ⟵ Django project settings
│   ├── settings.py                        · installed apps, CORS, REST, MEDIA
│   └── urls.py                            · top-level URL routes
│
├── core/                                ⟵ Main app (all business logic)
│   ├── models.py                          · 6 models + property methods + policy
│   │                                        validation + signal for cache invalidation
│   ├── serializers.py                     · DRF serializers with computed fields
│   ├── views.py                           · ViewSets + custom actions:
│   │                                        submit, approve, reject, return,
│   │                                        verify_and_pay, disburse_advance,
│   │                                        hold_advance, follow_up_advance,
│   │                                        ai_insights (cached), employee_context,
│   │                                        advance_context, admin_overview,
│   │                                        admin_policy, admin_organization,
│   │                                        import_emails, create_items_from_import
│   ├── parsers.py                         · Uber, MakeMyTrip flight/hotel,
│   │                                        hotel invoice, noise/duplicate/colleague
│   ├── llm.py                             · OpenRouter (multi-model + fallback),
│   │                                        AI insights generator, rule-based fallback
│   ├── urls.py                            · /api/ routes
│   ├── admin.py                           · Django admin registration
│   └── migrations/                        · 7 migrations
│
├── frontend/src/
│   ├── App.js                             · Router with protected routes
│   ├── index.css                          · Tailwind entry + Inter font
│   ├── api/client.js                      · Axios with Token interceptor + auto-logout
│   └── components/                        · (see Part B section 0 above)
│
├── pack/                                  ⟵ The spec — sample_emails, receipts, policy
├── populate_sample_data.py                ⟵ Seed script
├── requirements.txt                       ⟵ Django, DRF, CORS, dotenv, requests
├── .env                                   ⟵ OPENROUTER_API_KEY (gitignored)
└── STUDY.md / ARCHITECTURE.md /
    SUBMISSION_NOTE.md / DEPLOYMENT.md / README.md
```

## 7. Deployment

**Recommended: Railway (backend + Postgres) + Vercel (frontend)** — both free tier, ~30 min setup.

See `DEPLOYMENT.md` for the step-by-step. Key changes:
- `requirements.txt`: add gunicorn, whitenoise, dj-database-url, psycopg2-binary
- `settings.py`: read `DATABASE_URL`, `DEBUG`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` from env
- `Procfile`: `web: python manage.py migrate && python manage.py collectstatic --noinput && gunicorn config.wsgi`
- Frontend `.env.production`: `REACT_APP_API_URL=https://your-backend.railway.app`

## 8. Video Presentation Outline (10–12 min)

| Minute | Topic | Screen |
|--------|-------|--------|
| 0:00 | Hook: "48 hours, real messy problem, here's what I built" | Login page |
| 0:30 | Problem: 25 min, errors, follow-ups + show sample emails | pack/sample_emails |
| 1:30 | The pack analysis — patterns we found (Part A of this doc) | STUDY.md §A.3 |
| 3:00 | Product decisions overview | STUDY.md §A.6 mapping table |
| 4:00 | Live demo — employee (import from inbox → submit) | App |
| 6:00 | Live demo — manager (AI insights → approve) | App |
| 7:30 | Live demo — finance (advance review → disburse OR hold with note) | App |
| 9:00 | Live demo — admin (system overview, policy, org) | App |
| 10:00 | Architecture: tech stack + system diagram | STUDY.md §4 |
| 11:00 | Codebase pattern (organization = product mindset) | STUDY.md §0 |
| 12:00 | Deployment: Railway + Vercel | STUDY.md §7 |

**Speaking tips:**
- Lead with the *why* not the *what* — reviewers remember reasoning
- Show messy sample emails BEFORE the parsed result — the contrast is the pitch
- Pause on AI insights loading — let the recommendation appear on screen
- On the sub-tree feature: literally say "notice this is a separate track — this is how finance operations should be modeled"

## 9. What I'd Do With More Time

1. **Email server integration** — IMAP polling or Gmail add-on. `.eml` upload is a v0.
2. **OCR for image receipts** — vision LLM to extract dinner-bill amount from PNG.
3. **Learning loop** — every "return with remarks" becomes training data for AI.
4. **Slack/Teams approvals** — approve without opening the app.
5. **Full workflow builder** — admin can customise policy per-company (what the reference video showed).

---

# PART C — HOW TO USE THIS ARTIFACT

- **For studying:** read Part A first (understand the pack), then Part B (see how we responded)
- **For the video:** use Part A §A.3 and §A.6 as your opening (shows product thinking), then Part B for the deep dive
- **For the submission note:** SUBMISSION_NOTE.md is the ~1-page version of Part B §2
- **For deployment:** DEPLOYMENT.md is the step-by-step

**The one thing to remember:** every design call in Part B is traceable back to something specific in Part A. That's the story to tell.
