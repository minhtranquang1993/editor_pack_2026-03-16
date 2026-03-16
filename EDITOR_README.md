# EDITOR_README — editor_pack_2026-03-16

> Workspace: `/root/.openclaw/workspace`
> Tất cả paths dưới đây là relative to workspace root.
> Khi xong, push lên GitHub repo và gửi lại Ní link để deploy.

---

## TASK OVERVIEW

| # | Priority | File target | Mô tả ngắn |
|---|----------|-------------|------------|
| P1 | 🔴 HIGH | `skills/apps-script-deployer-lite/scripts/deploy.py` | Implement `cmd_deploy()` + `cmd_verify()` (hiện là TODO stubs) |
| P2a | 🟡 MED | `skills/rag-kit/scripts/kb_manager.py` *(new file)* | Script ingest URL + search KB cho rag-kit |
| P2b | 🟡 MED | `skills/persistent-memory/scripts/mem_manager.py` *(new file)* | Script `/save_mem` + `/recall_mems` cho persistent-memory |
| P3a | 🟡 MED | `tools/context_router.py` | Fix routing logic + add `memory-context` category |
| P3b | 🟡 MED | `tools/quality_drift_detector.py` | Fix duplicate metrics keys trong `METRIC_NAMES` + `METRIC_UNITS` |
| P4a | 🟢 LOW | `tools/regression_suite.py` | Thêm runtime smoke tests cho 3 core flows |
| P4b | 🟢 LOW | `tools/suggestion_reply_dnd.py` | Thêm `--export-json` mode |

---

## P1 — apps-script-deployer-lite: Implement deploy + verify

**File:** `skills/apps-script-deployer-lite/scripts/deploy.py`
**Current file:** `P1_apps_script_deployer/deploy.py`

### Vấn đề
`cmd_deploy()` (line 179) và `cmd_verify()` (line 188) đều là TODO stubs — skill announce deploy được nhưng thực tế không làm gì.

### Credentials available
- OAuth credentials: `credentials/google_workspace_credentials.json`
  - Type: installed app (OAuth 2.0)
  - Client ID: `870669444583-cj9l4it...`
- Token: `credentials/google_workspace_token.json`
  - Keys: `access_token`, `refresh_token`, `scope`, `token_type`, `expires_in`, `updated_at`
  - **Scopes hiện tại:** drive, documents, spreadsheets, gmail.send
  - ⚠️ Apps Script API scopes (`script.projects`, `script.deployments`) CÓ THỂ chưa có trong token này

### Yêu cầu implement

**`cmd_deploy(project_dir)`:**
```python
# 1. Đọc files từ project_dir (*.gs + appsscript.json)
# 2. Load token từ credentials/google_workspace_token.json
# 3. Gọi Apps Script API: POST https://script.googleapis.com/v1/projects
#    Body: {"title": project_name}
# 4. Upload files: PUT https://script.googleapis.com/v1/projects/{scriptId}/content
#    Body: {"files": [{"name": ..., "type": "SERVER_JS"|"JSON", "source": ...}]}
# 5. Print: ✅ Deployed: script_id = {scriptId}
# 6. Nếu scope chưa có → in warning hướng dẫn re-auth với scope script.projects
```

**`cmd_verify(script_id)`:**
```python
# 1. Load token
# 2. GET https://script.googleapis.com/v1/projects/{scriptId}
# 3. Print: title, scriptId, createTime, updateTime
# 4. GET https://script.googleapis.com/v1/projects/{scriptId}/deployments (nếu có)
# 5. In danh sách deployments nếu có
```

**Token refresh pattern** (reference từ existing tools):
```python
import google.auth.transport.requests
from google.oauth2.credentials import Credentials

def load_google_credentials(token_file, creds_file):
    with open(token_file) as f:
        token_data = json.load(f)
    with open(creds_file) as f:
        creds_data = json.load(f)
    
    creds = Credentials(
        token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_data["installed"]["client_id"],
        client_secret=creds_data["installed"]["client_secret"],
        scopes=token_data["scope"].split()
    )
    if creds.expired:
        creds.refresh(google.auth.transport.requests.Request())
        # Save updated token
        token_data["access_token"] = creds.token
        token_data["updated_at"] = datetime.utcnow().isoformat()
        with open(token_file, "w") as f:
            json.dump(token_data, f, indent=2)
    return creds
```

