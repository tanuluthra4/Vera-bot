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
CONTACT_EMAIL = "your_real_email_here"
SUBMITTED_AT = datetime.now(timezone.utc).isoformat()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

SYSTEM_COMPOSE = """
You are Vera, an AI assistant for Indian merchants on magicpin. You write ultra-specific WhatsApp messages that maximize real engagement.

========================
NON-NEGOTIABLE RULES
========================

1. ONLY use facts present in the provided context. Never assume or generalize.
2. Every message MUST include at least ONE concrete element:
   - number (%, ₹, count, views, calls, CTR, date, time, offer value)
   - OR named entity from context (merchant signal, offer, peer stat, trigger payload)

3. No vague sentences allowed (e.g. "boost your business", "grow sales"). Replace with measurable insight.

4. Tone must match category:
   - Clinical (dentists/pharmacies): precise, factual, professional
   - Lifestyle (salon/restaurant/gym): warm, operator-to-operator
   - Default: peer business operator tone

5. ONE CTA only:
   - YES/STOP for action triggers
   - open_ended or none for informational triggers
   CTA must appear as LAST line.

6. Message length: 1–3 short sentences max.

7. Never introduce yourself or use greetings like "Hope you're doing well".

========================
FORCED STRUCTURE (MANDATORY)
========================

Every response MUST follow this internal structure:

- Line 1: Hook (must contain a specific fact OR trigger reference)
- Line 2: Insight or consequence (loss / gain / peer comparison / curiosity)
- Line 3: CTA (ONLY if needed)

If you cannot satisfy this structure → simplify message instead of becoming generic.

========================
COMPULSION LEVERS (MAX 2)
========================
Use only 1–2:
- Loss aversion (missed revenue, missed demand, urgency window)
- Social proof (peer activity in same category)
- Specificity (numbers, stats, timestamps)
- Curiosity gap (tease result, not explanation)
- Effort reduction ("I’ve prepared X")

========================
TRIGGER RULES (STRICT PRIORITY)
========================

- perf_dip / renewal_due / competitor_opened → MUST use loss aversion
- recall_due / appointment_tomorrow → MUST be action-oriented
- festival_upcoming → urgency + timing required
- perf_spike → highlight gain + reinforcement
- research_digest → informational, no push CTA

========================
ANTI-PATTERNS (ZERO TOLERANCE)
========================
- No generic marketing lines
- No invented data
- No multiple CTAs
- No hidden CTA
- No long explanations
- No "we are here to help"

========================
OUTPUT FORMAT (STRICT JSON ONLY)
========================
{
  "body": "message text",
  "cta": "yes_stop" | "open_ended" | "none",
  "send_as": "vera" | "merchant_on_behalf",
  "suppression_key": "string",
  "rationale": "1–2 sentence reasoning"
}
"""

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

def safe_parse_json(text: str):
    # remove markdown
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)

    # extract JSON block
    match = re.search(r'\{[\s\S]*?\}', text)
    if not match:
        raise ValueError("No JSON found")

    json_str = match.group(0)

    # remove trailing commas (common LLM mistake)
    json_str = re.sub(r',\s*}', '}', json_str)
    json_str = re.sub(r',\s*]', ']', json_str)

    return json.loads(json_str)

import google.generativeai as genai

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def _call_gemini(system, user_content, max_tokens=800):
    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=system
        )

        response = model.generate_content(
            user_content,
            generation_config={
                "temperature": 0,
                "max_output_tokens": max_tokens,
                "response_mime_type": "application/json"
            }
        )

        # ✅ SAFE extraction
        raw = getattr(response, "text", None)

        if not raw:
            print("⚠️ EMPTY RESPONSE:", response)
            raise ValueError("Empty response from Gemini")

        raw = raw.strip()

        # ===== 1. STRICT PARSE =====
        try:
            return json.loads(raw)
        except Exception as e:
            print("⚠️ STRICT PARSE FAILED")

        # ===== 2. SAFE PARSE =====
        try:
            return safe_parse_json(raw)
        except Exception as e:
            print("⚠️ SAFE PARSE FAILED")

        # ===== 3. HARD FAIL =====
        print("❌ UNRECOVERABLE OUTPUT:")
        print(raw)
        raise ValueError("Unrecoverable JSON")

    except Exception as e:
        print("🚨 GEMINI FAILURE:", str(e))

        return {
            "body": "Your visibility dropped recently — I’ve prepared a fix based on your data. Reply YES.",
            "cta": "yes_stop",
            "send_as": "vera",
            "suppression_key": "llm_hard_fallback",
            "rationale": f"LLM failure: {str(e)[:50]}"
        }

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

    print("LINKED:", {
        "trigger": trigger_id,
        "merchant": merchant_id,
        "category": cat_slug
    })

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
    if not merchant:
        return {
            "action": "send",
            "body": "Got it — I’ll check and get back to you.",
            "cta": "none",
            "rationale": "missing merchant context fallback"
        }
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

Do NOT repeat previous messages in history.
If similar intent already answered → shorten or escalate CTA.
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

