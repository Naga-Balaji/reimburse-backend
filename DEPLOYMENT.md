# Deployment Guide

**Time budget:** ~30 min if everything goes smoothly.

**Stack:** Railway (Django + PostgreSQL) + Vercel (React) — both free tier.

---

## Prerequisites

- GitHub account
- Railway account (railway.app)
- Vercel account (vercel.com)
- OpenRouter API key (openrouter.ai/keys) — for AI features

---

## Step 1: Production-ready backend changes (5 min)

### 1a. Add production deps

Add to `requirements.txt`:
```
gunicorn==21.2.0
whitenoise==6.6.0
dj-database-url==2.1.0
psycopg2-binary==2.9.9
```

### 1b. Update `config/settings.py`

Replace the top of the file:

```python
from pathlib import Path
from dotenv import load_dotenv
import os, dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-dev-only')
DEBUG = os.environ.get('DEBUG', 'False') == 'True'
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
```

Replace the DATABASES block:
```python
DATABASES = {
    'default': dj_database_url.config(
        default=f'sqlite:///{BASE_DIR}/db.sqlite3',
        conn_max_age=600,
    )
}
```

Update the MIDDLEWARE (add WhiteNoise right after SecurityMiddleware):
```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',   # ← add this
    'corsheaders.middleware.CorsMiddleware',
    # ... rest unchanged
]
```

Add at the bottom:
```python
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Prod CORS: allow only your Vercel domain
if not DEBUG:
    CORS_ALLOWED_ORIGINS = os.environ.get('CORS_ALLOWED_ORIGINS', '').split(',')
    CSRF_TRUSTED_ORIGINS = os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',')
```

### 1c. Create `Procfile` at repo root

```
web: python manage.py migrate && python manage.py collectstatic --noinput && gunicorn config.wsgi
```

### 1d. Create `railway.json` at repo root (optional but cleaner)

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": { "builder": "NIXPACKS" },
  "deploy": {
    "startCommand": "python manage.py migrate && python manage.py collectstatic --noinput && gunicorn config.wsgi --log-file -",
    "restartPolicyType": "ON_FAILURE"
  }
}
```

### 1e. Test locally with production settings

```bash
DEBUG=False DATABASE_URL=sqlite:///db.sqlite3 python manage.py check --deploy
```

Commit:
```bash
git add -A
git commit -m "Production-ready: gunicorn, whitenoise, DATABASE_URL, CORS from env"
git push
```

---

## Step 2: Deploy backend to Railway (10 min)

1. Go to https://railway.app → **New Project** → **Deploy from GitHub repo** → select `reimburse`
2. Railway detects Django, starts building
3. **Add PostgreSQL:** In the project, click **New** → **Database** → **PostgreSQL** → provisioned instantly with `DATABASE_URL` auto-injected
4. **Add environment variables** (in the service, Variables tab):
   ```
   SECRET_KEY=<generate a random string, e.g. `python -c "import secrets;print(secrets.token_urlsafe(50))"`>
   DEBUG=False
   ALLOWED_HOSTS=your-service-xxxxx.up.railway.app
   OPENROUTER_API_KEY=sk-or-v1-<your key>
   OPENROUTER_MODEL=deepseek/deepseek-v4-flash-0731:free
   OPENROUTER_FALLBACK_MODEL=openrouter/free
   CORS_ALLOWED_ORIGINS=https://your-frontend.vercel.app
   CSRF_TRUSTED_ORIGINS=https://your-frontend.vercel.app
   ```
5. **Generate public domain:** Settings → Networking → **Generate Domain** → get `https://your-app.up.railway.app`
6. Update `ALLOWED_HOSTS` env var with the actual domain
7. **Trigger deploy** → wait ~3 min → check logs for `Booting worker`
8. **Seed initial data:** Railway → your service → **Deploy Logs** shows the DB migrated. To seed:
   - Click **Command** in service settings → run `python populate_sample_data.py`
   - Or use Railway CLI: `railway run python populate_sample_data.py`

**Verify:** open `https://your-app.up.railway.app/admin/` — should see Django admin login.

---

## Step 3: Deploy frontend to Vercel (5 min)

### 3a. Point React at the deployed API

Create `frontend/.env.production`:
```
REACT_APP_API_URL=https://your-app.up.railway.app
```

Update `frontend/src/api/client.js`:
```javascript
const API_BASE_URL = (process.env.REACT_APP_API_URL || 'http://localhost:8000') + '/api';

const client = axios.create({ baseURL: API_BASE_URL });
```

Also update `authClient` in the same file:
```javascript
export const authClient = axios.create({
  baseURL: process.env.REACT_APP_API_URL || 'http://localhost:8000',
});
```

Search-replace all hardcoded `http://localhost:8000` in `components/` — the client centralization handles it, but some components use `fetch()` directly (Login, some tests). Replace with `authClient` or the base URL env var.

### 3b. Deploy

```bash
cd frontend
npm install -g vercel   # if not installed
vercel                  # follow prompts, first time creates a project
vercel --prod          # publish to production URL
```

You'll get `https://reimburse-<hash>.vercel.app`.

### 3c. Fix CORS

Go back to Railway, update `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` to include your Vercel URL. Redeploy.

---

## Step 4: Media file storage (optional for demo)

**Default (works for demo):** Django writes to `/app/media/` on Railway. Files persist for the container's lifetime. On next deploy → wiped.

**Production-ready (S3):**

Add:
```
django-storages==1.14
boto3==1.34
```

Add to `settings.py`:
```python
if os.environ.get('USE_S3') == 'True':
    AWS_ACCESS_KEY_ID = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'ap-south-1')
    DEFAULT_FILE_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'
    MEDIA_URL = f'https://{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com/'
```

Set env vars on Railway. Uploads go to S3, URLs are S3 URLs. ProofViewer already handles URLs regardless of origin.

---

## Step 5: Test the deployed app (5 min)

Visit `https://your-frontend.vercel.app` and walk through:
1. Login as `chaitanya`
2. Create a travel request
3. Login as `suresh`, approve it
4. Login as `ravi`, disburse advance
5. Login as `chaitanya`, build claim from Import Inbox
6. Full approval chain
7. Login as `nandita`, view admin dashboards

If AI insights takes long (60s+), that's the free-tier LLM — mentioned in the note.

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `Application error` on Railway | Check logs — usually missing env var or migration failure |
| CORS error in browser | Add exact Vercel URL to `CORS_ALLOWED_ORIGINS`, redeploy backend |
| `401 Unauthorized` on API | Token expired; log out + back in |
| React app shows old data | Vercel edge cache — `vercel --prod --force` |
| `static/*.css` 404 | `collectstatic` didn't run; check Procfile / start command |
| LLM always fails | Check `OPENROUTER_API_KEY` env var on Railway |

---

## Cost estimate

**Free tier gets you:**
- Railway: $5/mo credit → covers this app easily
- Vercel: Unlimited hobby projects
- OpenRouter: Free models have rate limits; ~$1/mo for Anthropic paid tier

**Total: $0/mo for demo, ~$5–10/mo for real use.**

---

## Summary

The one-liner for the video: *"Backend on Railway with auto-provisioned Postgres, frontend on Vercel with env-vared API URL, both auto-deployed from GitHub. Total setup time under 30 minutes."*
