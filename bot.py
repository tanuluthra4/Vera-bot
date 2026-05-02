"""
Vera Bot — magicpin AI Challenge submission
Team: Tanu Luthra
Model: gemini-2.5-flash (temperature=0 for determinism)
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
import urllib.error
from typing import Optional
import os
import google.generativeai as genai
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
SYSTEM_PROMPT = """You are Vera, magicpin's merchant AI assistant. You compose WhatsApp messages for Indian merchants.

CORE PRINCIPLES:
1. Specificity wins — anchor on verifiable facts: numbers, dates, headlines, peer stats from the data
2. Peer/colleague tone — not promotional hype. Dentists: clinical-peer. Salons/restaurants: warm-friendly
3. Hindi-English code-mix is fine and often preferred. Match the merchant's language preference
4. One primary CTA — binary (YES/STOP) for action triggers; none for pure-info triggers
5. No hallucination — only use facts present in the contexts provided
6. Short, punchy — no preambles like "I hope you're doing well"
7. Never re-introduce yourself after the first message

COMPULSION LEVERS (use 1-2 per message):
- Specificity/verifiability: concrete numbers, dates, source citations
- Loss aversion: "you're missing X", "before this window closes"
- Social proof: "3 dentists in your area did Y this month"
- Effort externalization: "I've drafted X — just say go"
- Curiosity: "want to see who?", "want the full breakdown?"
- Single binary CTA: Reply YES / STOP

ANTI-PATTERNS (never do these):
- Generic "Flat 30% off" when service+price is available
- Multiple CTAs in one message
- Buried CTA (put it at the end)
- Promotional tone for clinical categories (dentists, pharmacies)
- Hallucinated citations or competitor names
- Long preambles
- Re-introducing yourself

TRIGGER TYPE GUIDANCE:
- research_digest → cite the specific finding + source; curiosity CTA
- perf_dip → name the exact metric drop; loss aversion + action offer
- perf_spike → celebrate + pivot to next opportunity
- renewal_due → urgency + specific value proof; binary YES CTA
- recall_due (customer) → send as merchant, name the patient, suggest slots
- festival_upcoming → specific campaign idea + effort externalization
- competitor_opened → social proof + differentiation anchor
- dormant_with_vera → re-engage with curiosity hook
- milestone_reached → celebrate + pivot to next goal
- curious_ask_due → open question; asking-the-merchant lever
- regulation_change → compliance urgency + offer to help
- appointment_tomorrow → reminder + upsell opportunity
- winback_eligible → loss aversion + specific lapsed count
- ipl_match_today → timely promo tie-in; urgency

OUTPUT FORMAT — respond ONLY with valid JSON, no markdown fences:
{
  "body": "the WhatsApp message text",
  "cta": "yes_stop" | "open_ended" | "none",
  "send_as": "vera" | "merchant_on_behalf",
  "suppression_key": "string matching trigger suppression_key or derived from it",
  "rationale": "1-2 sentences: why this message, what it achieves"
}"""

def _build_user_prompt(category: dict, merchant: dict, trigger: dict, customer: Optional[dict]) -> str:
    """Build the user-turn prompt with all four contexts."""
    
    # Extract key fields for concise prompting
    cat_slug = category.get("slug", "")
    cat_voice = category.get("voice", {})
    cat_offers = category.get("offer_catalog", [])[:5]
    cat_peer_stats = category.get("peer_stats", {})
    cat_digest = category.get("digest", [])[:3]  # top 3 digest items
    cat_seasonal = category.get("seasonal_beats", [])[:2]
    cat_trends = category.get("trend_signals", [])[:2]

    merchant_id = merchant.get("merchant_id", "")
    merchant_identity = merchant.get("identity", {})
    merchant_name = merchant_identity.get("name", "")
    owner_name = merchant_identity.get("owner_first_name", "")
    merchant_lang = merchant_identity.get("languages", ["en"])
    merchant_sub = merchant.get("subscription", {})
    merchant_perf = merchant.get("performance", {})
    merchant_offers = merchant.get("offers", [])
    merchant_signals = merchant.get("signals", [])
    merchant_history = merchant.get("conversation_history", [])[-3:]  # last 3 turns
    merchant_cust_agg = merchant.get("customer_aggregate", {})
    merchant_reviews = merchant.get("review_themes", [])

    trigger_kind = trigger.get("kind", "")
    trigger_scope = trigger.get("scope", "merchant")
    trigger_payload = trigger.get("payload", {})
    trigger_urgency = trigger.get("urgency", 1)
    trigger_suppression = trigger.get("suppression_key", "")

    sections = []
    
    # CATEGORY
    sections.append(f"""=== CATEGORY: {cat_slug} ===
