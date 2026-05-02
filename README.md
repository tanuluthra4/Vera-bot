# Vera Bot — magicpin AI Challenge Submission

**Submitted by**: Tanu Luthra  
**Model**: gemini-2.5-flash  
**Architecture**: FastAPI-based trigger-routed LLM system with post-generation validation

---

## Overview

Vera Bot is a production-style HTTP service that generates high-quality WhatsApp messages for merchants based on structured context inputs.

The system exposes all required endpoints:
- `/v1/context` → ingest category, merchant, customer, trigger data
- `/v1/tick` → evaluate triggers and generate outbound messages
- `/v1/reply` → handle multi-turn conversations
- `/v1/healthz`, `/v1/metadata`, `/v1/teardown`

---

## Core Approach

### 1. Trigger → Context Resolution
Each trigger is resolved into:
- Category context (voice, peer stats, trends)
- Merchant context (performance, offers, signals)
- Optional customer context

Only relevant fields are included → avoids prompt bloat.

---

### 2. Structured Prompt Composition
A single prompt is constructed containing:
- Category intelligence (digest, peer stats, trends)
- Merchant performance and offers
- Trigger payload (urgency, type)
- Language + tone instructions

Strict constraints enforced:
- No hallucination (only provided facts)
- Hinglish allowed
- One clear CTA
- No preambles or fluff

---

### 3. LLM Generation (Gemini 2.5 Flash)
- Temperature = 0 → deterministic outputs
- Single-call generation → low latency
- JSON-only output enforced

---

### 4. Post-LLM Validation (Critical Layer)

System does NOT trust LLM blindly.

Enforces:
- Valid `cta` (`yes_stop`, `open_ended`, `none`)
- Correct `send_as` (based on customer presence)
- Non-empty body fallback
- Deterministic `suppression_key`
- CTA enforcement (ensures "Reply YES" exists when required)

---

### 5. Suppression & State Management

- Prevents duplicate messages using `suppression_key`
- Maintains in-memory:
  - contexts
  - conversations
  - conversation metadata
- Ensures one trigger → one action

---

### 6. Multi-turn Handling (/v1/reply)

Supports:
- YES → immediate value delivery
- NO → graceful exit
- Auto-reply detection → retry once, then stop
- Question handling → grounded responses only

Conversation history is passed to maintain continuity.

---

## Design Decisions

| Decision | Reason |
|--------|--------|
| Single prompt | Faster, avoids multi-step errors |
| Gemini Flash | Low latency + strong instruction following |
| Post-validation | More reliable than re-prompting |
| No retrieval system | Dataset fits in prompt |
| In-memory state | Simpler, fast for evaluation |

---

## Tradeoffs

- No retry mechanism for LLM failures (fallback used instead)
- In-memory storage (not persistent)
- CTA logic partially heuristic (not learned)

---

## Testing

The system was tested using Postman:

- Context ingestion (`category`, `merchant`, `trigger`)
- Trigger execution via `/v1/tick`
- Multi-turn replies via `/v1/reply`

A clean Postman collection is included in:
```
postman/vera-bot-collection.json
```

---

## What could improve further

1. Retry mechanism for LLM failures  
2. Learned CTA optimization (based on past conversions)  
3. Better auto-reply detection patterns  
4. Persistent storage for production use  

---

## Summary

The system prioritizes:
- Deterministic outputs
- Strong constraint enforcement
- Real-world deployability

It is designed to behave like a production-ready messaging system rather than a prompt experiment.