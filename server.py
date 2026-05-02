"""
Vera Bot — magicpin AI Challenge
Full HTTP server exposing all 5 required endpoints.

Deploy: uvicorn server:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import os
import re
import time
import json
import uuid
import threading
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
app = FastAPI(title="Vera Bot", version="1.0.0")
START_TIME = time.time()

# (scope, context_id) -> {"version": int, "payload": dict}
contexts: dict[tuple[str, str], dict] = {}
contexts_lock = threading.Lock()

# conversation_id -> list of {"role": str, "body": str, "ts": str}
conversations: dict[str, list] = {}
# conversation_id -> {"merchant_id": str, "customer_id": str|None, "trigger_id": str}
conversation_meta: dict[str, dict] = {}
# suppression: set of suppression_keys already fired
fired_suppression: set[str] = set()
conversations_lock = threading.Lock()

TEAM_NAME = "Tanu Luthra"
TEAM_MEMBERS = ["Tanu Luthra"]
MODEL = "gemini-2.5-flash"
APPROACH = "trigger-routed single-prompt LLM composer with post-LLM validation and auto-reply detection"
CONTACT_EMAIL = "tanuluthra@example.com"  # UPDATE THIS
SUBMITTED_AT = datetime.now(timezone.utc).isoformat()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

SYSTEM_COMPOSE = """You are Vera, magicpin's merchant AI assistant. You compose WhatsApp messages for Indian merchants.

CORE PRINCIPLES:
1. Specificity wins — anchor on verifiable facts: numbers, dates, headlines, peer stats from the data
2. Peer/colleague tone — not promotional hype. Dentists/pharmacies: clinical-peer. Salons/restaurants/gyms: warm-friendly
3. Hindi-English code-mix is fine and often preferred. Match the merchant's language preference
4. One primary CTA — binary (YES/STOP) for action triggers; open_ended or none for info triggers
5. No hallucination — only use facts present in the contexts provided
6. Short, punchy — no preambles like "I hope you're doing well"
7. Never re-introduce yourself after the first message in the same conversation

COMPULSION LEVERS (use 1-2 per message):
- Specificity/verifiability: concrete numbers, dates, source citations
- Loss aversion: "you're missing X", "before this window closes"
- Social proof: "3 dentists in your area did Y this month"
- Effort externalization: "I've drafted X — just say go"
- Curiosity: "want to see who?", "want the full breakdown?"
- Single binary CTA: Reply YES / STOP

ANTI-PATTERNS:
- Generic "Flat 30% off" when service+price is available (use "Haircut @ ₹99")
- Multiple CTAs in one message
- Buried CTA (always at the end)
- Promotional tone for clinical categories (dentists, pharmacies)
- Hallucinated citations or competitor names not in the data
- Long preambles
- Re-introducing yourself

TRIGGER TYPE → CTA GUIDANCE:
- research_digest, cde_opportunity → open_ended or none
- perf_dip, renewal_due, gbp_unverified, competitor_opened → yes_stop
- recall_due, chronic_refill_due, appointment_tomorrow → yes_stop or open_ended (booking flows)
- festival_upcoming, active_planning_intent → yes_stop
- curious_ask_due → open_ended
- milestone_reached → open_ended
- dormant_with_vera, winback_eligible → yes_stop
- perf_spike → open_ended or yes_stop

Respond ONLY with valid JSON (no markdown fences):
{
  "body": "the WhatsApp message text",
  "cta": "yes_stop" | "open_ended" | "none",
  "send_as": "vera" | "merchant_on_behalf",
  "suppression_key": "string",
  "rationale": "1-2 sentences"
}"""

SYSTEM_REPLY = """You are Vera, magicpin's merchant AI assistant, in a live WhatsApp conversation.
You've already sent the opening message. The merchant (or customer) has replied.

RULES:
1. If merchant said YES / showed interest → honor it immediately, deliver value, no re-qualifying
2. If merchant sent an auto-reply → try once more with a fresh angle; exit if it happens twice
3. If merchant said NO / not interested → exit gracefully, politely
4. If merchant asked a question → answer precisely using ONLY facts from the context
5. Keep replies to 2-3 sentences max
6. Never re-introduce yourself
7. Match merchant's language

Auto-reply signals: "thank you for contacting", "aapki jaankari ke liye", "I am an automated assistant", "will get back to you"