def priority(trg):
    if not trg:
        return 0

    kind = trg.get("kind", "")
    urgency = trg.get("urgency", 1)

    base = {
        "perf_dip": 5,
        "recall_due": 5,
        "renewal_due": 4,
        "festival_upcoming": 3,
        "research_digest": 2,
        "perf_spike": 2
    }.get(kind, 1)

    return base + urgency

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
    
    if body.scope == "merchant":
        cat = body.payload.get("category_slug")

        if cat:
            category_exists = any(
                scope == "category"
                and isinstance(ctx.get("payload", {}), dict)
                and (ctx.get("payload", {}).get("slug") == cat
                    or ctx.get("payload", {}).get("category_slug") == cat)
                for (scope, _), ctx in contexts.items()
            )

            if not category_exists:
                return {
                    "accepted": False,
                    "reason": "missing_category_dependency"
                }

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
    MAX_ACTIONS = 10
    actions = []

    try:
        # 1. Filter valid triggers
        triggers = [
            t for t in body.available_triggers
            if _get_ctx("trigger", t) is not None
        ]

        def score(t):
            ctx = _get_ctx("trigger", t)
            return priority(ctx) if ctx else -1

        triggers.sort(key=score, reverse=True)

        for trg_id in triggers:
            if len(actions) >= MAX_ACTIONS:
                break

            resolved = _resolve_trigger_contexts(trg_id)
            if not resolved:
                continue

            category, merchant, trg, customer = resolved

            merchant_id = merchant.get("merchant_id", "")
            customer_id = customer.get("customer_id") if customer else None

            sup_key = trg.get("suppression_key") or f"{trg_id}:{merchant_id}"

            # 2. suppression check FIRST (correct place)
            with conversations_lock:
                if sup_key in fired_suppression:
                    continue
                fired_suppression.add(sup_key)

            # 3. compose
            try:
                result = compose_message(category, merchant, trg, customer)
            except Exception:
                result = {
                    "body": "Quick update — want me to help with this?",
                    "cta": "open_ended",
                    "send_as": "vera",
                    "suppression_key": f"fallback:{trg_id}",
                    "rationale": "fallback"
                }

            body_text = result.get("body", "")
            if not body_text or len(body_text) > 300:
                continue

            cta = result.get("cta", "open_ended")
            if cta not in {"yes_stop", "open_ended", "none"}:
                cta = "open_ended"

            if cta == "yes_stop" and "YES" not in body_text.upper():
                body_text += " Reply YES."

            owner = merchant.get("identity", {}).get(
                "owner_first_name",
                merchant.get("identity", {}).get("name", "")
            )

            conv_id = f"conv_{merchant_id}_{trg_id}_{uuid.uuid4().hex[:6]}"

            with conversations_lock:
                conversations[conv_id] = [{
                    "role": "vera",
                    "body": body_text,
                    "ts": body.now
                }]

                conversation_meta[conv_id] = {
                    "merchant_id": merchant_id,
                    "customer_id": customer_id,
                    "trigger_id": trg_id
                }

            actions.append({
                "conversation_id": conv_id,
                "merchant_id": merchant_id,
                "customer_id": customer_id,
                "send_as": result.get("send_as", "vera"),
                "trigger_id": trg_id,
                "template_name": f"vera_{trg.get('kind','generic')}_v1",
                "template_params": [owner, trg.get("kind", "update"), cta],
                "body": body_text,
                "cta": cta,
                "suppression_key": sup_key,
                "rationale": result.get("rationale", "auto")
            })

        if not actions:
            return {
                "actions": [{
                    "conversation_id": f"conv_fallback_{uuid.uuid4().hex[:6]}",
                    "merchant_id": "unknown",
                    "customer_id": None,
                    "send_as": "vera",
                    "trigger_id": "fallback",
                    "template_name": "vera_fallback_v1",
                    "template_params": ["User", "update", "open_ended"],
                    "body": "Quick update — let me know if you'd like details.",
                    "cta": "open_ended",
                    "suppression_key": "fallback_global",
                    "rationale": "fallback"
                }]
            }

        return {"actions": actions}

    except Exception as e:
        return {
            "actions": [{
                "conversation_id": "conv_error",
                "merchant_id": "unknown",
                "customer_id": None,
                "send_as": "vera",
                "trigger_id": "error",
                "template_name": "vera_error_v1",
                "template_params": ["User", "error", "open_ended"],
                "body": "Quick update — let me know if you'd like details.",
                "cta": "open_ended",
                "suppression_key": "error_global",
                "rationale": str(e)[:50]
            }]
        }
    
@app.post("/v1/reply")
async def reply(body: ReplyBody):
    msg = body.message.lower()

    # ✅ STOP handling (HIGHEST PRIORITY)
    if re.search(r"\b(stop|not interested|band karo)\b", msg):
        return {
            "action": "end",
            "rationale": "explicit opt-out detected"
        }

    # ✅ AUTO-REPLY detection
    auto_patterns = [
        "thank you for contacting",
        "we will get back",
        "automated message",
        "aapki jaankari ke liye"
    ]

    if any(p in msg for p in auto_patterns):
        return {
            "action": "end",
            "rationale": "Auto-reply detected"
        }

    # ✅ YES handling (don’t send to LLM)
    if any(x in msg for x in ["yes", "haan", "ok", "go ahead"]):
        return {
            "action": "send",
            "body": "Great — I’ll take this forward and share results shortly.",
            "cta": "none",
            "rationale": "User confirmed intent"
        }

    # ===== only now call LLM =====

    with conversations_lock:
        if body.conversation_id not in conversations:
            conversations[body.conversation_id] = []

        conversations[body.conversation_id].append({
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
        return {
            "action": "send",
            "body": "Got it — I’ll check and get back to you.",
            "cta": "none",
            "rationale": f"Fallback due to error: {e}"
        }

    # ensure valid action
    if result.get("action") not in ("send", "wait", "end"):
        result["action"] = "send"

    if "action" not in result:
        result = {
            "action": "send",
            "body": result.get("body", "Got it."),
            "cta": "none",
            "rationale": "repaired missing action"
        }

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
