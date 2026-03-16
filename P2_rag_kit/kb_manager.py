#!/usr/bin/env python3
"""
rag-kit KB Manager: Ingest URLs, search, list, and manage knowledge base.

Usage:
    python3 kb_manager.py --ingest <url>
    python3 kb_manager.py --search "<query>"
    python3 kb_manager.py --list [--tag <tag>]
    python3 kb_manager.py --summary
    python3 kb_manager.py --delete <id>
"""

import argparse
import copy
import json
import os
import random
import re
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(os.environ.get("OPENCLAW_WORKSPACE", "/root/.openclaw/workspace"))
KB_INDEX = WORKSPACE / "memory" / "kb" / "index.json"
KB_ARTICLES_DIR = WORKSPACE / "memory" / "kb" / "articles"
KB_ATTACH_DIR = WORKSPACE / "memory" / "kb" / "attachments"

TAG_RULES = {
    ("seo", "keyword", "ranking", "serp"): ["seo", "marketing"],
    ("n8n", "automation", "workflow", "make"): ["automation", "n8n"],
    ("vận chuyển", "logistics", "chuyển nhà"): ["thanh-hung", "logistics"],
    ("ai", "agent", "llm", "gpt", "claude"): ["ai", "tools"],
    ("facebook", "google ads", "tiktok ads"): ["ads", "marketing"],
    ("python", "code", "script", "api"): ["code", "automation"],
}

DEFAULT_INDEX = {
    "version": "1.0.0",
    "articles": [],
    "total": 0,
    "updated_at": None,
}


def load_index() -> dict:
    """Load KB index from file."""
    if KB_INDEX.exists():
        try:
            data = json.loads(KB_INDEX.read_text(encoding="utf-8"))
            if "articles" not in data:
                data["articles"] = []
            if "total" not in data:
                data["total"] = len(data["articles"])
            return data
        except (json.JSONDecodeError, KeyError):
            return copy.deepcopy(DEFAULT_INDEX)
    return copy.deepcopy(DEFAULT_INDEX)


def save_index(data: dict):
    """Save KB index with atomic write."""
    data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["total"] = len(data.get("articles", []))
    KB_INDEX.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = KB_INDEX.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(KB_INDEX)


def generate_id() -> str:
    """Generate kb_{unix_ms}_{random4}."""
    unix_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    rand4 = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"kb_{unix_ms}_{rand4}"


def url_to_slug(url: str, max_len: int = 50) -> str:
    """Convert URL to filesystem-safe slug."""
    # Strip protocol
    slug = re.sub(r'^https?://', '', url)
    # Replace non-alphanumeric with dash
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', slug.lower())
    # Strip leading/trailing dashes
    slug = slug.strip('-')
    return slug[:max_len]


def auto_tag(content: str) -> list:
    """Auto-tag content based on TAG_RULES."""
    content_lower = content.lower()
    tags = set()
    for keywords, tag_list in TAG_RULES.items():
        for kw in keywords:
            if kw in content_lower:
                tags.update(tag_list)
                break
    return sorted(tags)


def extract_text_from_html(html: str) -> str:
    """Extract text from HTML. Try html2text, fallback to regex."""
    try:
        import html2text
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        return h.handle(html)
    except ImportError:
        pass

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        # Remove script and style elements
        for el in soup(["script", "style"]):
            el.decompose()
        return soup.get_text(separator="\n", strip=True)
    except ImportError:
        pass

    # Last resort: regex strip tags
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_title(html: str, text: str) -> str:
    """Extract title from HTML h1 or title tag."""
    # Try h1
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.IGNORECASE | re.DOTALL)
    if m:
        return re.sub(r'<[^>]+>', '', m.group(1)).strip()

    # Try title tag
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
    if m:
        return re.sub(r'<[^>]+>', '', m.group(1)).strip()

    # Fallback: first line of text
    first_line = text.split('\n')[0].strip()
    return first_line[:100] if first_line else "Untitled"


def extract_summary(text: str) -> str:
    """Extract first 2 sentences as summary."""
    # Split by sentence-ending punctuation
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    summary_parts = []
    for s in sentences:
        s = s.strip()
        if s and len(s) > 10:
            summary_parts.append(s)
        if len(summary_parts) >= 2:
            break
    return " ".join(summary_parts) if summary_parts else text[:200]


def chunk_text(text: str, target_words: int = 500) -> list:
    """Split text into ~500-word chunks, preserving markdown headers."""
    lines = text.split('\n')
    chunks = []
    current_chunk = []
    current_word_count = 0

    for line in lines:
        words_in_line = len(line.split())

        # If this is a header and current chunk is large enough, start new chunk
        if line.strip().startswith('#') and current_word_count >= target_words * 0.5:
            if current_chunk:
                chunks.append('\n'.join(current_chunk))
            current_chunk = [line]
            current_word_count = words_in_line
        else:
            current_chunk.append(line)
            current_word_count += words_in_line

            # Split if exceeding target
            if current_word_count >= target_words:
                chunks.append('\n'.join(current_chunk))
                current_chunk = []
                current_word_count = 0

    if current_chunk:
        chunks.append('\n'.join(current_chunk))

    return chunks if chunks else [text]


