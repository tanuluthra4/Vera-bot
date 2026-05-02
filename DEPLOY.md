# Deployment Guide — Vera Bot

## What to submit
- The **public URL** of your deployed server (e.g. `https://vera-bot.onrender.com`)
- `submission.jsonl` (30 pre-generated messages)
- `bot.py`, `server.py`, `conversation_handlers.py`, `README.md`

---

## Option A — Render (recommended, free tier works)

1. Push this folder to a **GitHub repo** (public or private)
2. Go to https://render.com → New → Web Service
3. Connect your GitHub repo
4. Settings:
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `uvicorn server:app --host 0.0.0.0 --port $PORT`
   - **Environment variable**: `ANTHROPIC_API_KEY` = your key
5. Deploy → wait ~2 min → copy the URL (e.g. `https://vera-bot.onrender.com`)
6. Test: `curl https://vera-bot.onrender.com/v1/healthz`

---

## Option B — Railway

1. Push to GitHub
2. Go to https://railway.app → New Project → Deploy from GitHub
3. Add env var `ANTHROPIC_API_KEY`
4. Railway auto-detects Python and runs `uvicorn server:app --host 0.0.0.0 --port $PORT`

---

## Option C — Local with ngrok (for testing only)

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."
uvicorn server:app --host 0.0.0.0 --port 8080

# In another terminal:
ngrok http 8080
# Copy the https URL ngrok gives you
```

---

## Testing locally with judge_simulator.py

```bash
# Start your server first (see above)
# Then in another terminal:
export BOT_URL=http://localhost:8080
python judge_simulator.py
```

---

## Quick health check

```bash
# Replace with your actual URL
BOT_URL=https://vera-bot.onrender.com

curl $BOT_URL/v1/healthz
curl $BOT_URL/v1/metadata

# Push a test context
curl -X POST $BOT_URL/v1/context \
  -H "Content-Type: application/json" \
  -d '{"scope":"category","context_id":"dentists","version":1,"payload":{"slug":"dentists","voice":{},"offer_catalog":[],"peer_stats":{},"digest":[],"seasonal_beats":[],"trend_signals":[]},"delivered_at":"2026-04-26T10:00:00Z"}'

# Test a tick
curl -X POST $BOT_URL/v1/tick \
  -H "Content-Type: application/json" \
  -d '{"now":"2026-04-26T10:00:00Z","available_triggers":[]}'
```

---

## Files in this submission

| File | Purpose |
|---|---|
| `server.py` | Full FastAPI HTTP server — all 5 endpoints |
| `bot.py` | `compose()` function (also importable standalone) |
| `conversation_handlers.py` | Multi-turn reply logic, auto-reply detection |
| `submission.jsonl` | 30 pre-generated test pair messages |
| `requirements.txt` | Python dependencies |
| `render.yaml` | One-click Render deployment config |
| `README.md` | Approach + tradeoffs |
| `DEPLOY.md` | This file |
