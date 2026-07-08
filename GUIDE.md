# cc-engines — Full Guide

A complete walkthrough: what it is, how to install it into a project, how to wire each engine, how Claude decides what to run where, and how to work on large tasks safely.

**Contents**
1. [Mental model](#1-mental-model)
2. [The engines](#2-the-engines)
3. [Install (project scope + merge)](#3-install-project-scope--merge)
4. [Configure each engine](#4-configure-each-engine)
5. [How Claude routes work](#5-how-claude-routes-work)
6. [Working on large tasks](#6-working-on-large-tasks)
7. [Verification & safety](#7-verification--safety)
8. [Security](#8-security)
9. [Troubleshooting](#9-troubleshooting)
10. [Cheat sheet](#10-cheat-sheet)
11. [Uninstall](#11-uninstall)

---

## 1. Mental model

cc-engines does not add a new AI. It lets **Claude Code delegate work to external coding-agent CLIs** you already have — OpenAI **Codex**, xAI **Grok**, Google **Antigravity (Gemini/`agy`)** — and to a Playwright-driven **vision loop**. Claude stays the orchestrator: it plans, picks the engine, hands over a scoped spec, and — crucially — **verifies the result itself with `git` + tests**. Engines do the typing; Claude owns correctness.

Two forms ship:
- **Subagents** (`codex-impl`, `codex-debug`, `codex-review`, `grok-impl`, `agy-ui`) — a real Claude instance whose only job is to drive one engine and verify it. Use to isolate a noisy task or to run several in parallel.
- **Skills** (`code-impl`, `ui-vision-loop`) — instructions Claude runs **inline** in the current context (no second Claude). Cheapest path for a single task.

Everything is optional: if an engine's CLI isn't installed, its agent falls back to Claude.

## 2. The engines

| Component | Kind | Engine / tool | Best for |
|---|---|---|---|
| `codex-impl` | subagent | OpenAI Codex | code implementation |
| `codex-debug` | subagent | OpenAI Codex | root-cause investigation |
| `codex-review` | subagent | OpenAI Codex | code review / red-team (read-only) |
| `grok-impl` | subagent | xAI Grok | fast, well-specified implementation |
| `agy-ui` | subagent | Antigravity (Gemini) | UI/layout, mockup → spec |
| `code-impl` | skill | Codex **or** Grok | a single implementation task, **inline** |
| `ui-vision-loop` | skill | Antigravity + Playwright | visual fidelity: edit → screenshot → iterate |

Docs shipped alongside (installed to `.claude/cc-engines/`): `orchestration-routing-policy.md`, `liveness-protocol.md`, `task-decomposition-and-notes.md`, plus `templates/`.

## 3. Install (project scope + merge)

**Default is project scope.** Stand in your project folder and run:
```bash
npx github:toma2005/cc-engines
```
This installs into **`./.claude/`** of the current directory only — the agents, skills, docs, and templates for that one project. (Prints the exact target path it writes to.)

Other targets:
```bash
npx github:toma2005/cc-engines --user       # ~/.claude (available in every project)
npx github:toma2005/cc-engines --dir /path  # /path/.claude
```

**Merge semantics — your config is never clobbered.** The installer is **add-only**:
- It writes only under `.claude/agents/`, `.claude/skills/`, `.claude/cc-engines/`. It **never touches** `settings.json`, `settings.local.json`, or anything else.
- For each file: if it already exists, it is **skipped** (your version is kept) — nothing is overwritten.
- Re-running is **idempotent** (a second run copies 0, skips all).
- Agent names are **engine-prefixed** (`codex-impl`, `grok-impl`, `agy-ui`, …) specifically so they don't collide with your own agents.

**Updating to a newer cc-engines release:**
```bash
npx github:toma2005/cc-engines --force       # overwrites cc-engines files with the latest
```
`--force` overwrites even a cc-engines file you edited locally — only use it when you want the upstream version.

**After installing, restart Claude Code** so the agent/skill registry reloads.

## 4. Configure each engine

Each engine is independent. Set up only the ones you want.

### OpenAI Codex
Install the `codex@openai-codex` Claude Code plugin (provides the `codex-companion` runtime) and authenticate it. The `codex-*` agents resolve the runtime automatically; if it's absent they fall back to Claude.

### xAI Grok (BYOK)
```bash
cp .claude/cc-engines/templates/grok-worker.env.example ~/.grok/grok-worker.env
# edit ~/.grok/grok-worker.env:
#   XAI_API_KEY         = your key
#   GROK_MODELS_BASE_URL= your inference endpoint, MUST end in /v1
#   GROK_IMPL_MODEL     = the model id (see: grok models)
chmod 600 ~/.grok/grok-worker.env
grok logout   # IMPORTANT: forces API-key auth instead of a cached login
```
Why `grok logout`: if grok has a cached OIDC login, it sends that token to your endpoint and you get `401 Invalid API key`. Logging out makes it use `XAI_API_KEY`. The key lives only in `~/.grok/grok-worker.env` — outside any repo.

### Antigravity (`agy`)
Install the `agy` CLI and confirm a model with `agy models`. The `agy-ui` agent passes the model by its full display name (e.g. `"Gemini 3.5 Flash (High)"`).

### ui-vision-loop (Playwright)
Needs any `python3` with `venv`. Playwright + Chromium are **self-bootstrapped** on first run into `~/.cache/ui-vision-loop/venv` (~150 MB, once). Nothing else to install.

## 5. How Claude routes work

Claude applies a layered policy (full text in `.claude/cc-engines/orchestration-routing-policy.md`; paste it into your `CLAUDE.md` to make it stick):

1. **Size gate** — trivial edits (a few lines, files known) → Claude does them directly, **no engine** (the engine's agentic loop + verify costs minutes and dwarfs a tiny change).
2. **By task type** — UI-with-render → `ui-vision-loop`; pure markup → `agy-ui`; implementation → Codex/Grok; debug → `codex-debug`; review → `codex-review`; planning → usually Claude itself.
3. **Engine (Codex vs Grok)** — both implement code. Grok = fast, well-specified. Codex = mature, handles ambiguous/intricate (a bit slower). Cross-fall back on failure.
4. **Inline vs subagent** — **inline (`code-impl` skill) is the default** for one task (cheapest, no spawn). Use a **subagent** only to isolate a noisy transcript or to parallelize.
5. **Parallel waves + per-slice choice** — split a big task into independent slices (non-overlapping files) and pick the engine **per slice**:
   - **Sensitive code** (revenue/billing/payments, auth/security, DB migrations, wide blast radius) → run as a **Claude subagent (in-context)**, not an external engine, then a **mandatory `codex-review`**. External engines edit in an opaque sandbox; keep sensitive edits visible in Claude's permission system.
   - Normal + fast → Grok. Normal + intricate → Codex. UI → agy. Glue/cross-cutting → Claude.
   - Wave by dependency: independent slices first (parallel) → verify each → then dependent slices.

## 6. Working on large tasks

See `.claude/cc-engines/task-decomposition-and-notes.md`. In short:

- **Decompose** a milestone into **slices**, each with **≥1 testable acceptance criterion** (this AC becomes the engine's spec). If you can't state an AC, the slice is too vague — research or split first.
- **Slice lifecycle**: gap-research (optional) → implement (engine/inline) → validate (proportional check) → **close** with an evidence index (`templates/slice-closure.md`): reader contract + where-to-look + rerunnable proof commands.
- **CONTINUITY ledger** (`templates/CONTINUITY.md`): a ~20-line running handoff (Ctx / Goal / State ✓○ / Decisions / Working / open questions) so the next session or a fresh engine resumes without re-scanning.
- **Agent notes**: the wrapper agents set `memory: project`, so each keeps `.claude/agent-memory/<agent>/` across sessions — record **verified findings** (`file:line`, grep/live-confirmed) and **"verified OK — don't re-flag"** facts so future passes don't re-litigate.

## 7. Verification & safety

Full rationale in `.claude/cc-engines/liveness-protocol.md`. The rules the agents follow:

- **Foreground only.** Engines run as blocking foreground calls; the agents never use an engine's own `--background` (that would detach the job and orphan it). A single subagent already runs in the host's background and notifies on completion.
- **Ground truth = git + tests you run.** An engine's own "done" / summary is **advisory**. A phase is DONE only when the agent has pasted real `git status` + a check.
- **Proportional verify.** Small/UI edit → typecheck the touched package / lint changed files / read the diff. Full suite/build **only** when a shared contract changed. (Running a full monorepo test+build on a few-line change is the #1 cause of slowness.)
- **Fallback chain.** Engine missing or failing → other engine → Claude. Nothing is skipped silently.

## 8. Security

- **No credentials are bundled.** The only secret (the Grok key) lives in `~/.grok/grok-worker.env` (outside any repo, `chmod 600`), created from a placeholder template.
- Engines edit files in their own sandboxes, outside Claude Code's permission prompts — **review the `git diff` before committing**, especially for anything sensitive.
- Verify your repo stays clean: `grep -rn "sk-" .` should find nothing but the `.example` placeholder.

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Grok: `401 Invalid API key` | grok using a cached OIDC login, not the key | `grok logout`; ensure `XAI_API_KEY` set |
| Grok: `unauthorized` from `/models` | endpoint missing `/v1` | set `GROK_MODELS_BASE_URL` to end in `/v1` |
| Grok: `Device not configured (os error 6)` | ran the interactive TUI (`grok "prompt"`) headless | use `grok -p` (the agents already do) |
| agy: hangs, zero output | backgrounded / no TTY | run foreground, ONE call, `< /dev/null`; never `run_in_background` |
| A task takes 10-15 min for a small change | full test/build verify + wrong routing | let Claude do small edits directly; verify proportional to the change |
| `codex-*` agent falls back to Claude | codex plugin not installed | install `codex@openai-codex`, or accept the Claude fallback |
| New agents/skills don't appear | registry loads at startup | restart Claude Code after install |

## 10. Cheat sheet

```bash
# install into current project (merge, keep config)
npx github:toma2005/cc-engines
# update to latest
npx github:toma2005/cc-engines --force

# Grok one-shot (what grok-impl runs), foreground:
. ~/.grok/grok-worker.env
grok -p "<spec>" -m "$GROK_IMPL_MODEL" --always-approve --output-format json --cwd "$(pwd)" < /dev/null

# Codex one-shot (what codex-impl runs):
COMPANION=$(ls -d "$HOME"/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs | sort -V | tail -1)
node "$COMPANION" task "<spec>" --write

# UI vision loop:
python3 .claude/skills/ui-vision-loop/scripts/ui-vision-loop.py \
  --project-dir "$(pwd)" --task "<goal>" --url "http://localhost:{port}" \
  --serve-cmd "<dev server cmd on {port}>" --port 0
```

## 11. Uninstall

Remove the installed files; nothing else was touched:
```bash
rm -rf .claude/agents/{codex-impl,codex-debug,codex-review,grok-impl,agy-ui}.md \
       .claude/skills/{code-impl,ui-vision-loop} \
       .claude/cc-engines
# optional: rm ~/.grok/grok-worker.env
```
