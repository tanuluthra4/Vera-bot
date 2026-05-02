#!/usr/bin/env python3
"""
Generate submission.jsonl for the 30 canonical test pairs.
Run from the magicpin-vera/ directory:
    python generate_submission.py
"""

import json
import os
import sys
import time
from pathlib import Path

# Add current dir to path so we can import bot
sys.path.insert(0, str(Path(__file__).parent))
import bot

DATASET_DIR = Path(__file__).parent / "dataset" / "expanded"
OUTPUT_FILE = Path(__file__).parent / "submission.jsonl"


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def load_contexts(merchant_id: str, trigger_id: str, customer_id: str | None):
    """Load all 4 contexts for a test pair."""
    
    # Load merchant
    merchant_path = DATASET_DIR / "merchants" / f"{merchant_id}.json"
    merchant = load_json(merchant_path)
    
    # Get category slug from merchant
    cat_slug = merchant.get("category_slug", "")
    category_path = DATASET_DIR / "categories" / f"{cat_slug}.json"
    category = load_json(category_path)
    
    # Load trigger
    trigger_path = DATASET_DIR / "triggers" / f"{trigger_id}.json"
    trigger = load_json(trigger_path)
    
    # Load customer (if any)
    customer = None
    if customer_id:
        customer_path = DATASET_DIR / "customers" / f"{customer_id}.json"
        customer = load_json(customer_path)
    
    return category, merchant, trigger, customer


def main():
    test_pairs_path = DATASET_DIR / "test_pairs.json"
    test_pairs = load_json(test_pairs_path)["pairs"]
    
    print(f"Generating {len(test_pairs)} submissions...")
    
    results = []
    for i, pair in enumerate(test_pairs):
        test_id = pair["test_id"]
        merchant_id = pair["merchant_id"]
        trigger_id = pair["trigger_id"]
        customer_id = pair.get("customer_id")
        
        print(f"  [{i+1:2d}/30] {test_id}: {trigger_id[:45]}...", end="", flush=True)
        
        try:
            category, merchant, trigger, customer = load_contexts(merchant_id, trigger_id, customer_id)
            result = bot.compose(category, merchant, trigger, customer)
            
            entry = {
                "test_id": test_id,
                "body": result["body"],
                "cta": result["cta"],
                "send_as": result["send_as"],
                "suppression_key": result["suppression_key"],
                "rationale": result["rationale"]
            }
            results.append(entry)
            print(f" ✓ ({result['cta']}, {result['send_as']})")
            
        except Exception as e:
            print(f" ✗ ERROR: {e}")
            # Add a placeholder so we don't skip the test_id
            results.append({
                "test_id": test_id,
                "body": f"[ERROR generating message: {e}]",
                "cta": "open_ended",
                "send_as": "vera",
                "suppression_key": f"error:{test_id}",
                "rationale": "Error during generation"
            })
        
        # Be a bit nice to the API — small delay between calls
        if i < len(test_pairs) - 1:
            time.sleep(0.5)
    
    # Write JSONL
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for entry in results:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    
    print(f"\nDone! Wrote {len(results)} lines to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
