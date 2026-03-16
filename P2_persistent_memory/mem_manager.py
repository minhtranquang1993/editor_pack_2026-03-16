#!/usr/bin/env python3
"""
persistent-memory: Save + recall structured memories with shelf categories.

Usage:
    python3 mem_manager.py --save --shelf decisions --content "..." --tags "tag1,tag2"
    python3 mem_manager.py --recall "query" [--shelf decisions]
    python3 mem_manager.py --list [--shelf decisions]
    python3 mem_manager.py --stats
    python3 mem_manager.py --delete <id>
"""

import argparse
import copy
import json
import os
import random
import string
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(os.environ.get("OPENCLAW_WORKSPACE", "/root/.openclaw/workspace"))
MEM_INDEX = WORKSPACE / "memory" / "index.json"

VALID_SHELVES = ["decisions", "patterns", "errors", "solutions", "context", "config"]

TAG_RULES = [
    (["api", "token", "key"],           ["api-key", "config"]),
    (["error", "lỗi", "fix"],           ["error"]),
    (["model", "provider"],             ["model", "openclaw"]),
    (["seo", "keyword"],                ["seo", "content"]),
    (["deploy", "server"],              ["devops"]),
    (["python", "code", "script"],      ["code"]),
]

DEFAULT_INDEX = {
    "version": "1.0.0",
    "mems": [],
    "shelves": {s: 0 for s in VALID_SHELVES},
    "updated_at": None,
}


def load_index() -> dict:
    """Load memory index from file."""
    if MEM_INDEX.exists():
        try:
            data = json.loads(MEM_INDEX.read_text(encoding="utf-8"))
            # Ensure all shelves exist
            if "shelves" not in data:
                data["shelves"] = {s: 0 for s in VALID_SHELVES}
            for s in VALID_SHELVES:
                if s not in data["shelves"]:
                    data["shelves"][s] = 0
            if "mems" not in data:
                data["mems"] = []
            return data
        except (json.JSONDecodeError, KeyError):
            return copy.deepcopy(DEFAULT_INDEX)
    return copy.deepcopy(DEFAULT_INDEX)


def save_index(data: dict):
    """Atomic write: write to .tmp then rename."""
    data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    MEM_INDEX.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = MEM_INDEX.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(MEM_INDEX)


def generate_id() -> str:
    """Generate mem_{unix_ms}_{random4}."""
    unix_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    rand4 = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"mem_{unix_ms}_{rand4}"


def auto_tag(content: str) -> list:
    """Auto-tag content based on TAG_RULES."""
    content_lower = content.lower()
    tags = set()
    for keywords, tag_list in TAG_RULES:
        for kw in keywords:
            if kw in content_lower:
                tags.update(tag_list)
                break
    return sorted(tags)


