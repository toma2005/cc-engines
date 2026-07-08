# Cross-platform notes

The agent instructions in this package are written as **POSIX shell** (bash/zsh). Where they run:

- **macOS / Linux** — as-is.
- **Windows + WSL2** (recommended) or **Git Bash** — as-is (these are POSIX shells). Simplest path on Windows.
- **Windows native (PowerShell / cmd)** — translate the commands using the table below. The `npx` installer and the `ui-vision-loop` Python script handle the OS themselves; only the shell snippets in the agents need translating.

## POSIX → PowerShell translation

| POSIX (bash/zsh) | PowerShell |
| --- | --- |
| `"$HOME"` | `$env:USERPROFILE` |
| `~/.grok/grok-worker.env` | `$env:USERPROFILE\.grok\grok-worker.env` |
| `/tmp/x.log` | `$env:TEMP\x.log` |
| `cmd > log 2>&1` | `cmd *> log` |
| `... < /dev/null` | `... < $null` (or drop it) |
| `. "$HOME/.grok/grok-worker.env"` (source) | see "Grok env on Windows" below |
| `ls -d P/* \| sort -V \| tail -1` | `Get-ChildItem P \| Sort-Object Name \| Select-Object -Last 1 -ExpandProperty FullName` |
| `command -v grok` | `Get-Command grok -ErrorAction SilentlyContinue` |
| `grep -n foo file` | `Select-String foo file` |
| `cp a b` | `Copy-Item a b` |
| `chmod 600 f` | usually skip on NTFS; or restrict ACL with `icacls f /inheritance:r /grant:r "$env:USERNAME:F"` |

## Resolving the Codex companion on PowerShell
```powershell
$COMPANION = Get-ChildItem "$env:USERPROFILE\.claude\plugins\cache\openai-codex\codex\*\scripts\codex-companion.mjs" |
  Sort-Object FullName | Select-Object -Last 1 -ExpandProperty FullName
node "$COMPANION" task "<spec>" --write *> $env:TEMP\codex.log; Get-Content $env:TEMP\codex.log -Tail 30
```

## Grok env on Windows
The `grok-worker.env` template is bash `export` lines — PowerShell can't `source` it. Instead set the three vars in your PowerShell session (or `$PROFILE`):
```powershell
$env:XAI_API_KEY = "sk-..."
$env:GROK_MODELS_BASE_URL = "https://your-endpoint.example.com/v1"
$env:GROK_IMPL_MODEL = "<model-id>"
grok logout
```
Then run grok directly (the `-p` one-shot works the same):
```powershell
grok -p "<spec>" -m $env:GROK_IMPL_MODEL --always-approve --output-format json --cwd (Get-Location).Path *> $env:TEMP\grok.log
```
Under WSL2 / Git Bash, the original `. ~/.grok/grok-worker.env` works unchanged.

## ui-vision-loop on Windows
The script self-bootstraps its venv (`Scripts\python.exe`) and drives Playwright cross-platform. Its **agy runner uses pipes on Windows** (no pty) — this is **best-effort and unverified**: if `agy` suppresses output without a console, run the loop under **WSL2**. Everything else (screenshots, git diff-gate, dev-server) is OS-agnostic.

> If in doubt on Windows, use WSL2 — the whole package then behaves exactly like Linux.
