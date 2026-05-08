# Wood League

Chess club analytics platform. See `docs/architecture.md` for system overview.

## Services

| Service | Description | Deployment |
|---------|-------------|------------|
| `services/app` | Django web application | Railway |
| `services/dispatchers` | RunPod job dispatcher | Railway |
| `services/stockfish_worker` | Stockfish analysis worker | RunPod |
| `services/lc0_worker` | Lc0 neural net analysis worker | RunPod |

## Local Development

Install uv if needed:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Install all workspace members:
```bash
uv sync
```
