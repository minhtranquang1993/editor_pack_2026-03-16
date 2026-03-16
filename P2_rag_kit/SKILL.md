---
name: rag-kit
description: >-
  Personal Knowledge Base với RAG. Auto-ingest URL/article/PDF khi anh drop
  link. Search semantic trên toàn bộ KB. Dùng khi anh muốn lưu bài đọc,
  research articles, hoặc hỏi "tìm trong KB về X".
---

# 📋 SKILL: Personal Knowledge Base (RAG)
# Location: /root/.openclaw/workspace/skills/rag-kit/

## Mô tả

Searchable knowledge base — anh drop URL/file → em tự ingest → lưu vào KB.
Sau đó anh hỏi bất cứ thứ gì → em search KB trả lời có nguồn.

**Storage:** `memory/kb/` folder (markdown chunks + index)

---

## KB Storage Structure

```
memory/
└── kb/
    ├── index.json          # KB index: metadata + search index
    ├── articles/           # Ingested articles (chunked markdown)
    │   ├── {slug}-{date}.md
    │   └── ...
    └── attachments/        # PDFs, files (extracted text)
        └── {filename}-{date}.md
```

---

## 🔽 AUTO-INGEST — khi anh drop URL

### Trigger:
- Anh gửi URL kèm "lưu", "save", "đọc sau", "ingest", "add to kb"
- Anh gửi URL trong conversation và em nhận ra đây là article đáng lưu
- Anh gửi: "thêm cái này vào KB: [URL]"

### Ingest Flow:

**Bước 1: Fetch content**
```
web_fetch(url) → extract markdown text
Detect type: article | tweet | youtube | pdf | doc
```

**Bước 2: Extract metadata**
```
title: từ <title> tag hoặc h1
summary: tóm tắt 2-3 câu
tags: auto-generate từ content (3-5 tags)
word_count: đếm words
```

**Bước 3: Chunk content**
```
Split thành chunks ~500 words mỗi chunk
Giữ nguyên markdown headers như chunk boundaries
Prefix mỗi chunk: "# Source: {title} | Part {N}/{total}"
```

**Bước 4: Save**
```
slug = url → kebab-case (max 50 chars)
file = memory/kb/articles/{slug}-{YYYY-MM-DD}.md
Append metadata vào memory/kb/index.json
```

**Bước 5: Confirm**
```
✅ Đã lưu vào KB: "{title}"
   URL: {url}
   Tags: {tags}
   Chunks: {N} | Words: {word_count}
   → Hỏi em về bài này bất cứ lúc nào nha anh!
```

---


## References

Xem `references/kb-details.md` cho: index.json schema, KB commands, auto-ingest rules, storage limits.

## 🔍 KB SEARCH — khi anh hỏi

### Trigger:
- Anh hỏi "trong KB có gì về X"
- Anh hỏi câu hỏi mà em biết có thể liên quan đến KB đã lưu
- `/kb search [query]`
- `/kb list` — xem danh sách articles

### Search Flow:

**Bước 1: Search index.json**
```
title + summary + tags → keyword match
Return: relevant articles (title, summary, file path)
```

**Bước 2: Load relevant chunks**
```
Đọc file article → chỉ load chunks relevant đến query
(dùng keyword matching trên chunk headers)
```

**Bước 3: Synthesize answer**
```
Trả lời dựa trên chunks tìm được
Cite nguồn: "Theo [{title}]({url}):"
```

### Output format:
```
📚 Tìm thấy {N} nguồn trong KB về "{query}":

**[{title}]** ({date})
> "{relevant excerpt}"
Source: {url}

---
💡 Tổng hợp: [Em tổng hợp trả lời từ các nguồn]
```

### Không có kết quả:
```
📚 KB chưa có gì về "{query}".
💡 Muốn em search web tìm bài rồi ingest vào KB không?
```

---

## Mesh Connections
- **→ search-kit**: KB không có → search web → ingest kết quả vào KB
- **→ seo-article**: Viết bài có thể reference KB cho E-E-A-T
- **→ reader-adapter**: Crawl deep content rồi ingest vào KB

## Category
memory-context