Respond ONLY with valid JSON (no markdown fences):
{
  "action": "send" | "wait" | "end",
  "body": "message text (only if action=send)",
  "cta": "yes_stop" | "open_ended" | "none" (only if action=send),
  "wait_seconds": 1800 (only if action=wait),
  "rationale": "1 sentence"
}"""


def _call_gemini(system: str, user_content: str, max_tokens: int = 800) -> dict:
    """Call Gemini API. Returns parsed JSON dict from model output."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")

    payload = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "temperature": 0,
        "system": system,
        "messages": [{"role": "user", "content": user_content}]
    }

    import google.generativeai as genai
    
    req = urllib.request.Request(
        
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": GEMINI_API_KEY,
            "gemini-version": "2023-06-01",
        },
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    text = data["content"][0]["text"].strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return json.loads(text)

def _get_ctx(scope: str, context_id: str) -> Optional[dict]:
    with contexts_lock:
        entry = contexts.get((scope, context_id))
    return entry["payload"] if entry else None


def _resolve_trigger_contexts(trigger_id: str):
    """Return (category, merchant, trigger, customer) for a trigger id, or None."""
    trg = _get_ctx("trigger", trigger_id)
    if not trg:
        return None

    merchant_id = trg.get("merchant_id")
    customer_id = trg.get("customer_id")

    merchant = _get_ctx("merchant", merchant_id) if merchant_id else None
    if not merchant:
        return None

    cat_slug = merchant.get("category_slug", "")
    category = _get_ctx("category", cat_slug)
    if not category:
        return None

    customer = _get_ctx("customer", customer_id) if customer_id else None

    return category, merchant, trg, customer

def _build_compose_prompt(category, merchant, trigger, customer, history=None):
    cat_slug = category.get("slug", "")
    merchant_id = merchant.get("merchant_id", "")
    owner_name = merchant.get("identity", {}).get("owner_first_name", "")
    trigger_kind = trigger.get("kind", "")
    trigger_scope = trigger.get("scope", "merchant")
    trigger_suppression = trigger.get("suppression_key", "")

    lines = []
    lines.append(f"=== CATEGORY: {cat_slug} ===")
    lines.append(f"Voice: {json.dumps(category.get('voice', {}))}")
    lines.append(f"Offer catalog: {json.dumps(category.get('offer_catalog', [])[:5])}")
    lines.append(f"Peer stats: {json.dumps(category.get('peer_stats', {}))}")
    lines.append(f"Digest (cite these, don't invent): {json.dumps(category.get('digest', [])[:3])}")
    lines.append(f"Seasonal beats: {json.dumps(category.get('seasonal_beats', [])[:2])}")
    lines.append(f"Trend signals: {json.dumps(category.get('trend_signals', [])[:2])}")

    lines.append(f"\n=== MERCHANT ===")
    lines.append(f"ID: {merchant_id} | Name: {merchant.get('identity',{}).get('name')} | Owner: {owner_name}")
    lines.append(f"City: {merchant.get('identity',{}).get('city')} | Locality: {merchant.get('identity',{}).get('locality')}")
    lines.append(f"Languages: {merchant.get('identity',{}).get('languages')}")
    lines.append(f"Subscription: {json.dumps(merchant.get('subscription',{}))}")
    lines.append(f"Performance: {json.dumps(merchant.get('performance',{}))}")
    lines.append(f"Active offers: {json.dumps([o for o in merchant.get('offers',[]) if o.get('status')=='active'])}")
    lines.append(f"Signals: {merchant.get('signals',[])}")
    lines.append(f"Customer aggregate: {json.dumps(merchant.get('customer_aggregate',{}))}")
    lines.append(f"Review themes: {json.dumps(merchant.get('review_themes',[]))}")
    lines.append(f"Recent history: {json.dumps(merchant.get('conversation_history',[])[-3:])}")

    lines.append(f"\n=== TRIGGER ===")
    lines.append(f"Kind: {trigger_kind} | Scope: {trigger_scope} | Urgency: {trigger.get('urgency',1)}/5")
    lines.append(f"Suppression key: {trigger_suppression}")
    lines.append(f"Payload: {json.dumps(trigger.get('payload',{}))}")

    if customer:
        lines.append(f"\n=== CUSTOMER (message sent ON BEHALF of merchant) ===")
        lines.append(json.dumps(customer, ensure_ascii=False))
        lines.append("NOTE: set send_as = 'merchant_on_behalf'")
    else:
        lines.append("\n=== CUSTOMER ===\nNone — merchant-facing. set send_as = 'vera'")

    if history:
        lines.append(f"\n=== CONVERSATION SO FAR ===")
        lines.append(json.dumps(history, ensure_ascii=False))
        lines.append("Do NOT repeat any message already sent. This is a follow-up turn.")

    lines.append(f"\n=== TASK ===")
    lines.append(f"Trigger kind: '{trigger_kind}' | Urgency: {trigger.get('urgency',1)}")
    if customer:
        lines.append(f"Customer-facing message. Address {customer.get('identity',{}).get('name','the customer')} by name.")
        lines.append(f"Language: {customer.get('identity',{}).get('language_pref','en')}")
    else:
        lines.append(f"Merchant-facing. Address owner by first name if available: {owner_name or 'their name'}")
        lines.append(f"Match merchant language: {merchant.get('identity',{}).get('languages',['en'])}")
    lines.append("Use ONLY facts present in the contexts above. Respond with valid JSON.")

    return "\n".join(lines)


