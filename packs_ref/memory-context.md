# Memory & Context Pack

## Skills available
- **persistent-memory**: `/save_mem`, `/recall_mems` — lưu/truy xuất quyết định, patterns, configs
- **rag-kit**: `/kb add`, `/kb search`, `/kb list` — knowledge base ingest + search
- **smart-memory**: `/smart-memory`, extract facts từ chat history, dedup by merge_key
- **semantic-memory-search**: search across all memory layers (persistent + smart + KB)
- **lazy-context**: 3-tier context loading (hot → warm → cold)
- **snapshot-ttl**: session snapshot management với TTL per category

## When to use
- User muốn lưu lại quyết định, config, pattern, solution
- User cần tìm lại thông tin đã lưu trước đó
- User muốn ingest URL/article vào knowledge base
- Task liên quan đến memory management, recall, context loading
- User hỏi "nhớ lại...", "lưu lại...", "tìm trong KB..."

## Related tools
- `tools/context_router.py` — routes tasks to this pack when memory/kb keywords detected
- `memory/index.json` — persistent memory storage
- `memory/kb/index.json` — knowledge base index
- `memory/smart-memory.json` — smart memory with TTL
