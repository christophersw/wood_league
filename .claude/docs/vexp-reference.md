# vexp Advanced Parameters Reference

## run_pipeline Parameters

| Parameter | Values | Use case |
|-----------|--------|----------|
| `preset` | `"debug"` | Force debug mode: capsule + tests + impact + memory |
| `preset` | `"refactor"` | Deep impact analysis (depth 5) |
| `max_tokens` | e.g. `12000` | Increase total budget for complex tasks |
| `include_tests` | `true` | Include test files in results |
| `include_file_content` | `false` | Omit full file content (lighter response) |

## Multi-Repo Workspaces

`run_pipeline` auto-queries all indexed repos. Use `repos: ["alias"]` to scope.
Use `index_status` to discover available repo aliases.

## Other MCP Tools

- `get_skeleton({ files: [...], detail: "minimal"|"standard"|"detailed" })` — 70-90% token savings over Read
- `index_status` — indexing status and health check
- `expand_vexp_ref` — expand V-REF hash placeholders in v2 compact output
- `search_logic_flow` — trace logic paths
- `search_memory` — query session observations
- `save_observation` — persist an insight for future sessions
