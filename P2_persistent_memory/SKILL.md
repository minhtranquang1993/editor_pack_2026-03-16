---
name: persistent-memory
description: >-
  Persistent memory với search. Lưu decisions/patterns/errors/solutions có tag
  để search nhanh qua /save_mem và /recall_mems. Khác MEMORY.md (prose)
  — đây là structured, searchable memory index.
---

# 📋 SKILL: Persistent Memory with Search
# Location: /root/.openclaw/workspace/skills/persistent-memory/

## Mô tả

Structured memory layer — lưu memories có shelf + tags → search nhanh.
Khác với `MEMORY.md` (viết tay, prose) — đây là index tự động, machine-readable.

**File:** `memory/index.json`

---

## Schema

```json
{
  "version": "1.0.0",
  "mems": [
    {
      "id": "mem_1708444800000_a3f2",
      "shelf": "decisions",
      "content": "Dùng gpt-5.3-codex lowercase vì minai93 case-sensitive",
      "tags": ["openclaw", "config", "model-id"],
      "session_date": "2026-02-20",
      "created_at": 1708444800000
    }
  ],
  "shelves": {
    "decisions": 0,
    "patterns": 0,
    "errors": 0,
    "solutions": 0,
    "context": 0,
    "config": 0
  },
  "updated_at": "2026-02-20T19:00:00Z"
}
```

---

## Shelves (Categories)

| Shelf | Dùng khi nào |
|-------|-------------|
| `decisions` | Quyết định kỹ thuật, config, design choices |
| `patterns` | Workflow patterns anh thích, best practices |
| `errors` | Lỗi đã gặp + cách fix → tránh lặp lại |
| `solutions` | Giải pháp hay cho vấn đề phổ biến |
| `context` | Project context, background info |
| `config` | API keys, settings, endpoints |

---

## `/save_mem` — Lưu memory

### Trigger khi:
- Decision được đưa ra (tự động via decision-extractor)
- Lỗi được fix → save vào `errors` shelf
- Anh nói "nhớ cái này", "lưu lại", "ghi nhớ"
- Config/API key mới được thêm

### Format:
```
Em tự generate:
  id: "mem_{timestamp}_{random4}"
  shelf: [phân loại tự động hoặc theo anh chỉ định]
  content: [tóm tắt 1-2 câu, súc tích]
  tags: [2-5 tags liên quan, lowercase, dùng dấu gạch ngang]
  session_date: YYYY-MM-DD
  created_at: unix timestamp
```

### Auto-tagging rules:
```
Từ khóa trong content → tag tự động:
"api key", "token"     → tag: "api-key", "config"
"error", "lỗi", "fix"  → tag: "error", shelf: "errors"
"model", "provider"    → tag: "model", "openclaw"
"SEO", "keyword"       → tag: "seo", "content"
"deploy", "server"     → tag: "devops"
"python", "code"       → tag: "code"
```

### Confirmation (1 dòng):
```
💾 Saved to [decisions] — {content preview}. Tags: {tags}. Total: {count} mems.
```

---

## `/recall_mems` — Search memory

### Trigger khi:
- Anh hỏi "hồi trước mình làm gì", "lần trước fix thế nào"
- Anh gặp lỗi quen → tự động check `errors` shelf
- Anh hỏi về config/API key cũ
- `/recall_mems [keyword]` hoặc `/recall_mems [keyword] shelf:[shelf]`

### Search logic:
```
1. Tìm trong content (case-insensitive, partial match)
2. Tìm trong tags (exact match)
3. Filter theo shelf nếu có
4. Sort: newest first
5. Return top 5 kết quả
```

### Output format:
```
=== 🧠 RECALL: {N} kết quả cho "{query}" ===

[decisions] mem_xxx (2026-02-20)
  Dùng gpt-5.3-codex lowercase vì minai93 case-sensitive
  Tags: openclaw, config, model-id

[errors] mem_yyy (2026-02-19)
  CORS error khi call API → thêm headers Access-Control-Allow-Origin
  Tags: api, cors, error

=== END RECALL ===
```

### List mode (không có query):
```
/recall_mems → Hiển thị tổng quan:

=== 🧠 MEMS BRAIN ===
Total: 12 memories

Shelves:
  decisions: 4
  errors: 3
  patterns: 2
  solutions: 2
  config: 1

Recent (3 mới nhất): ...
=== END ===
```

---

## Integration

### Với decision-extractor:
Khi decision được detect → tự động `/save_mem` vào `decisions` shelf.

### Với error-translator:
Khi lỗi được fix → propose save vào `errors` shelf.
```
💡 Lưu fix này vào memory để sau khỏi mất không anh?
→ /save_mem errors "CORS error fix: add Access-Control headers" cors,api,fix
```

### Với /recap:
`/recall_mems` là smart search layer của `/recap [topic]`.
```
/recap auth → tìm trong index.json với query="auth"
```

---

## Duplicate Prevention

Trước khi save → check:
```
Nếu tồn tại mem có cùng shelf + content giống > 80%:
→ "Memory này đã có rồi nha anh! [shelf] {date}: {content}"
→ Không save duplicate
```

---

## File Operations

Read: `read memory/index.json`
Write: `edit memory/index.json` (append vào `mems` array)
Cleanup: Khi `mems.length > 200` → propose archive entries cũ hơn 90 ngày

## Category
memory-context