### Acceptance criteria
- [ ] `python3 skills/apps-script-deployer-lite/scripts/deploy.py scaffold --template daily-report --name "Test"` → tạo được folder
- [ ] `python3 skills/apps-script-deployer-lite/scripts/deploy.py deploy --project-dir ./output/test` → gọi API (hoặc in warning rõ ràng nếu scope thiếu)
- [ ] `python3 skills/apps-script-deployer-lite/scripts/deploy.py verify --script-id dummy123` → gọi API verify (hoặc 401 error cụ thể, không phải "chưa implement")
- [ ] Không crash khi token expired → tự refresh
- [ ] Syntax error-free: `python3 -m py_compile skills/apps-script-deployer-lite/scripts/deploy.py`

---

## P2a — rag-kit: Implement kb_manager.py

**New file:** `skills/rag-kit/scripts/kb_manager.py`
**Reference spec:** `P2_rag_kit/SKILL.md` + `P2_rag_kit/kb-details.md`
**Reference script style:** `P2_rag_kit/ref_extract_facts.py` (smart-memory, same workspace pattern)
**Current KB index:** `P2_rag_kit/kb_index_current.json` (empty, schema: `{version, articles[], total, updated_at}`)

### Storage paths
```
WORKSPACE = Path("/root/.openclaw/workspace")
KB_INDEX  = WORKSPACE / "memory" / "kb" / "index.json"
KB_ARTICLES_DIR = WORKSPACE / "memory" / "kb" / "articles"
KB_ATTACH_DIR   = WORKSPACE / "memory" / "kb" / "attachments"
```

### Yêu cầu implement

**CLI:**
```bash
python3 skills/rag-kit/scripts/kb_manager.py --ingest <url>
python3 skills/rag-kit/scripts/kb_manager.py --search "<query>"
python3 skills/rag-kit/scripts/kb_manager.py --list [--tag <tag>]
python3 skills/rag-kit/scripts/kb_manager.py --summary
python3 skills/rag-kit/scripts/kb_manager.py --delete <id>
```

**`--ingest <url>`:**
1. `web_fetch` URL → extract text (dùng `requests` + `html2text` hoặc nếu không có thì `BeautifulSoup`)
   - Fallback: nếu không fetch được → print error, exit 1
2. Extract metadata: `title` (h1 hoặc `<title>`), `summary` (first 2 sentences), `tags` (auto từ content), `word_count`
3. Chunk content: split ~500 words mỗi chunk, giữ markdown headers làm boundary
4. Save file: `memory/kb/articles/{slug}-{YYYY-MM-DD}.md`
   - Slug: URL → lowercase, strip protocol, replace non-alphanumeric → `-`, max 50 chars
5. Update `memory/kb/index.json`: append entry vào `articles[]`, increment `total`, set `updated_at`
6. Print confirmation: `✅ Ingested: "{title}" | {N} chunks | {word_count} words | Tags: {tags}`

**`--search "<query>"`:**
1. Load `index.json`
2. Score mỗi article: keyword match trong `title` + `summary` + `tags` (simple tf/count scoring)
3. Load chunks từ top 3 file `.md`
4. Filter chunks có chứa query keyword
5. Print: title, source URL, relevant excerpts (max 3 excerpts per article)

**`--list [--tag <tag>]`:**
- In danh sách articles: `id | title | date | tags | chunks`
- Filter theo tag nếu có

**`--summary`:**
- Total articles, total words, top 5 tags, oldest/newest article date

**`--delete <id>`:**
- Remove entry từ index.json + xóa file .md tương ứng

### Auto-tag rules (implement trong ingest):
```python
TAG_RULES = {
    ("seo", "keyword", "ranking", "serp"): ["seo", "marketing"],
    ("n8n", "automation", "workflow", "make"): ["automation", "n8n"],
    ("vận chuyển", "logistics", "chuyển nhà"): ["thanh-hung", "logistics"],
    ("ai", "agent", "llm", "gpt", "claude"): ["ai", "tools"],
    ("facebook", "google ads", "tiktok ads"): ["ads", "marketing"],
    ("python", "code", "script", "api"): ["code", "automation"],
}
```

### Duplicate check:
- Trước khi ingest, check URL đã có trong `index.json` chưa
- Nếu có → print `⚠️ Already in KB (id: {id}, ingested: {date}). Use --force to re-ingest.`

