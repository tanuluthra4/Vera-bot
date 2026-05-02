# Deployment Guide — Vera Bot

## What to submit
- Public URL of deployed server (e.g. https://vera-bot.onrender.com)
- Working FastAPI service with all endpoints

---

## Option A — Render (Recommended)

1. Push your code to a GitHub repo
2. Go to https://render.com → New → Web Service
3. Connect your repo

### Settings
- **Build Command**
```
pip install -r requirements.txt
```

- **Start Command**
```
uvicorn server:app --host 0.0.0.0 --port $PORT
```

- **Environment Variables**
```
GEMINI_API_KEY=your_api_key_here
```

4. Click Deploy (takes ~2–3 minutes)
5. Copy your public URL

---

## Option B — Railway

1. Push code to GitHub
2. Go to https://railway.app → New Project → Deploy from GitHub
3. Add environment variable:
```
GEMINI_API_KEY=your_api_key_here
```

Railway auto-runs:
```
uvicorn server:app --host 0.0.0.0 --port $PORT
```

---

## Option C — Local Testing

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="your_api_key"

uvicorn server:app --host 0.0.0.0 --port 8080
```

---

## Health Check
```
curl https://your-url/v1/healthz
curl https://your-url/v1/metadata
```

--- 

## API Testing (Manual)
1. Push Category Context
```
curl -X POST https://your-url/v1/context \
-H "Content-Type: application/json" \
-d '{
  "scope":"category",
  "context_id":"restaurants",
  "version":1,
  "payload":{"slug":"restaurants"},
  "delivered_at":"2026-05-02T10:00:00Z"
}'
```

2. Push Merchant Context
```
curl -X POST https://your-url/v1/context \
-H "Content-Type: application/json" \
-d '{
  "scope":"merchant",
  "context_id":"m1",
  "version":1,
  "payload":{"merchant_id":"m1","category_slug":"restaurants"},
  "delivered_at":"2026-05-02T10:01:00Z"
}'
```

3. Push Trigger
```
curl -X POST https://your-url/v1/context \
-H "Content-Type: application/json" \
-d '{
  "scope":"trigger",
  "context_id":"t1",
  "version":1,
  "payload":{"merchant_id":"m1","kind":"perf_dip"},
  "delivered_at":"2026-05-02T10:02:00Z"
}'
```

4. Run Tick
```
curl -X POST https://your-url/v1/tick \
-H "Content-Type: application/json" \
-d '{
  "now":"2026-05-02T10:03:00Z",
  "available_triggers":["t1"]
}'
```

---

## Notes
- System uses Gemini 2.5 Flash
- All responses are strict JSON
- LLM output is post-validated before returning
- In-memory storage used for simplicity and speed

--- 

## Files Included
| File	| Purpose |
|--------|--------|
| server.py |	Full FastAPI service |
| requirements.txt |	Dependencies |
| README.md |	System design + approach |
| DEPLOY.md |	Deployment guide |
| postman/ |	API testing collection |