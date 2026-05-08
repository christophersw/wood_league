# Agent Instructions — Wood League Chess

Be brief.

## Security: scan edited Python files

After editing any `.py` file, run `bandit` on that file and fix any Medium or High
severity issues before considering the task complete:

```bash
bandit -ll <edited_file.py>
```

`-ll` reports Medium and High only (skips LOW). If `bandit` is not installed:

```bash
pip3 install bandit
```

Do not commit or hand back with unresolved Medium/High bandit findings.

The full Snyk scan (deps + code + containers across all repos) is handled by the
pre-commit hook and can also be run manually:

```bash
./security-scan.sh
```
