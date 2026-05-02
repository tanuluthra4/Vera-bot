"""
conversation_handlers.py — Multi-turn conversation support for Vera.
Optional component per challenge spec §7.4.
"""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
import time
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Auto-reply detection
# ---------------------------------------------------------------------------

AUTO_REPLY_PATTERNS = [
    # Common WhatsApp Business auto-replies
    r"aapki jaankari ke liye bahut-bahut shukriya",
    r"main aapki.*baatein.*team tak pahuncha",
    r"thank you for contacting",
    r"thanks? for (reaching out|your message|contacting)",
    r"i am an? (automated|auto)\b",
    r"main ek automated assistant",
    r"this is an? (auto(mated)?[\s-]reply|automated response)",
    r"we (will|shall) get back to you",
    r"our team will (contact|respond)",
    r"your (message|query) has been received",
]

def is_auto_reply(message: str) -> bool:
    """Return True if the message looks like a WhatsApp Business auto-reply."""
    msg_lower = message.lower()
    for pattern in AUTO_REPLY_PATTERNS:
        if re.search(pattern, msg_lower):
            return True
    return False


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

ACTION_INTENTS = [
    r"\b(yes|yep|yeah|haan|ha|ok|okay|sure|bilkul|zaroor|go ahead|let'?s do it|please do|karo|kar do|theek hai)\b",
    r"\b(join|judrna|judna|subscribe|renew)\b",
    r"\bgo\b",
    r"send (me|it|the)",
    r"please (update|share|send|draft|post)",
]

STOP_INTENTS = [
    r"\b(no|nahi|nope|stop|not interested|band karo|mat karo|rukna|ruk)\b",
    r"don'?t (want|need|send)",
    r"not (now|today|interested)",
    r"baad mein",  # "later" in Hindi
    r"leave (me|it)",
]

def detect_intent(message: str) -> str:
    """Return 'action', 'stop', or 'unknown'."""
    msg_lower = message.lower()
    for pattern in ACTION_INTENTS:
        if re.search(pattern, msg_lower):
            return "action"
    for pattern in STOP_INTENTS:
        if re.search(pattern, msg_lower):
            return "stop"
    return "unknown"


# ---------------------------------------------------------------------------
# ConversationState
# ---------------------------------------------------------------------------

@dataclass
class ConversationState:
    conversation_id: str
    merchant_id: str
    customer_id: Optional[str]
    category: dict
    merchant: dict
    trigger: dict
    customer: Optional[dict]
    history: list[dict] = field(default_factory=list)  # {role: vera/merchant, body: str}
    turn_number: int = 0
    auto_reply_count: int = 0
    resolved: bool = False


# ---------------------------------------------------------------------------
# LLM call (same API as bot.py)
# ---------------------------------------------------------------------------

RESPOND_SYSTEM = """You are Vera, magicpin's merchant AI assistant handling a live WhatsApp conversation.

CONTEXT: You've already sent the first message. Now the merchant has replied. You must decide the best next move.

RULES:
1. If merchant said YES / showed interest → honor it immediately, take the action they asked for, don't re-qualify
2. If merchant sent an auto-reply → try once more with a different angle; if it happens again, exit gracefully
3. If merchant said NO / not interested → exit gracefully with a polite closing, no pushing
4. If merchant asked a question → answer it precisely using ONLY facts from the context
5. Keep replies short — 2-3 sentences max in follow-up turns
6. Never re-introduce yourself
7. Hindi-English mix is fine; match merchant's language

Respond ONLY with valid JSON (no markdown fences):
{
  "action": "send" | "wait" | "end",
  "body": "message text (only if action=send)",
  "cta": "yes_stop" | "open_ended" | "none" (only if action=send),
  "wait_seconds": 1800 (only if action=wait),
  "rationale": "1 sentence explanation"
}"""


def _call_claude_reply(prompt: str) -> dict:
    payload = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 600,
        "temperature": 0,
        "system": RESPOND_SYSTEM,
        "messages": [{"role": "user", "content": prompt}]
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "anthropic-version": "2023-06-01"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    text = data["content"][0]["text"].strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    return json.loads(text)


def respond(state: ConversationState, merchant_message: str) -> dict:
    """
    Given the conversation so far + the merchant's latest message,
    produce the reply.
    
    Returns dict with keys: action, body (if send), cta (if send), wait_seconds (if wait), rationale
    """
    state.turn_number += 1
    state.history.append({"role": "merchant", "body": merchant_message})

    # --- Guard: auto-reply detection ---
    if is_auto_reply(merchant_message):
        state.auto_reply_count += 1
        if state.auto_reply_count >= 2:
            # Stop — we've tried enough
            state.resolved = True
            return {
                "action": "end",
                "rationale": "Detected auto-reply twice — exiting gracefully to avoid burning turns."
            }
        else:
            # Try once more with a pivot
            pivot_prompt = f"""
CONVERSATION SO FAR:
{json.dumps(state.history, ensure_ascii=False, indent=2)}

MERCHANT CONTEXT (brief):
Name: {state.merchant.get('identity', {}).get('name')}
Category: {state.category.get('slug')}

The merchant just sent an auto-reply. Try once more with a DIFFERENT, shorter angle — 
ask a direct closed question that a real person would have to consciously reply to.
Keep it to 1-2 sentences. If the merchant sends another auto-reply after this, we stop.
"""
            result = _call_claude_reply(pivot_prompt)
            if result.get("action") == "send":
                state.history.append({"role": "vera", "body": result.get("body", "")})
            return result

    # --- Guard: intent detection ---
    intent = detect_intent(merchant_message)
    
    if intent == "stop":
        state.resolved = True
        return {
            "action": "end",
            "rationale": "Merchant signaled not-interested — exiting gracefully."
        }

    # --- Normal LLM response ---
    prompt = f"""
ORIGINAL TRIGGER:
{json.dumps({'kind': state.trigger.get('kind'), 'payload': state.trigger.get('payload')}, ensure_ascii=False)}

MERCHANT CONTEXT (key facts):
Name: {state.merchant.get('identity', {}).get('name')}
Category: {state.category.get('slug')}
Language: {state.merchant.get('identity', {}).get('languages', ['en'])}
Signals: {state.merchant.get('signals', [])}
Active offers: {[o.get('title') for o in state.merchant.get('offers', []) if o.get('status') == 'active']}
{f"Customer: {json.dumps(state.customer, ensure_ascii=False)}" if state.customer else ""}

CONVERSATION HISTORY:
{json.dumps(state.history, ensure_ascii=False, indent=2)}

DETECTED INTENT: {intent}

The merchant just replied: "{merchant_message}"

{"The merchant is INTERESTED — take the action, deliver value immediately." if intent == "action" else "Respond helpfully. If they asked a question, answer precisely. If neutral, advance the conversation."}

Respond with JSON.
"""

    result = _call_claude_reply(prompt)
    
    # Validate
    if result.get("action") not in ("send", "wait", "end"):
        result["action"] = "send"
    
    if result.get("action") == "send":
        state.history.append({"role": "vera", "body": result.get("body", "")})
    elif result.get("action") == "end":
        state.resolved = True

    return result
