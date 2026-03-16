#!/usr/bin/env python3
"""
suggestion_reply_dnd.py
Tool script cho skill suggestion-reply-dnd

Usage:
  python3 tools/suggestion_reply_dnd.py --init
  python3 tools/suggestion_reply_dnd.py --update [--limit 200]
  python3 tools/suggestion_reply_dnd.py --query "giá phẫu thuật cận thị"
  python3 tools/suggestion_reply_dnd.py --stats
  python3 tools/suggestion_reply_dnd.py --export-csv [--output output.csv]
  python3 tools/suggestion_reply_dnd.py --rebuild-fts
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone

import requests

# ── Config ─────────────────────────────────────────────────────────────────────
PAGE_ID = "104552934399242"
ADMIN_FB_ID = "104552934399242"   # Page ID == admin sender ID
API_VERSION = "v21.0"
API_BASE = f"https://graph.facebook.com/{API_VERSION}"
DEFAULT_CRAWL_LIMIT = 200
MAX_MESSAGES_PER_CONV = 50
RATE_LIMIT_SLEEP = 0.3            # seconds between requests

# Paths (relative to workspace root — adjust if running from different dir)
_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.dirname(_DIR)
TOKEN_FILE = os.path.join(WORKSPACE, "credentials", "fb_page_token.txt")
DB_PATH = os.path.join(WORKSPACE, "memory", "suggestion_reply_dnd.db")
SCHEMA_FILE = os.path.join(WORKSPACE, "skills", "suggestion-reply-dnd", "scripts", "schema.sql")
CSV_DEFAULT_OUTPUT = os.path.join(WORKSPACE, "memory", "suggestion_reply_export.csv")


# ── Helpers ────────────────────────────────────────────────────────────────────
def load_token() -> str:
    if not os.path.exists(TOKEN_FILE):
        print(f"❌ Token file not found: {TOKEN_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(TOKEN_FILE, encoding="utf-8") as f:
        token = f.read().strip()
    if not token:
        print("❌ Token file is empty", file=sys.stderr)
        sys.exit(1)
    return token


def get_db() -> sqlite3.Connection:
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except (sqlite3.Error, OSError) as e:
        print(f"❌ Cannot open database: {e}", file=sys.stderr)
        sys.exit(1)


def fb_get(path: str, token: str, params: dict = None) -> dict:
    """Single FB Graph API GET with error handling."""
    url = f"{API_BASE}/{path}"
    p = {"access_token": token, **(params or {})}
    try:
        resp = requests.get(url, params=p, timeout=15)
        if resp.status_code == 429:
            print("⚠️  Rate limited — sleeping 60s...")
            time.sleep(60)
            resp = requests.get(url, params=p, timeout=15)
        data = resp.json()
    except requests.RequestException as e:
        print(f"❌ Network error: {e}", file=sys.stderr)
        return {}
    except (ValueError, json.JSONDecodeError) as e:
        print(f"❌ Invalid JSON response: {e}", file=sys.stderr)
        return {}
    if "error" in data:
        code = data["error"].get("code")
        msg = data["error"].get("message")
        if code == 190:
            print(f"❌ Token hết hạn hoặc không hợp lệ. Anh cần refresh token trong credentials/fb_page_token.txt", file=sys.stderr)
        else:
            print(f"❌ FB API Error [{code}]: {msg}", file=sys.stderr)
        return {}
    return data


def paginate(path: str, token: str, params: dict, max_items: int) -> tuple:
    """Paginate through FB API results.

    Returns:
        (results, had_error): tuple of list and bool indicating if any API errors occurred.
    """
    results = []
    had_error = False
    after = None
    while len(results) < max_items:
        p = {**params, "limit": min(50, max_items - len(results))}
        if after:
            p["after"] = after
        data = fb_get(path, token, p)
        if not data:
            had_error = True
            break
        items = data.get("data", [])
        results.extend(items)
        paging = data.get("paging", {})
        after = paging.get("cursors", {}).get("after")
        if not after or not items:
            break
        time.sleep(RATE_LIMIT_SLEEP)
    return results, had_error


def sanitize_fts_query(query: str) -> str:
    """Sanitize user input for FTS5 MATCH query.

    Strips FTS5 operators and wraps each token in double quotes.
    Returns empty string if no valid tokens remain.
    """
    # Remove FTS5 special characters
    cleaned = re.sub(r'[*"()+\-]', ' ', query)
    # Split into tokens and remove FTS5 keywords
    fts_keywords = {'NEAR', 'OR', 'AND', 'NOT'}
    tokens = [t for t in cleaned.split() if t.upper() not in fts_keywords and len(t) > 0]
    if not tokens:
        return ""
    # Wrap each token in double quotes for exact matching
    return " ".join(f'"{t}"' for t in tokens)


def _load_schema() -> str:
    """Load schema SQL from file."""
    if not os.path.exists(SCHEMA_FILE):
        print(f"❌ Schema file not found: {SCHEMA_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(SCHEMA_FILE, encoding="utf-8") as f:
        return f.read()


# ── Commands ───────────────────────────────────────────────────────────────────
def cmd_init():
    """Create DB + schema. If DB exists, also rebuild FTS index for migration."""
    schema = _load_schema()
    db_existed = os.path.exists(DB_PATH)
    conn = get_db()
    conn.executescript(schema)
    conn.commit()
    if db_existed:
        # Migration path: rebuild FTS for existing data
        _rebuild_fts_index(conn)
    conn.close()
    print(f"✅ DB initialized: {DB_PATH}")
    if db_existed:
        print("   ℹ️  FTS index rebuilt (migration from existing DB)")


def cmd_update(limit: int):
    """Crawl inbox and upsert into DB."""
    token = load_token()
    conn = get_db()

    # Ensure schema exists
    schema = _load_schema()
    conn.executescript(schema)
    conn.commit()

    print(f"🔄 Crawling up to {limit} conversations...")
    convs, convs_had_error = paginate(
        f"{PAGE_ID}/conversations",
        token,
        {"fields": "id,updated_time,message_count,participants"},
        limit,
    )

    # Check if paginate failed due to API error (e.g. token invalid)
    if not convs and convs_had_error:
        # API error — log error and exit
        conn.execute(
            "INSERT INTO crawl_log (crawled_at, conversations_added, messages_added, status) VALUES (?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), 0, 0, "error"),
        )
        conn.commit()
        conn.close()
        print("❌ Crawl thất bại — không thể kết nối API. Kiểm tra token.", file=sys.stderr)
        sys.exit(1)

    conv_added = 0
    msg_added = 0
    error_count = 0

    # Count conversation-list pagination errors toward error_count
    if convs_had_error:
        error_count += 1

    for conv in convs:
        conv_id = conv["id"]
        updated_time = conv.get("updated_time", "")
        message_count = conv.get("message_count", 0)

        # Participant info (first non-page participant = khách)
        participant_name = "Unknown"
        participant_id = ""
        for p in conv.get("participants", {}).get("data", []):
            if p["id"] != ADMIN_FB_ID:
                participant_name = p.get("name", "Facebook user")
                participant_id = p.get("id", "")
                break

        # Check if already crawled and up to date
        row = conn.execute(
            "SELECT last_updated FROM conversations WHERE id = ?", (conv_id,)
        ).fetchone()
        if row and row["last_updated"] == updated_time:
            continue  # no new messages

        # Crawl messages FIRST (before updating conversation checkpoint)
        msgs, msgs_had_error = paginate(
            f"{conv_id}/messages",
            token,
            {"fields": "id,from,message,created_time"},
            MAX_MESSAGES_PER_CONV,
        )

        if msgs_had_error and not msgs:
            # API error for this conversation — skip without updating checkpoint
            error_count += 1
            continue

        if msgs_had_error:
            error_count += 1

        # Insert messages
        conv_msg_added = 0
        conv_insert_failed = False
        for m in msgs:
            msg_id = m.get("id", "")
            from_info = m.get("from", {})
            from_id = from_info.get("id", "")
            from_name = from_info.get("name", "")
            is_admin = 1 if from_id == ADMIN_FB_ID else 0
            message_text = m.get("message")  # can be None for attachments
            created_time = m.get("created_time", "")

            if not message_text:
                continue  # skip stickers/attachments

            try:
                cursor = conn.execute(
                    """INSERT OR IGNORE INTO messages
                       (id, conversation_id, from_id, from_name, is_admin, message, created_time)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (msg_id, conv_id, from_id, from_name, is_admin, message_text, created_time),
                )
                if cursor.rowcount > 0:
                    conv_msg_added += 1
            except sqlite3.IntegrityError:
                pass  # Expected: duplicate message ID
            except Exception as e:
                print(f"⚠️  Error inserting message {msg_id}: {e}", file=sys.stderr)
                conv_insert_failed = True

        msg_added += conv_msg_added

        # Skip checkpoint if insert failures occurred (will re-crawl next time)
        if conv_insert_failed:
            error_count += 1
            continue

        # NOW upsert conversation checkpoint (after successful message fetch+insert)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO conversations (id, participant_name, participant_id, message_count, last_updated, crawled_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 message_count=excluded.message_count,
                 last_updated=excluded.last_updated,
                 crawled_at=excluded.crawled_at""",
            (conv_id, participant_name, participant_id, message_count, updated_time, now),
        )
        conv_added += 1

        time.sleep(RATE_LIMIT_SLEEP)

    # Determine crawl status
    if error_count == 0:
        status = "success"
    elif error_count > 0 and conv_added > 0:
        status = "partial"
    else:
        status = "error"

    # Log crawl
    conn.execute(
        "INSERT INTO crawl_log (crawled_at, conversations_added, messages_added, status) VALUES (?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), conv_added, msg_added, status),
    )
    conn.commit()

    total_stats = get_stats_dict(conn)
    conn.close()

    status_icon = {"success": "✅", "partial": "⚠️", "error": "❌"}.get(status, "✅")
    print(f"{status_icon} Đã thêm {conv_added} cuộc hội thoại mới, {msg_added} tin nhắn (status: {status})")
    if error_count > 0:
        print(f"   ⚠️  {error_count} conversations bị lỗi API")
    print(f"📊 Tổng DB: {total_stats['total_conversations']} conversations | {total_stats['total_messages']} messages")
    print(f"📅 Cập nhật lần cuối: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")


def cmd_query(query: str, top_n: int = 5):
    """Search conversations and return context for reply suggestion."""
    # Handle empty/whitespace-only query
    if not query or not query.strip():
        print(json.dumps({"found": 0, "results": [], "query": query or ""}))
        return

    conn = get_db()

    # Sanitize query for FTS5
    safe_query = sanitize_fts_query(query)

    rows = None
    # Try FTS search if we have valid tokens after sanitization
    if safe_query:
        try:
            rows = conn.execute(
                """SELECT m.conversation_id, m.message as customer_msg, m.created_time
                   FROM messages_fts fts
                   JOIN messages m ON m.rowid = fts.rowid
                   WHERE fts.message MATCH ? AND m.is_admin = 0
                   ORDER BY rank
                   LIMIT ?""",
                (safe_query, top_n),
            ).fetchall()
        except sqlite3.Error:
            rows = None  # Will fallback to LIKE

    # Fallback: LIKE search (if FTS failed or had no valid tokens)
    if rows is None:
        keywords = [kw for kw in query.lower().split() if len(kw) > 0]
        if not keywords:
            print(json.dumps({"found": 0, "results": [], "query": query}))
            conn.close()
            return
        like_clauses = " OR ".join(["LOWER(message) LIKE ?" for _ in keywords])
        params = [f"%{kw}%" for kw in keywords] + [0, top_n]
        rows = conn.execute(
            f"""SELECT conversation_id, message as customer_msg, created_time
                FROM messages
                WHERE ({like_clauses}) AND is_admin = ?
                ORDER BY created_time DESC
                LIMIT ?""",
            params,
        ).fetchall()

    if not rows:
        print(json.dumps({"found": 0, "results": [], "query": query}))
        conn.close()
        return

    results = []
    seen_conv_ids = set()
    for row in rows:
        conv_id = row["conversation_id"]
        if conv_id in seen_conv_ids:
            continue
        seen_conv_ids.add(conv_id)

        # Get full conversation thread
        thread = conn.execute(
            """SELECT from_name, is_admin, message, created_time
               FROM messages
               WHERE conversation_id = ?
               ORDER BY created_time ASC""",
            (conv_id,),
        ).fetchall()

        thread_list = []
        for t in thread:
            thread_list.append({
                "role": "admin" if t["is_admin"] else "customer",
                "name": t["from_name"],
                "message": t["message"],
                "time": t["created_time"],
            })

        results.append({
            "conversation_id": conv_id,
            "trigger_message": row["customer_msg"],
            "thread": thread_list,
        })

    print(json.dumps({"found": len(results), "query": query, "results": results}, ensure_ascii=False, indent=2))
    conn.close()


def get_stats_dict(conn: sqlite3.Connection = None) -> dict:
    """Get DB statistics. Accepts optional connection to reuse."""
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
    total_conv = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    total_msg = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    last_crawl = conn.execute("SELECT crawled_at FROM crawl_log ORDER BY id DESC LIMIT 1").fetchone()
    last_crawl_time = last_crawl[0] if last_crawl else "Never"
    if close_conn:
        conn.close()
    return {
        "total_conversations": total_conv,
        "total_messages": total_msg,
        "last_crawl": last_crawl_time,
    }


def cmd_stats():
    """Show DB stats."""
    s = get_stats_dict()
    print(f"📊 Thống kê DB: {DB_PATH}")
    print(f"   Conversations : {s['total_conversations']}")
    print(f"   Messages      : {s['total_messages']}")
    print(f"   Cập nhật lần cuối: {s['last_crawl']}")


def cmd_export_csv(output: str):
    """Export all messages to CSV."""
    print("⚠️  CSV chứa thông tin khách hàng — không chia sẻ hoặc commit vào Git", file=sys.stderr)
    conn = get_db()
    rows = conn.execute(
        """SELECT c.participant_name, m.is_admin, m.from_name, m.message, m.created_time
           FROM messages m
           JOIN conversations c ON c.id = m.conversation_id
           ORDER BY m.created_time ASC"""
    ).fetchall()
    conn.close()
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["participant_name", "is_admin", "from_name", "message", "created_time"])
        for r in rows:
            writer.writerow([r["participant_name"], r["is_admin"], r["from_name"], r["message"], r["created_time"]])
    print(f"✅ Exported {len(rows)} messages to {output}")


def _rebuild_fts_index(conn: sqlite3.Connection):
    """Rebuild the FTS5 index from scratch using current messages table."""
    conn.execute("DELETE FROM messages_fts")
    conn.execute(
        """INSERT INTO messages_fts(rowid, id, conversation_id, from_name, message)
           SELECT rowid, id, conversation_id, from_name, message FROM messages"""
    )
    conn.commit()


def cmd_rebuild_fts():
    """Rebuild FTS index from existing messages."""
    conn = get_db()
    schema = _load_schema()
    conn.executescript(schema)
    conn.commit()
    _rebuild_fts_index(conn)
    total_msg = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()
    print(f"✅ FTS index rebuilt — {total_msg} messages indexed")


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="suggestion_reply_dnd — Inbox search tool for DND Messenger")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--init", action="store_true", help="Init DB schema")
    group.add_argument("--update", action="store_true", help="Crawl inbox")
    group.add_argument("--query", type=str, help="Search conversations by keyword")
    group.add_argument("--stats", action="store_true", help="Show DB stats")
    group.add_argument("--export-csv", action="store_true", help="Export to CSV")
    group.add_argument("--rebuild-fts", action="store_true", help="Rebuild FTS index")

    parser.add_argument("--limit", type=int, default=DEFAULT_CRAWL_LIMIT, help="Max conversations to crawl")
    parser.add_argument("--output", type=str, default=CSV_DEFAULT_OUTPUT, help="CSV output file")
    parser.add_argument("--top", type=int, default=5, help="Top N results for query")

    args = parser.parse_args()

    if args.init:
        cmd_init()
    elif args.update:
        cmd_update(args.limit)
    elif args.query:
        cmd_query(args.query, args.top)
    elif args.stats:
        cmd_stats()
    elif args.export_csv:
        cmd_export_csv(args.output)
    elif args.rebuild_fts:
        cmd_rebuild_fts()


if __name__ == "__main__":
    main()