def cmd_ingest(url: str, force: bool = False):
    """Ingest a URL into the knowledge base."""
    try:
        import requests
    except ImportError:
        print("❌ Missing dependency: requests. Install: pip install requests")
        return False

    index = load_index()

    # Dedup check
    if not force:
        for article in index.get("articles", []):
            if article.get("url") == url:
                print(f"⚠️ Already in KB (id: {article['id']}, ingested: {article.get('ingested_at', 'N/A')}).")
                print("  Use --force to re-ingest.")
                return False

    # Validate URL scheme and host (SSRF mitigation)
    import ipaddress
    import socket
    from urllib.parse import urlparse, urljoin
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        print(f"❌ Unsupported URL scheme: {parsed.scheme}. Only http/https allowed.")
        return False
    hostname = parsed.hostname
    if not hostname:
        print("❌ URL missing hostname.")
        return False

    def _is_safe_host(host: str) -> bool:
        """Resolve hostname to IPs and check all are global (non-private/loopback/link-local)."""
        try:
            addr_infos = socket.getaddrinfo(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror:
            return True  # DNS failure → let requests handle it
        for info in addr_infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
        return True

    if not _is_safe_host(hostname):
        print(f"❌ Blocked: URL resolves to internal/private IP: {hostname}")
        return False

    # Fetch URL (no automatic redirects — validate each hop)
    print(f"🌐 Fetching: {url}")
    try:
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (OpenClaw KB Manager)"
        }, allow_redirects=False)

        # Follow redirects manually with SSRF check on each hop
        max_redirects = 5
        current_url = url
        for _ in range(max_redirects):
            if resp.status_code not in (301, 302, 303, 307, 308):
                break
            redirect_url = resp.headers.get("Location", "")
            if not redirect_url:
                break
            # Resolve relative redirects against current URL
            redirect_url = urljoin(current_url, redirect_url)
            rp = urlparse(redirect_url)
            rhost = rp.hostname
            if rhost and not _is_safe_host(rhost):
                print(f"❌ Blocked: redirect to internal/private IP: {rhost}")
                return False
            current_url = redirect_url
            resp = requests.get(redirect_url, timeout=30, headers={
                "User-Agent": "Mozilla/5.0 (OpenClaw KB Manager)"
            }, allow_redirects=False)

        resp.raise_for_status()
    except Exception as e:
        print(f"❌ Failed to fetch URL: {e}")
        return False

    html = resp.text

    # Extract text
    text = extract_text_from_html(html)
    if not text or len(text.strip()) < 50:
        print("❌ Could not extract meaningful text from URL")
        return False

    # Extract metadata
    title = extract_title(html, text)
    summary = extract_summary(text)
    word_count = len(text.split())
    tags = auto_tag(text)

    # Chunk content
    chunks = chunk_text(text)
    chunk_count = len(chunks)

    # Generate slug and save file
    slug = url_to_slug(url)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"{slug}-{date_str}.md"
    filepath = KB_ARTICLES_DIR / filename

    KB_ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    # Write article file with chunk separators
    content_parts = [f"# {title}\n", f"Source: {url}\n", f"Ingested: {date_str}\n"]
    for i, chunk in enumerate(chunks):
        content_parts.append(f"\n---\n## Chunk {i + 1}\n\n{chunk}")

    filepath.write_text("\n".join(content_parts), encoding="utf-8")

    # Update index
    article_id = generate_id()
    article_entry = {
        "id": article_id,
        "url": url,
        "title": title,
        "summary": summary[:300],
        "tags": tags,
        "word_count": word_count,
        "chunk_count": chunk_count,
        "file": f"articles/{filename}",
        "ingested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    index["articles"].append(article_entry)
    save_index(index)

    tags_display = ", ".join(tags) if tags else "none"
    print(f'✅ Ingested: "{title}" | {chunk_count} chunks | {word_count} words | Tags: {tags_display}')
    return True


def cmd_search(query: str):
    """Search KB by keyword match."""
    index = load_index()
    articles = index.get("articles", [])

    if not articles:
        print("📭 KB empty — ingest some URLs first.")
        return

    query_lower = query.lower()
    query_words = set(query_lower.split())

    scored = []
    for article in articles:
        score = 0
        title_lower = article.get("title", "").lower()
        summary_lower = article.get("summary", "").lower()
        tags_lower = [t.lower() for t in article.get("tags", [])]

        for word in query_words:
            if word in title_lower:
                score += 3
            if word in summary_lower:
                score += 2
            if word in tags_lower:
                score += 3

        if score > 0:
            scored.append((score, article))

    if not scored:
        print(f"🔍 No results for '{query}'")
        return

    scored.sort(key=lambda x: -x[0])
    top3 = scored[:3]

    print(f"🔍 Found {len(scored)} results for '{query}' (showing top {len(top3)}):\n")

    for _, article in top3:
        print(f"  📄 {article.get('title', 'Untitled')}")
        print(f"     Source: {article.get('url', 'N/A')}")
        print(f"     Tags: {', '.join(article.get('tags', []))}")

        # Load chunks and find matching excerpts
        article_file = WORKSPACE / "memory" / "kb" / article.get("file", "")
        if article_file.exists():
            try:
                content = article_file.read_text(encoding="utf-8")
                chunks = content.split("---\n## Chunk")
                excerpts = []
                for chunk in chunks:
                    chunk_lower = chunk.lower()
                    for word in query_words:
                        if word in chunk_lower:
                            # Extract relevant excerpt (~100 chars around match)
                            idx = chunk_lower.find(word)
                            start = max(0, idx - 50)
                            end = min(len(chunk), idx + 50 + len(word))
                            excerpt = chunk[start:end].strip().replace('\n', ' ')
                            excerpts.append(f"...{excerpt}...")
                            break
                    if len(excerpts) >= 3:
                        break

                if excerpts:
                    print("     Excerpts:")
                    for ex in excerpts:
                        print(f"       • {ex}")
            except Exception:
                pass

        print()


def cmd_list(tag: str = None):
    """List all articles with optional tag filter."""
    index = load_index()
    articles = index.get("articles", [])

    if tag:
        articles = [a for a in articles if tag.lower() in [t.lower() for t in a.get("tags", [])]]

    if not articles:
        label = f" with tag '{tag}'" if tag else ""
        print(f"📭 KB empty{label}.")
        return

    print(f"📋 KB Articles{' (tag: ' + tag + ')' if tag else ''} ({len(articles)}):\n")
    for article in articles:
        tags_display = ", ".join(article.get("tags", []))
        print(f"  {article.get('id', '?')} | {article.get('title', 'Untitled')}")
        print(f"    Date: {article.get('ingested_at', 'N/A')[:10]} | "
              f"Tags: {tags_display} | "
              f"Chunks: {article.get('chunk_count', 0)} | "
              f"Words: {article.get('word_count', 0)}")
        print()


def cmd_summary():
    """Show KB summary statistics."""
    index = load_index()
    articles = index.get("articles", [])

    total = len(articles)
    total_words = sum(a.get("word_count", 0) for a in articles)

    print(f"📊 KB Summary:")
    print(f"  Total articles: {total}")
    print(f"  Total words: {total_words:,}")
    print(f"  Updated: {index.get('updated_at', 'N/A')}")

    if articles:
        # Top 5 tags
        from collections import Counter
        tag_counts = Counter()
        for a in articles:
            for t in a.get("tags", []):
                tag_counts[t] += 1

        if tag_counts:
            print(f"\n  Top 5 Tags:")
            for tag, count in tag_counts.most_common(5):
                print(f"    {tag}: {count}")

        # Date range
        dates = [a.get("ingested_at", "")[:10] for a in articles if a.get("ingested_at")]
        if dates:
            print(f"\n  Date range: {min(dates)} → {max(dates)}")


def cmd_delete(article_id: str):
    """Delete article from KB."""
    index = load_index()
    articles = index.get("articles", [])

    found = None
    for i, article in enumerate(articles):
        if article.get("id") == article_id:
            found = (i, article)
            break

    if not found:
        print(f"❌ Article not found: {article_id}")
        return False

    idx, article = found

    # Delete file (with path traversal protection)
    kb_root = WORKSPACE / "memory" / "kb"
    article_file = (kb_root / article.get("file", "")).resolve()
    if not article_file.is_relative_to(kb_root.resolve()):
        print(f"❌ Blocked: file path escapes KB root: {article.get('file', '')}")
        return False
    if article_file.exists():
        article_file.unlink()
        print(f"  🗑️ Deleted file: {article_file.name}")

    # Remove from index
    articles.pop(idx)
    index["articles"] = articles
    save_index(index)

    print(f"🗑️ Deleted: {article_id} — '{article.get('title', 'Untitled')}'")
    return True


def main():
    parser = argparse.ArgumentParser(description="RAG Kit KB Manager")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ingest", type=str, help="Ingest URL into KB")
    group.add_argument("--search", type=str, help="Search KB by keyword")
    group.add_argument("--list", action="store_true", help="List all articles")
    group.add_argument("--summary", action="store_true", help="Show KB summary")
    group.add_argument("--delete", type=str, help="Delete article by ID")

    parser.add_argument("--tag", type=str, help="Filter by tag (for --list)")
    parser.add_argument("--force", action="store_true", help="Force re-ingest even if URL exists")

    args = parser.parse_args()

    if args.ingest:
        cmd_ingest(args.ingest, args.force)
    elif args.search:
        cmd_search(args.search)
    elif args.list:
        cmd_list(args.tag)
    elif args.summary:
        cmd_summary()
    elif args.delete:
        cmd_delete(args.delete)


if __name__ == "__main__":
    main()
