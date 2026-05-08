# vexp — Code Intelligence for AI Agents

vexp maintains a semantic graph index of wood_league. Always use vexp MCP tools
instead of grep/find for code exploration — they are faster and token-efficient.

## Tool Reference

### `get_context_capsule` — **start here for every task**
Returns the most relevant code ranked by hybrid search (keyword + semantic + graph centrality).
Auto-detects query intent: "fix bug" → debug mode, "refactor" → blast-radius, "add feature" → modify.
```
get_context_capsule(query="<describe what you need>")
```
Advanced: `include_tests: true`, `max_tokens: 12000`, `pivot_depth: 3`, `skeleton_detail: "detailed"`, `repos: ["alias"]`

### `get_skeleton` — file structure without full content
Returns function/class signatures only (70-90% token reduction).
```
get_skeleton(files=["src/foo.py", "src/bar.py"])
```

### `get_impact_graph` — blast radius of a change
Shows all code that would break if a symbol changes (callers, importers, dependents).
FQN format from capsule results: `src/module.py::ClassName::method_name`
```
get_impact_graph(symbol_fqn="<fqn from capsule>", depth=3)
```

### `search_logic_flow` — trace execution paths
Finds how data/control flows from symbol A to symbol B through the call graph.
```
search_logic_flow(start="<fqn>", end="<fqn>")
```

### `index_status` — check index health
Use to verify vexp is running and the index is up to date before making queries.

### `workspace_setup` — bootstrap config
Generates config files for AI agents and multi-repo workspaces.

### `submit_lsp_edges` — submit type-resolved call edges
Submit high-confidence call graph edges from Language Server resolution (used by VS Code extension).
```
submit_lsp_edges(edges=[{"source_fqn": "...", "target_fqn": "...", "edge_type": "CALLS"}])
```

### `get_session_context` — recall what you worked on
Returns observations from the current session and optionally previous sessions.
Observations are auto-captured from every vexp tool call. Linked to code symbols for staleness tracking.
```
get_session_context(include_previous=true, max_results=20)
```

### `search_memory` — find past decisions and insights
Cross-session search with hybrid scoring (keyword + semantic + recency + code-graph proximity).
Each result explains WHY it surfaced. Stale observations (linked to changed code) are demoted.
```
search_memory(query="<what you're looking for>", max_results=10)
```

### `save_observation` — persist important insights
Manually save architectural decisions, patterns, or important context that should persist across sessions.
Link to code symbols for automatic staleness tracking when that code changes.
```
save_observation(content="<concise insight>", type="decision", linked_symbols=["src/mod.rs::FnName"])
```

## Smart Features (automatic — no action needed)
- **Intent Detection**: "fix bug" → debug mode (follows error paths), "refactor" → blast-radius mode, "add" → modify, default → read
- **Hybrid Search**: combines keyword matching (FTS) + semantic similarity (TF-IDF) + graph centrality
- **Session Memory**: every tool call is auto-captured as an observation. Relevant memories from previous sessions are auto-surfaced in `get_context_capsule` results. Observations linked to code symbols are auto-flagged stale when that code changes.
- **Feedback Loop**: repeated queries with similar terms auto-expand result budget
- **LSP Bridge**: VS Code captures type-resolved call edges for high-confidence call graphs
- **Change Coupling**: files modified together in git history are included as related context
- **Context Lineage**: frequently modified code gets a boost in relevance ranking

## Recommended Workflow

1. `get_context_capsule(query="<task description>")` — orient yourself (includes relevant memories)
2. If you need more detail on a specific file: `get_skeleton(files=[...])`
3. Before modifying a function: `get_impact_graph(symbol_fqn="...")`
4. If tracing a call chain: `search_logic_flow(start="...", end="...")`
5. Save important decisions: `save_observation(content="...", linked_symbols=[...])`
6. Recall past work: `search_memory(query="...")` or `get_session_context()`
7. Then read/edit specific files as needed