### Acceptance criteria
- [ ] `--ingest https://example.com` → tạo file trong `memory/kb/articles/`, update index
- [ ] `--search "seo"` → trả về kết quả có relevance (hoặc "No results" nếu KB empty)
- [ ] `--list` → in danh sách (hoặc "KB empty")
- [ ] `--summary` → in tổng quan
- [ ] Syntax error-free + no import errors cho std lib

---

## P2b — persistent-memory: Implement mem_manager.py

**New file:** `skills/persistent-memory/scripts/mem_manager.py`
**Reference spec:** `P2_persistent_memory/SKILL.md`
**Current index:** `P2_persistent_memory/index_current.json` (có 10 entries, schema rõ ràng)

### Storage
```
MEM_INDEX = WORKSPACE / "memory" / "index.json"
```

### Yêu cầu implement

**CLI:**
```bash
python3 skills/persistent-memory/scripts/mem_manager.py --save --shelf decisions --content "..." --tags "tag1,tag2"
python3 skills/persistent-memory/scripts/mem_manager.py --recall "<query>" [--shelf decisions]
python3 skills/persistent-memory/scripts/mem_manager.py --list [--shelf <shelf>]
python3 skills/persistent-memory/scripts/mem_manager.py --delete <id>
python3 skills/persistent-memory/scripts/mem_manager.py --stats
```

**`--save`:**
1. Generate `id = "mem_{unix_ms}_{random4}"`
2. Auto-tag nếu không có tags: match content với TAG_RULES
3. Dedup check: nếu có mem trong cùng shelf + content similar >80% → warn + skip (hoặc `--force` override)
4. Append vào `index.json["mems"]`, increment `shelves[shelf]`, update `updated_at`
5. Print: `💾 Saved to [{shelf}] — {content[:60]}... Tags: {tags}. Total: {count} mems.`

**`--recall "<query>"`:**
1. Load index.json
2. Score: keyword match trong `content` (case-insensitive) + exact match trong `tags`
3. Filter by `--shelf` nếu có
4. Sort newest first, return top 5
5. Print format đúng theo SKILL.md spec

**`--list [--shelf]`:**
- In tất cả mems hoặc filter theo shelf
- Format: `[{shelf}] {id} ({session_date})\n  {content}\n  Tags: {tags}`

**`--stats`:**
- In tổng quan: total mems, breakdown by shelf, 3 mems mới nhất

**`--delete <id>`:**
- Remove entry, decrement `shelves[shelf]`, update `updated_at`

### Shelves valid:
```python
VALID_SHELVES = ["decisions", "patterns", "errors", "solutions", "context", "config"]
```

### Auto-tag rules:
```python
TAG_RULES = [
    (["api", "token", "key"],           ["api-key", "config"]),
    (["error", "lỗi", "fix"],           ["error"]),
    (["model", "provider"],             ["model", "openclaw"]),
    (["seo", "keyword"],                ["seo", "content"]),
    (["deploy", "server"],              ["devops"]),
    (["python", "code", "script"],      ["code"]),
]
```

### Acceptance criteria
- [ ] `--save --shelf decisions --content "Test decision" --tags "test"` → thêm vào index.json, `shelves.decisions` tăng lên
- [ ] `--recall "test"` → trả về mem vừa save
- [ ] `--stats` → in tổng quan đúng count
- [ ] `--delete <id>` → xóa khỏi index, shelves count giảm
- [ ] Syntax error-free
- [ ] Không break existing `index.json` (đừng overwrite toàn bộ file nếu save lỗi giữa chừng — dùng atomic write)

---

## P3a — context_router.py: Fix routing + add memory-context

**File:** `tools/context_router.py`
**Current file:** `P3_context_router/context_router.py`

### Vấn đề hiện tại
1. Không có category `memory-context` → khi task liên quan đến KB/memory, không route đúng
2. `--task "test"` chỉ trả về `AGENTS-CORE.md` vì không match bất kỳ keyword nào → OK, nhưng test với task thực tế phải match đúng

### Thay đổi cần làm

**Thêm entry mới vào `KEYWORD_MAP`:**
```python
{
    "keywords": ["memory", "kb", "knowledge base", "recall", "save mem", "persistent", "rag", "ingest", "index"],
    "pack": "packs/memory-context.md",
    "type_aliases": ["memory", "kb"]
},
```

