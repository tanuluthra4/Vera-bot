# Vera AI Engine (Magicpin AI Challenge)

A production-style, context-aware LLM messaging system designed to generate highly specific WhatsApp messages for merchants using structured triggers, deterministic fallback logic, and strict response constraints.

---

## 🚀 Problem Statement

Build an AI system that:
- Responds to business triggers (performance drops, renewals, spikes)
- Generates highly specific, non-generic messages
- Handles LLM failures gracefully
- Ensures deterministic behavior under strict constraints

---

## 🧠 System Architecture

### Core Pipeline

Trigger → Context Resolver → Prompt Builder → LLM (Gemini) → Validator → Fallback Layer → Output Actions

---

## ⚙️ Key Features

### 1. Trigger-Based Routing
- Supports: `perf_dip`, `renewal_due`, `recall_due`, `festival_upcoming`, `perf_spike`
- Priority scoring system for execution order

---

### 2. Context Injection System
- Category context (voice, peer stats, trends)
- Merchant context (performance, signals, offers)
- Customer context (when applicable)
- Strict dependency validation

---

### 3. LLM Integration (Gemini)
- Structured JSON output enforcement
- Temperature = 0 for determinism
- Safe JSON parsing with recovery layer

---

### 4. Fallback System (Critical Design)
- Trigger-aware fallback generation
- Uses real payload data (e.g. drop %, CTR, signals)
- Never returns generic messages

---

### 5. Suppression Engine
- Prevents duplicate trigger firing
- Maintains idempotency across ticks

---

## 🧪 API Endpoints

| Method | Endpoint        | Description |
|--------|----------------|-------------|
| GET    | /v1/healthz     | Health check |
| GET    | /v1/metadata    | System metadata |
| POST   | /v1/context     | Load category/merchant/trigger context |
| POST   | /v1/tick        | Trigger message generation |
| POST   | /v1/reply       | Conversation handling |
| POST   | /v1/teardown    | Reset system state |

---

## 🔥 Example Output

```json
{
  "body": "Rahul, your salon’s visibility dropped 30% this week — CTR is 5% vs 12% average.",
  "cta": "yes_stop",
  "send_as": "vera"
}
```

---

## 🧱 Tech Stack

- Python 3.10+
- FastAPI
- Google Gemini API
- Pydantic
- Thread-safe in-memory state

---

## ⚠️ Design Highlights

- No hardcoded responses in main flow
- Fallback system is context-aware (not generic)
- Strict JSON enforcement with multi-layer parsing
- Deterministic execution (temperature = 0)
- Production-safe failure handling

---

## 📌 What makes this different

Most LLM systems fail when:

- API breaks
- JSON is malformed
- Context is incomplete

This system:

- Never breaks output contract
- Degrades gracefully with context-aware fallback
- Maintains business-critical messaging consistency

---

## 👤 Author

Tanu Luthra
B.Tech CSE | Backend + AI Systems

---