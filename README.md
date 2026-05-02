# Vera Bot — magicpin AI Challenge Submission

**Submitted by**: Tanu Luthra  
**Model**: `claude-sonnet-4-20250514`  
**Approach**: Trigger-routed LLM composer with post-LLM validation

---

## Approach

### Core Architecture

`bot.py` implements a single `compose()` function that:

1. **Builds a rich, structured prompt** from all four contexts (category, merchant, trigger, customer), extracting only the fields that matter for message composition — no context stuffing.
2. **Routes trigger types** via the system prompt's trigger-type guidance rather than hard-coded branches. This keeps the routing generalizable to trigger types the judge introduces post-submission.
3. **Calls Claude Sonnet** at `temperature=0` for determinism.
4. **Post-validates** the output: ensures all five required fields are present, enforces `send_as` based on customer presence, falls back to sensible defaults.

### What the system prompt enforces

- **Anti-patterns are explicitly listed** (generic discounts, buried CTAs, preambles, re-introduction) — the LLM treats this as a checklist.
- **Compulsion levers are enumerated** with examples — specificity, loss aversion, social proof, effort externalization, curiosity, asking the merchant, single binary commitment.
- **Trigger-type guidance** maps each trigger kind to the appropriate tone, CTA type, and what to anchor the message on.
- **No hallucination** is a hard rule: the model is told to only use facts present in the provided contexts.

### Prompt design choices

- Category context is trimmed to the top 3 digest items (most relevant to current trigger) rather than the full list.
- Merchant conversation history is limited to last 3 turns (prevents re-sending variations of what was already said).
- Customer context includes a directive to set `send_as = "merchant_on_behalf"` — this has never failed in testing.
- Language matching is included as an explicit instruction, with the merchant's `languages` array and customer's `language_pref` both passed in.

---

## Multi-turn (conversation_handlers.py)

The optional `conversation_handlers.py` implements:

- **Auto-reply detection** via regex patterns for common WhatsApp Business canned responses (English and Hindi). After 2 consecutive auto-replies, Vera exits gracefully.
- **Intent detection** for action-confirming ("yes", "go ahead", "haan", "ok") and stop-signaling ("nahi", "not interested", "band karo") messages — routes to immediate action or graceful exit respectively.
- **LLM-powered reply generation** for ambiguous turns, with conversation history passed as context.
- **Graceful exit handling**: the `end` action type is returned when the merchant is clearly not interested, avoiding turn-burning.

---

## Tradeoffs

| Choice | Rationale |
|---|---|
| Single-prompt vs. multi-step | Single prompt keeps latency well under 30s; avoids error compounding across steps |
| Claude Sonnet over Haiku | Sonnet's instruction-following is meaningfully better for complex multi-constraint prompts; cost is acceptable at 30 submissions |
| Post-LLM validation over re-prompting | Simpler failure path; the primary failure mode is wrong `cta` type, which is easy to repair deterministically |
| No retrieval/embedding | Dataset fits in a single prompt; retrieval overhead would add latency for marginal gain at 30-message scale |

---

## What additional context would have helped most

1. **Auto-reply pattern corpus** — production Vera has seen millions of WhatsApp Business auto-replies; a 50-sample list of real patterns would make detection far more robust.
2. **Merchant engagement history tags** — knowing whether past messages were opened, CTAs tapped, or ignored would let the bot avoid repeating styles that haven't worked for a specific merchant.
3. **Language detection per-turn** — the dataset has `language_pref` at the identity level, but merchants frequently code-switch mid-conversation. A per-turn detected language would help.
4. **Category-specific CTA conversion rates** — knowing that dentists respond better to `open_ended` vs `yes_stop` (or vice versa) would let the system pick CTAs based on evidence, not heuristics.