**Update `--type` choices trong argparse:**
```python
choices=["marketing", "seo", "content", "automation",
         "security", "heartbeat", "ops", "memory", "kb"],
```

**Fix: thêm `packs/memory-context.md` vào workspace** (tạo file mới):
```markdown
# Memory & Context Pack
## Skills available
- persistent-memory: /save_mem, /recall_mems
- rag-kit: /kb add, /kb search, /kb list
- smart-memory: /smart-memory, extract facts
- semantic-memory-search: search across all memory
- lazy-context: 3-tier context loading
- snapshot-ttl: session snapshot management
```

### Acceptance criteria
- [ ] `python3 tools/context_router.py --task "lưu memory về quyết định này" --json` → recommend bao gồm `packs/memory-context.md`
- [ ] `python3 tools/context_router.py --type memory --json` → recommend `packs/memory-context.md`
- [ ] `python3 tools/context_router.py --task "check ads anomaly" --json` → vẫn recommend `packs/marketing.md` (không break cũ)
- [ ] Syntax error-free

---

## P3b — quality_drift_detector.py: Fix duplicate metrics

**File:** `tools/quality_drift_detector.py`
**Current file:** `P3_quality_drift_detector/quality_drift_detector.py`

### Vấn đề
`METRIC_NAMES` list có duplicate entries:
- `"tool_call_count"` (line ~21) VÀ `"tool_calls_count"` (line ~25) → đây là 2 tên khác nhau nhưng cùng đo 1 thứ
- `METRIC_UNITS` cũng có cả 2 keys
- `DRIFT_DESCRIPTIONS` cũng có cả 2 keys
- Khi `--log-session`, cả 2 đều bị set → inflate data, report bị misleading

### Fix cần làm

1. **Xóa `"tool_calls_count"` khỏi `METRIC_NAMES`** — giữ lại `"tool_call_count"` (canonical name)
2. **Xóa `"tool_calls_count"` khỏi `METRIC_UNITS`**
3. **Xóa `"tool_calls_count"` khỏi `DRIFT_DESCRIPTIONS`**
4. **Trong `log_session()`:** Update mapping:
   ```python
   # Trước:
   "tool_calls_count": args.tool_calls if args.tool_calls is not None else 1,
   # Sau: merge vào tool_call_count
   "tool_call_count": args.tool_call_count if args.tool_call_count is not None 
                      else (args.tool_calls if args.tool_calls is not None else 0),
   ```
5. **Giữ `--tool-calls` arg** trong argparse (backward compat) nhưng map nó vào `tool_call_count`
6. **Final `METRIC_NAMES`** sau fix (7 metrics, không còn duplicate):
   ```python
   METRIC_NAMES = [
       "output_length",
       "revision_rounds",
       "tool_call_count",
       "fail_rate",
       "contradiction_flags",
       "task_completed",
       "session_duration_min",
   ]
   ```

### Acceptance criteria
- [ ] `METRIC_NAMES` không có duplicate entries
- [ ] `python3 tools/quality_drift_detector.py --log-session --tool-call-count 5` → log 1 entry không có `tool_calls_count` key
- [ ] `python3 tools/quality_drift_detector.py --log-session --tool-calls 5` → vẫn hoạt động (backward compat), map vào `tool_call_count`
- [ ] `python3 tools/quality_drift_detector.py --report` → không crash
- [ ] Syntax error-free

---

## P4a — regression_suite.py: Add runtime smoke tests

**File:** `tools/regression_suite.py`
**Current file:** `P4_regression_suite/regression_suite.py`

### Vấn đề
Hiện chỉ check syntax (`py_compile`). Không verify actual runtime behavior của core flows.

### Thêm 3 runtime checks (append vào suite, không break existing):

**Test 1: context_router runtime**
```python
# Verify context_router route() function works correctly
from tools.context_router import route
result = route(task_text="check facebook ads anomaly")
assert "packs/marketing.md" in result, "context_router: marketing pack not recommended for ads task"
assert "AGENTS-CORE.md" in result, "context_router: AGENTS-CORE.md always required"
```

**Test 2: quality_drift_detector: no duplicate metrics**
```python
# Verify no duplicate entries in METRIC_NAMES
from tools.quality_drift_detector import METRIC_NAMES
assert len(METRIC_NAMES) == len(set(METRIC_NAMES)), f"Duplicate metrics found: {METRIC_NAMES}"
```