def similarity(a: str, b: str) -> float:
    """Simple word-overlap similarity (Jaccard)."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def cmd_save(shelf: str, content: str, tags_str: str, force: bool):
    """Save a new memory entry."""
    if shelf not in VALID_SHELVES:
        print(f"❌ Invalid shelf: '{shelf}'. Valid: {', '.join(VALID_SHELVES)}")
        return False

    index = load_index()

    # Dedup check (>80% similarity in same shelf)
    if not force:
        for mem in index["mems"]:
            if mem.get("shelf") == shelf and similarity(mem.get("content", ""), content) > 0.8:
                print(f"⚠️ Duplicate detected in [{shelf}] — mem {mem['id']}")
                print(f"  Existing: {mem['content'][:80]}...")
                print("  Use --force to save anyway.")
                return False

    # Parse tags
    if tags_str:
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
    else:
        tags = auto_tag(content)

    mem_id = generate_id()
    entry = {
        "id": mem_id,
        "shelf": shelf,
        "content": content,
        "tags": tags,
        "session_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "created_at": int(datetime.now(timezone.utc).timestamp() * 1000),
    }

    index["mems"].append(entry)
    index["shelves"][shelf] = index["shelves"].get(shelf, 0) + 1
    save_index(index)

    total = len(index["mems"])
    content_preview = content[:60] + "..." if len(content) > 60 else content
    tags_display = ", ".join(tags) if tags else "none"
    print(f"💾 Saved to [{shelf}] — {content_preview} Tags: {tags_display}. Total: {total} mems.")
    return True


def cmd_recall(query: str, shelf: str = None):
    """Search memories by keyword match."""
    index = load_index()
    mems = index.get("mems", [])

    if not mems:
        print("📭 No memories found.")
        return

    query_lower = query.lower()
    query_words = set(query_lower.split())

    scored = []
    for mem in mems:
        if shelf and mem.get("shelf") != shelf:
            continue

        score = 0
        content_lower = mem.get("content", "").lower()
        mem_tags = [t.lower() for t in mem.get("tags", [])]

        # Keyword match in content
        for word in query_words:
            if word in content_lower:
                score += 2

        # Exact tag match
        for word in query_words:
            if word in mem_tags:
                score += 3

        if score > 0:
            scored.append((score, mem))

    if not scored:
        print(f"🔍 No results for '{query}'" + (f" in [{shelf}]" if shelf else ""))
        return

    # Sort by score desc, then newest first
    scored.sort(key=lambda x: (-x[0], -x[1].get("created_at", 0)))

    # Top 5
    results = scored[:5]
    print(f"🔍 Found {len(scored)} results for '{query}'" + (f" in [{shelf}]" if shelf else "") + f" (showing top {len(results)}):\n")

    for _, mem in results:
        print(f"  [{mem.get('shelf', '?')}] {mem['id']} ({mem.get('session_date', 'N/A')})")
        print(f"    {mem.get('content', '')}")
        tags_display = ", ".join(mem.get("tags", []))
        print(f"    Tags: {tags_display}\n")


def cmd_list(shelf: str = None):
    """List all memories or filter by shelf."""
    index = load_index()
    mems = index.get("mems", [])

    if shelf:
        mems = [m for m in mems if m.get("shelf") == shelf]

    if not mems:
        label = f" in [{shelf}]" if shelf else ""
        print(f"📭 No memories{label}.")
        return

    print(f"📋 Memories{' in [' + shelf + ']' if shelf else ''} ({len(mems)}):\n")
    for mem in mems:
        tags_display = ", ".join(mem.get("tags", []))
        print(f"  [{mem.get('shelf', '?')}] {mem['id']} ({mem.get('session_date', 'N/A')})")
        print(f"    {mem.get('content', '')}")
        print(f"    Tags: {tags_display}\n")


def cmd_stats():
    """Show memory statistics."""
    index = load_index()
    mems = index.get("mems", [])
    shelves = index.get("shelves", {})

    total = len(mems)
    print(f"📊 Memory Stats:")
    print(f"  Total: {total} mems")
    print(f"  Updated: {index.get('updated_at', 'N/A')}\n")

    print("  Shelves:")
    for s in VALID_SHELVES:
        count = shelves.get(s, 0)
        bar = "█" * count + "░" * max(0, 5 - count)
        print(f"    {s:12s}: {count:3d} {bar}")

    if mems:
        print("\n  3 Newest:")
        newest = sorted(mems, key=lambda m: m.get("created_at", 0), reverse=True)[:3]
        for mem in newest:
            print(f"    [{mem.get('shelf', '?')}] {mem.get('content', '')[:70]}...")


def cmd_delete(mem_id: str):
    """Delete a memory entry by ID."""
    index = load_index()
    mems = index.get("mems", [])

    found = None
    for i, mem in enumerate(mems):
        if mem.get("id") == mem_id:
            found = (i, mem)
            break

    if not found:
        print(f"❌ Memory not found: {mem_id}")
        return False

    idx, mem = found
    shelf = mem.get("shelf", "")
    mems.pop(idx)
    index["mems"] = mems

    if shelf in index.get("shelves", {}):
        index["shelves"][shelf] = max(0, index["shelves"][shelf] - 1)

    save_index(index)
    print(f"🗑️ Deleted: {mem_id} from [{shelf}]")
    return True


def main():
    parser = argparse.ArgumentParser(description="Persistent Memory Manager")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--save", action="store_true", help="Save a new memory")
    group.add_argument("--recall", type=str, nargs="?", const="", help="Recall memories by query")
    group.add_argument("--list", action="store_true", help="List all memories")
    group.add_argument("--stats", action="store_true", help="Show memory stats")
    group.add_argument("--delete", type=str, help="Delete memory by ID")

    parser.add_argument("--shelf", type=str, choices=VALID_SHELVES, help="Filter by shelf")
    parser.add_argument("--content", type=str, help="Memory content (for --save)")
    parser.add_argument("--tags", type=str, help="Comma-separated tags (for --save)")
    parser.add_argument("--force", action="store_true", help="Force save even if duplicate detected")

    args = parser.parse_args()

    if args.save:
        if not args.shelf:
            print("❌ --shelf is required for --save")
            sys.exit(1)
        if not args.content:
            print("❌ --content is required for --save")
            sys.exit(1)
        cmd_save(args.shelf, args.content, args.tags, args.force)
    elif args.recall is not None:
        if not args.recall:
            # No query = list all
            cmd_list(args.shelf)
        else:
            cmd_recall(args.recall, args.shelf)
    elif args.list:
        cmd_list(args.shelf)
    elif args.stats:
        cmd_stats()
    elif args.delete:
        cmd_delete(args.delete)


if __name__ == "__main__":
    main()