def compose_message(category, merchant, trigger, customer, history=None) -> dict:
    """Compose a message and validate the output."""
    prompt = _build_compose_prompt(category, merchant, trigger, customer, history)
    result = _call_gemini(SYSTEM_COMPOSE, prompt, max_tokens=800)

    # Validate + repair
    valid_ctas = {"yes_stop", "open_ended", "none"}
    if result.get("cta") not in valid_ctas:
        result["cta"] = "yes_stop" if trigger.get("urgency", 1) >= 3 else "open_ended"
    if result.get("send_as") not in {"vera", "merchant_on_behalf"}:
        result["send_as"] = "merchant_on_behalf" if customer else "vera"
    # enforce correct send_as
    result["send_as"] = "merchant_on_behalf" if customer else "vera"
    if not result.get("suppression_key"):
        result["suppression_key"] = trigger.get("suppression_key", f"auto:{trigger.get('id','?')}")
    if not result.get("body"):
        result["body"] = "Hi, checking in — anything I can help with today?"
    if not result.get("rationale"):
        result["rationale"] = f"Responding to {trigger.get('kind','trigger')} trigger."

    return result


def reply_message(conversation_id: str, merchant_id: str, customer_id: Optional[str],
                  message: str, turn_number: int) -> dict:
    """Generate a reply for an ongoing conversation."""
    with conversations_lock:
        history = conversations.get(conversation_id, [])
        meta = conversation_meta.get(conversation_id, {})

    trigger_id = meta.get("trigger_id", "")
    trg = _get_ctx("trigger", trigger_id) if trigger_id else {}
    merchant = _get_ctx("merchant", merchant_id)
    category = _get_ctx("category", merchant.get("category_slug", "")) if merchant else {}
    customer = _get_ctx("customer", customer_id) if customer_id else None

    prompt = f"""=== CONTEXT ===
Trigger kind: {trg.get('kind','unknown')} | Urgency: {trg.get('urgency',1)}
Merchant: {merchant.get('identity',{}).get('name') if merchant else merchant_id}
Category: {merchant.get('category_slug') if merchant else 'unknown'}
Languages: {merchant.get('identity',{}).get('languages',['en']) if merchant else ['en']}
Active offers: {json.dumps([o for o in merchant.get('offers',[]) if o.get('status')=='active']) if merchant else []}
Trigger payload: {json.dumps(trg.get('payload',{}))}
{"Customer: " + json.dumps({'name': customer.get('identity',{}).get('name'), 'state': customer.get('state'), 'lang': customer.get('identity',{}).get('language_pref')}) if customer else ""}

=== CONVERSATION HISTORY ===
{json.dumps(history, ensure_ascii=False)}

=== NEW MESSAGE (turn {turn_number}) ===
From: {'merchant' if not customer_id else 'customer'}
Message: "{message}"

Decide: send, wait, or end. Keep reply to 2-3 sentences if sending. Respond with valid JSON."""

    result = _call_gemini(SYSTEM_REPLY, prompt, max_tokens=500)

    # Validate
    if result.get("action") not in ("send", "wait", "end"):
        result["action"] = "send"
    if result.get("action") == "send" and not result.get("body"):
        result["body"] = "Noted — let me take care of that for you."
    if not result.get("rationale"):
        result["rationale"] = "Continuing conversation."

    return result

class CtxBody(BaseModel):
    scope: str
    context_id: str
    version: int
    payload: dict[str, Any]
    delivered_at: str

class TickBody(BaseModel):
    now: str
    available_triggers: list[str] = []

class ReplyBody(BaseModel):
    conversation_id: str
    merchant_id: Optional[str] = None
    customer_id: Optional[str] = None
    from_role: str
    message: str
    received_at: str
    turn_number: int

@app.get("/v1/healthz")
async def healthz():
    with contexts_lock:
        counts = {"category": 0, "merchant": 0, "customer": 0, "trigger": 0}
        for (scope, _) in contexts:
            if scope in counts:
                counts[scope] += 1
    return {
        "status": "ok",
        "uptime_seconds": int(time.time() - START_TIME),
        "contexts_loaded": counts
    }