**Test 3: persistent-memory mem_manager import**
```python
# Verify mem_manager can be imported (syntax + basic import)
import importlib.util
spec = importlib.util.spec_from_file_location(
    "mem_manager",
    "skills/persistent-memory/scripts/mem_manager.py"
)
mod = importlib.util.module_from_spec(spec)
# Just check it parses — don't exec (side effects)
import ast, pathlib
src = pathlib.Path("skills/persistent-memory/scripts/mem_manager.py").read_text()
ast.parse(src)  # syntax ok
```

### Pattern để add test (xem regression_suite.py hiện tại để biết `_check_import`, `_check_cmd` pattern):
- Dùng `_check_import_runtime` hoặc tạo `_check_fn(fn, *args)` pattern mới nếu cần
- Add vào `TESTS` list với key `("tool_name", "test_description")`

### Acceptance criteria
- [ ] 3 tests mới xuất hiện trong output `python3 tools/regression_suite.py`
- [ ] Không break existing 10+ tests
- [ ] Syntax error-free

---

## P4b — suggestion_reply_dnd.py: Add --export-json mode

**File:** `tools/suggestion_reply_dnd.py`
**Current file:** `P4_suggestion_reply_export/suggestion_reply_dnd.py`

### Yêu cầu
Thêm `--export-json [--output path]` mode (mirror của `--export-csv` đã có):

```python
def cmd_export_json(output_path: str, limit: int = 0):
    """Export conversations to JSON file."""
    db = get_db()
    cur = db.execute("""
        SELECT c.conversation_id, c.participant_name, c.last_message_time,
               m.sender_id, m.message_text, m.created_time, m.is_admin_reply
        FROM conversations c
        LEFT JOIN messages m ON c.conversation_id = m.conversation_id
        ORDER BY c.last_message_time DESC, m.created_time ASC
    """)
    rows = cur.fetchall()
    
    # Group by conversation
    convs = {}
    for row in rows:
        cid = row[0]
        if cid not in convs:
            convs[cid] = {
                "conversation_id": cid,
                "participant_name": row[1],
                "last_message_time": row[2],
                "messages": []
            }
        if row[3]:  # has message
            convs[cid]["messages"].append({
                "sender_id": row[3],
                "text": row[4],
                "created_time": row[5],
                "is_admin_reply": bool(row[6])
            })
    
    data = list(convs.values())
    if limit > 0:
        data = data[:limit]
    
    output = output_path or CSV_DEFAULT_OUTPUT.replace(".csv", ".json")
    os.makedirs(os.path.dirname(output), exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"✅ Exported {len(data)} conversations to {output}")
    return True
```

**Thêm vào argparse:**
```python
parser.add_argument("--export-json", action="store_true", help="Export to JSON file")
```

**Thêm vào main():**
```python
elif args.export_json:
    cmd_export_json(args.output, getattr(args, 'limit', 0))
```

### Acceptance criteria
- [ ] `python3 tools/suggestion_reply_dnd.py --export-json` → tạo file `.json` (hoặc error nếu DB chưa init)
- [ ] `python3 tools/suggestion_reply_dnd.py --export-json --output /tmp/test.json` → tạo đúng path
- [ ] Syntax error-free

---

## Deploy Instructions (sau khi edit xong)

```
1. Push tất cả files đã edit lên GitHub repo (tạo repo mới hoặc dùng repo cũ)
2. Gửi Ní link repo
3. Ní sẽ clone + verify + deploy vào workspace
```

## File Map (editor cần sửa/tạo)

| File | Action |
|------|--------|
| `skills/apps-script-deployer-lite/scripts/deploy.py` | EDIT — implement 2 functions |
| `skills/rag-kit/scripts/kb_manager.py` | CREATE NEW |
| `skills/persistent-memory/scripts/mem_manager.py` | CREATE NEW |
| `tools/context_router.py` | EDIT — add memory-context category |
| `packs/memory-context.md` | CREATE NEW |
| `tools/quality_drift_detector.py` | EDIT — fix duplicate metrics |
| `tools/regression_suite.py` | EDIT — add 3 runtime tests |
| `tools/suggestion_reply_dnd.py` | EDIT — add --export-json |
