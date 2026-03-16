#!/usr/bin/env python3
"""
smart-memory: Extract + deduplicate facts từ chat history vào structured memory.
Usage: python3 extract_facts.py --messages '[{"role":"user","content":"..."}]' [--dry-run]
"""

import json
import os
import sys
import argparse
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

WORKSPACE = Path("/root/.openclaw/workspace")
MEMORY_FILE = Path(os.environ.get("SMART_MEMORY_FILE", 
    str(WORKSPACE / "memory" / "smart-memory.json")))
SECRETS_FILE = WORKSPACE / "credentials" / "smart_memory_secrets.json"

# TTL defaults (days) per category
CATEGORY_TTL = {
    "preference":     None,   # vĩnh viễn
    "decision":       30,
    "task_status":    7,
    "fact_personal":  None,   # vĩnh viễn
    "fact_temp":      1,
    "project_context":90,
    "relationship":   None,
    "learning":       60,
}

SYSTEM_PROMPT = """You are a memory extraction AI. Given a list of chat messages, extract important facts.

Output ONLY a valid JSON array of fact objects. Each object:
{
  "fact": "concise factual statement (1 sentence)",
  "category": one of [preference, decision, task_status, fact_personal, fact_temp, project_context, relationship, learning],
  "subject": "who/what this is about (e.g. 'Minh', 'TikTok task', 'DND ads')",
  "confidence": "high" | "medium" | "low",
  "merge_key": "short dedup key, e.g. 'proactive_style' or 'tiktok_download_task'"
}

Rules:
- Extract only meaningful, reusable facts — skip greetings, trivial chatter, temp info like weather/gold price (mark as fact_temp)
- If user corrects themselves (e.g. "hôm qua tôi đi mall" after "hôm nay tôi đi mall"), extract the CORRECTED fact only
- For task_status: include current status (in_progress / hold / done)
- Do NOT invent facts not present in messages
- Output only the JSON array, no explanation
"""

def load_memory() -> list:
    if MEMORY_FILE.exists():
        try:
            return json.loads(MEMORY_FILE.read_text())
        except:
            return []
    return []

def save_memory(facts: list):
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(facts, ensure_ascii=False, indent=2))

def prune_expired(facts: list) -> list:
    now = datetime.now(timezone.utc)
    result = []
    for f in facts:
        expires = f.get("expires_at")
        if expires is None:
            result.append(f)
        else:
            exp_dt = datetime.fromisoformat(expires)
            if exp_dt > now:
                result.append(f)
    return result

def merge_facts(existing: list, new_facts: list) -> tuple[list, int, int]:
    """Merge new facts into existing, dedup by merge_key. Returns (merged, added, updated)."""
    added = updated = 0
    by_key = {f.get("merge_key", f["fact"][:40]): i for i, f in enumerate(existing)}
    result = list(existing)
    
    for nf in new_facts:
        key = nf.get("merge_key", nf["fact"][:40])
        cat = nf.get("category", "learning")
        ttl = CATEGORY_TTL.get(cat)
        
        # Compute expires_at
        if ttl is not None:
            expires = (datetime.now(timezone.utc) + timedelta(days=ttl)).isoformat()
        else:
            expires = None
        
        nf["expires_at"] = expires
        nf["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        if key in by_key:
            idx = by_key[key]
            old_fact = result[idx]["fact"]
            if old_fact != nf["fact"]:
                nf["previous"] = old_fact  # giữ lịch sử
                result[idx] = nf
                updated += 1
        else:
            nf["created_at"] = nf["updated_at"]
            result.append(nf)
            by_key[key] = len(result) - 1
            added += 1
    
    return result, added, updated

def load_smart_memory_secrets() -> dict:
    if not SECRETS_FILE.exists():
        raise RuntimeError(f"Missing secrets file: {SECRETS_FILE}")
    data = json.loads(SECRETS_FILE.read_text(encoding="utf-8"))
    required = ["claudible_url", "claudible_key", "model"]
    missing = [k for k in required if not data.get(k)]
    if missing:
        raise RuntimeError(f"Missing required keys in {SECRETS_FILE.name}: {', '.join(missing)}")
    return data


def call_llm(messages_json: str) -> list:
    """Call Haiku via Claudible provider."""
    sec = load_smart_memory_secrets()
    CLAUDIBLE_URL = sec["claudible_url"]
    CLAUDIBLE_KEY = sec["claudible_key"]
    MODEL = sec["model"]

    resp = requests.post(
        CLAUDIBLE_URL,
        headers={"Authorization": f"Bearer {CLAUDIBLE_KEY}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "max_tokens": 1024,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Extract facts from:\n{messages_json}"}
            ]
        },
        timeout=30
    )

    if resp.status_code != 200:
        raise Exception(f"LLM error {resp.status_code}: {resp.text[:200]}")

    content = resp.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown code fences if present
    if "```" in content:
        import re
        content = re.sub(r'```\w*\n?', '', content).strip()

    return json.loads(content)

def main():
    parser = argparse.ArgumentParser(description="Extract facts from chat messages into smart memory")
    parser.add_argument("--messages", required=True, help="JSON array of chat messages")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    parser.add_argument("--list", action="store_true", help="List current memory")
    parser.add_argument("--prune", action="store_true", help="Prune expired facts only")
    args = parser.parse_args()

    existing = load_memory()

    if args.list:
        existing = prune_expired(existing)
        print(f"📚 Smart Memory ({len(existing)} facts):\n")
        for f in existing:
            exp = f.get("expires_at", "∞")[:10] if f.get("expires_at") else "∞"
            print(f"  [{f.get('category','?')}] {f['fact']}")
            print(f"    key={f.get('merge_key','?')} | expires={exp} | conf={f.get('confidence','?')}")
        return

    if args.prune:
        before = len(existing)
        existing = prune_expired(existing)
        after = len(existing)
        if not args.dry_run:
            save_memory(existing)
        print(f"🗑️  Pruned {before - after} expired facts. Remaining: {after}")
        return

    # Extract new facts
    try:
        messages = json.loads(args.messages)
    except json.JSONDecodeError as e:
        print(f"❌ Invalid messages JSON: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"🧠 Extracting facts from {len(messages)} messages...")
    
    try:
        new_facts = call_llm(json.dumps(messages, ensure_ascii=False))
    except Exception as e:
        print(f"❌ LLM extraction failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"✅ Extracted {len(new_facts)} raw facts")

    # Prune expired first
    existing = prune_expired(existing)

    # Merge
    merged, added, updated = merge_facts(existing, new_facts)

    print(f"➕ Added: {added} | 🔄 Updated: {updated} | 📦 Total: {len(merged)}")

    if args.dry_run:
        print("\n📋 Preview (not saved):")
        for f in new_facts:
            print(f"  [{f.get('category')}] {f['fact']} (key={f.get('merge_key')})")
    else:
        save_memory(merged)
        print(f"💾 Saved to {MEMORY_FILE}")

    # Print summary
    print("\n📊 Category breakdown:")
    from collections import Counter
    cats = Counter(f.get("category","?") for f in merged)
    for cat, count in cats.most_common():
        print(f"  {cat}: {count}")

if __name__ == "__main__":
    main()
