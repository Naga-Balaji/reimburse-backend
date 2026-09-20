# Reimburse — Backend

Django + DRF backend for the Nortex Travel Expense Reimbursement app.

**Frontend repo:** [reimburse-frontend](https://github.com/Naga-Balaji/reimburse-frontend)

---

## Quick start (local, 3 min)

```bash
git clone https://github.com/Naga-Balaji/reimburse-backend.git
cd reimburse-backend

# venv + install
python3 -m venv venv
source venv/bin/activate          # macOS/Linux
pip install -r requirements.txt

# .env (add your OpenRouter key for AI features — optional)
cp .env.example .env
# edit .env if you have an OPENROUTER_API_KEY

# db + seed
python manage.py migrate
python populate_sample_data.py     # 8 users, 3 TRs, 4 historical claims

# run
python manage.py runserver 8000
```

API is at `http://localhost:8000/api/`. Admin at `http://localhost:8000/admin/` (`admin` / `admin123`).

---

## Demo credentials

| Role | Username | Password |
|------|----------|----------|
| Employee | `chaitanya` | `password123` |
| Employee | `deepa` | `password123` |
| Manager | `suresh` | `password123` |
| Head of Department | `meera` | `password123` |
| Div Head | `arvind` | `password123` |
| MD | `nandita` | `password123` (admin role) |
| Finance | `ravi` | `password123` |

---

## Architecture

Read `STUDY.md` for the full story — pack analysis, product decisions, system design, DB structure.

- `core/models.py` — domain vocabulary (UserProfile, TravelRequest, ExpenseClaim, ExpenseItem, Approval, TRApproval)
- `core/parsers.py` — deterministic `.eml` extractors (Uber, MakeMyTrip, hotel, noise/dup/colleague filters)
- `core/llm.py` — OpenRouter client + AI insights generator with rule-based fallback
- `core/views.py` — role-scoped viewsets + custom actions (submit, approve, disburse, hold, follow_up, etc.)
- `core/serializers.py` — DRF serializers with computed fields
- `pack/` — the original spec (sample emails, receipts, policy)

---

## Documentation

| File | What it covers |
|------|----------------|
| `STUDY.md` | Complete study — pack analysis + architecture (main reference) |
| `ARCHITECTURE.md` | Architecture-only version for video walkthroughs |
| `SUBMISSION_NOTE.md` | 1-page reviewer summary of design decisions |
| `POLICY_COVERAGE.md` | Clause-by-clause audit of what's covered vs left out |
| `DEPLOYMENT.md` | Railway + Vercel deployment guide |

---

## Deploy

See `DEPLOYMENT.md`. TL;DR:

1. Push this repo to GitHub
2. Railway → Deploy from GitHub → add PostgreSQL → set env vars
3. Add domain, point frontend `REACT_APP_API_URL` at it

Environment variables needed:
- `SECRET_KEY` (generate a random string)
- `DEBUG=False`
- `ALLOWED_HOSTS=your-app.railway.app`
- `CORS_ALLOWED_ORIGINS=https://your-frontend.vercel.app`
- `CSRF_TRUSTED_ORIGINS=https://your-frontend.vercel.app`
- `OPENROUTER_API_KEY=sk-or-v1-...` (optional — rule-based fallback works without)
- `OPENROUTER_MODEL=deepseek/deepseek-v4-flash-0731:free`
- `DATABASE_URL` — auto-injected by Railway PostgreSQL

---

## Tech stack

Django 6.1 · Django REST Framework · SQLite (dev) / PostgreSQL (prod) · Token authentication · OpenRouter for LLM · WhiteNoise for static · Gunicorn for WSGI.
