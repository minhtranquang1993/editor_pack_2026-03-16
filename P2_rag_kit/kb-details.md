# RAG Kit — KB Details & Commands

## index.json Schema

```json
{
  "version": "1.0.0",
  "articles": [
    {
      "id": "kb_1771613400000_a1b2",
      "title": "How to structure AI memory",
      "url": "https://example.com/article",
      "type": "article",
      "tags": ["memory", "ai", "architecture"],
      "summary": "1-2 câu tóm tắt nội dung",
      "chunk_count": 5,
      "file": "kb/articles/ai-memory-20260220.md",
      "ingested_at": "2026-02-20",
      "word_count": 1200
    }
  ],
  "total": 0,
  "updated_at": ""
}
```

---

## 📋 KB COMMANDS

| Command | Chức năng |
|---------|-----------|
| `/kb add [url]` | Ingest URL vào KB |
| `/kb search [query]` | Search trong KB |
| `/kb list` | Liệt kê tất cả articles |
| `/kb list [tag]` | Filter theo tag |
| `/kb summary` | Tổng quan KB (N articles, top tags) |

---

## Auto-ingest chủ động

Em tự động đề xuất ingest khi:
- Anh share URL trong lúc research task
- Anh đọc article liên quan đến project đang làm

```
💡 Anh có muốn em lưu bài này vào KB không?
   "{title}" — liên quan đến "{current_task}"
   [/kb add {url}]
```

---

## Relevance với anh Minh

**Topics hay ingest:**
- SEO techniques, Google algorithm updates
- Digital marketing case studies
- Automation tools (N8N, Make, Python)
- AI/ML tools và workflows
- Vận chuyển/logistics research (cho Thành Hưng)

**Auto-tag rules:**
```
SEO + keyword + ranking → tags: ["seo", "marketing"]
N8N + automation + workflow → tags: ["automation", "n8n"]
vận chuyển + logistics → tags: ["thanh-hung", "logistics"]
AI + agent + LLM → tags: ["ai", "tools"]
```

---

## Storage Limits

- Max 500 articles trong index
- Max 5MB per article file
- Khi > 500 → propose archive articles cũ hơn 90 ngày không được search