@app.get("/v1/metadata")
async def metadata():
    return {
        "team_name": TEAM_NAME,
        "team_members": TEAM_MEMBERS,
        "model": MODEL,
        "approach": APPROACH,
        "contact_email": CONTACT_EMAIL,
        "version": "1.0.0",
        "submitted_at": SUBMITTED_AT
    }

@app.post("/v1/context")
async def push_context(body: CtxBody):
    valid_scopes = {"category", "merchant", "customer", "trigger"}
    if body.scope not in valid_scopes:
        return {"accepted": False, "reason": "invalid_scope",
                "details": f"scope must be one of {valid_scopes}"}

    key = (body.scope, body.context_id)
    with contexts_lock:
        cur = contexts.get(key)
        if cur and cur["version"] >= body.version:
            return {"accepted": False, "reason": "stale_version", "current_version": cur["version"]}
        contexts[key] = {"version": body.version, "payload": body.payload}

    return {
        "accepted": True,
        "ack_id": f"ack_{body.context_id}_v{body.version}",
        "stored_at": datetime.now(timezone.utc).isoformat()
    }

@app.post("/v1/tick")
async def tick(body: TickBody):
    """
    For each available trigger, check if we should fire a message.
    Suppression prevents re-firing the same message.
    Budget: fire at most 10 actions per tick to stay within the 30s window.
    """
    actions = []

    for trg_id in body.available_triggers:
        if len(actions) >= 10:
            break

        # Resolve contexts
        resolved = _resolve_trigger_contexts(trg_id)
        if not resolved:
            continue

        category, merchant, trg, customer = resolved
        sup_key = trg.get("suppression_key", trg_id)

        with conversations_lock:
            if sup_key in fired_suppression:
                continue

        # Compose
        try:
            result = compose_message(category, merchant, trg, customer)
        except Exception as e:
            # Don't crash the tick — skip this trigger
            continue

        merchant_id = merchant.get("merchant_id", "")
        customer_id = customer.get("customer_id") if customer else None
        conv_id = f"conv_{merchant_id}_{trg_id}_{uuid.uuid4().hex[:6]}"

        with conversations_lock:
            fired_suppression.add(sup_key)
            conversations[conv_id] = [{"role": "vera", "body": result["body"], "ts": body.now}]
            conversation_meta[conv_id] = {
                "merchant_id": merchant_id,
                "customer_id": customer_id,
                "trigger_id": trg_id
            }

        # Build template params (name, topic, CTA hint)
        owner = merchant.get("identity", {}).get("owner_first_name", merchant.get("identity", {}).get("name", ""))
        actions.append({
            "conversation_id": conv_id,
            "merchant_id": merchant_id,
            "customer_id": customer_id,
            "send_as": result["send_as"],
            "trigger_id": trg_id,
            "template_name": f"vera_{trg.get('kind','generic')}_v1",
            "template_params": [owner, trg.get("kind", "update"), result["cta"]],
            "body": result["body"],
            "cta": result["cta"],
            "suppression_key": result["suppression_key"],
            "rationale": result["rationale"]
        })

    return {"actions": actions}


@app.post("/v1/reply")
async def reply(body: ReplyBody):
    """Handle a reply from the judge (merchant or customer)."""
    with conversations_lock:
        if body.conversation_id not in conversations:
            conversations[body.conversation_id] = []
        history = conversations[body.conversation_id]
        history.append({
            "role": body.from_role,
            "body": body.message,
            "ts": body.received_at
        })

    try:
        result = reply_message(
            conversation_id=body.conversation_id,
            merchant_id=body.merchant_id or "",
            customer_id=body.customer_id,
            message=body.message,
            turn_number=body.turn_number
        )
    except Exception as e:
        # Graceful degradation — don't time out
        result = {
            "action": "send",
            "body": "Got it! Let me look into that and come back to you shortly.",
            "cta": "none",
            "rationale": f"Fallback response due to error: {e}"
        }

    # Log bot's reply in history
    if result.get("action") == "send":
        with conversations_lock:
            conversations[body.conversation_id].append({
                "role": "vera",
                "body": result.get("body", ""),
                "ts": datetime.now(timezone.utc).isoformat()
            })

    return result


@app.post("/v1/teardown")
async def teardown():
    """Optional: magicpin signals end of test. Wipe state."""
    with contexts_lock:
        contexts.clear()
    with conversations_lock:
        conversations.clear()
        conversation_meta.clear()
        fired_suppression.clear()
    return {"status": "torn_down"}


@app.get("/")
async def root():
    return {"service": "Vera Bot", "team": TEAM_NAME, "status": "running"}