Voice: {json.dumps(cat_voice)}
Offer catalog (use these exact price formats): {json.dumps(cat_offers)}
Peer stats: {json.dumps(cat_peer_stats)}
Digest items (cite these, don't invent): {json.dumps(cat_digest)}
Seasonal beats: {json.dumps(cat_seasonal)}
Trend signals: {json.dumps(cat_trends)}""")

    # MERCHANT
    sections.append(f"""=== MERCHANT ===
ID: {merchant_id}
Name: {merchant_name} | Owner: {owner_name}
City: {merchant_identity.get('city')} | Locality: {merchant_identity.get('locality')}
Languages: {merchant_lang}
Verified: {merchant_identity.get('verified')}
Subscription: {json.dumps(merchant_sub)}
Performance (30d): {json.dumps(merchant_perf)}
Active offers: {json.dumps([o for o in merchant_offers if o.get('status') == 'active'])}
Signals: {merchant_signals}
Customer aggregate: {json.dumps(merchant_cust_agg)}
Review themes: {json.dumps(merchant_reviews)}
Recent conversation history (last 3 turns): {json.dumps(merchant_history)}""")

    # TRIGGER
    sections.append(f"""=== TRIGGER ===
Kind: {trigger_kind}
Scope: {trigger_scope}
Urgency: {trigger_urgency}/5
Suppression key: {trigger_suppression}
Payload: {json.dumps(trigger_payload)}""")

    # CUSTOMER (if present)
    if customer:
        sections.append(f"""=== CUSTOMER (message sent on merchant's behalf) ===
{json.dumps(customer, indent=2)}
NOTE: set send_as = "merchant_on_behalf" since this is a customer-facing message""")
    else:
        sections.append("=== CUSTOMER ===\nNone — this is a merchant-facing message. Set send_as = \"vera\"")

    # TASK
    sections.append(f"""=== YOUR TASK ===
Compose the best possible WhatsApp message for this exact context.

Trigger kind is "{trigger_kind}" (urgency={trigger_urgency}).
{"This is a CUSTOMER-FACING message — compose from merchant's voice, address the customer by name." if customer else "This is a MERCHANT-FACING message — address the merchant/owner by first name if you have it."}

{"Language preference: " + str(customer.get('identity', {}).get('language_pref', '')) if customer else "Match merchant's language preference: " + str(merchant_lang)}

Key constraints:
- ONLY use facts present in the contexts above — no hallucination
- {"Use peer/clinical tone" if cat_slug in ['dentists', 'pharmacies'] else "Use warm, friendly-peer tone"}
- CTA type: {"yes_stop for action trigger" if trigger_urgency >= 3 else "open_ended or none for info trigger"}
- Body: concise, punchy — aim for 3-5 sentences max
- End with the CTA (if any)

Respond ONLY with valid JSON.""")

    return "\n\n".join(sections)

def _call_gemini(user_prompt: str, max_retries: int = 2) -> dict:
    """Call Gemini API with retry logic. Returns parsed JSON output dict."""
    
    payload = {
        "model": "gemini-2.5-flash",
        "max_tokens": 1000,
        "temperature": 0,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": user_prompt}
        ]
    }

    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(
                "https://api.gemini.com/v1/messages",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "gemini-version": "2023-06-01",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            
            text = data["content"][0]["text"].strip()
            # Strip markdown fences if present
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)
            return json.loads(text)

        except (urllib.error.URLError, json.JSONDecodeError, KeyError) as e:
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Claude API call failed after {max_retries+1} attempts: {e}")

def _validate_and_repair(result: dict, trigger: dict, customer: Optional[dict]) -> dict:
    """Ensure output has all required fields and valid values."""
    
    valid_ctas = {"yes_stop", "open_ended", "none"}
    valid_send_as = {"vera", "merchant_on_behalf"}

    # Defaults
    if "body" not in result or not result["body"]:
        result["body"] = "Hi, checking in — is there anything I can help with today?"
    
    if result.get("cta") not in valid_ctas:
        # Infer from trigger urgency
        urgency = trigger.get("urgency", 1)
        result["cta"] = "yes_stop" if urgency >= 3 else "open_ended"
    
    if result.get("send_as") not in valid_send_as:
        result["send_as"] = "merchant_on_behalf" if customer else "vera"
    
    if "suppression_key" not in result or not result["suppression_key"]:
        result["suppression_key"] = trigger.get("suppression_key", f"msg:{trigger.get('id','unknown')}")
    
    if "rationale" not in result or not result["rationale"]:
        result["rationale"] = f"Responding to {trigger.get('kind','trigger')} trigger."

    # Force correct send_as
    if customer:
        result["send_as"] = "merchant_on_behalf"
    else:
        result["send_as"] = "vera"

    return result

def compose(
    category: dict,
    merchant: dict,
    trigger: dict,
    customer: Optional[dict] = None
) -> dict:
    """
    Main entry point for the judge harness.
    
    Args:
        category: CategoryContext dict
        merchant: MerchantContext dict
        trigger: TriggerContext dict
        customer: CustomerContext dict or None
    
    Returns:
        dict with keys: body, cta, send_as, suppression_key, rationale
    """
    user_prompt = _build_user_prompt(category, merchant, trigger, customer)
    result = _call_gemini(user_prompt)
    result = _validate_and_repair(result, trigger, customer)
    return result
