---
name: code-impl
description: Run a code-implementation task INLINE in the current context by delegating to an external engine CLI (OpenAI Codex or xAI Grok) — no subagent spawn. Use this as the default for a single implementation task; it builds a spec, runs the engine foreground, and verifies proportionally. Spawn the codex-impl/grok-impl subagents instead only to isolate a large/noisy transcript or to run several independent tasks in parallel.
---

# code-impl (inline engine runner)

Delegate one implementation task to an engine **in the main context** — cheaper and faster than spawning a subagent (no spawn/teardown), and the result + verification stay in context to continue reasoning.

## Size gate (check first)
- **Trivial / a few lines / you already know the files** → just edit it yourself. Do NOT invoke an engine; the engine's agentic loop + verify costs minutes and dwarfs the change.
- **Substantial single task** → use an engine inline (below).
- **Large & noisy, or N independent tasks** → don't use this skill; spawn the `codex-impl`/`grok-impl` subagent(s) (parallel = one subagent per independent task, non-overlapping files).

## 1. Pick the engine
Codex is a solid default (mature); Grok suits well-specified, AC-bearing, fast tasks. Use whichever is installed; cross-fall back on failure, then to yourself.

## 2. Build a tight spec
Task + **≥1 testable acceptance criterion** + absolute repo path (`pwd`) + "read the project's conventions doc" + the **exact files** it may touch (so it doesn't re-scout) + required output.

## 3. Run FOREGROUND, redirect verbose to a log, read the tail
Codex:
```bash
COMPANION=$(ls -d "$HOME"/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs 2>/dev/null | sort -V | tail -1)
node "$COMPANION" task "<spec>" --write > /tmp/code-impl.log 2>&1; echo "exit=$?"; tail -30 /tmp/code-impl.log
```
Grok (requires `~/.grok/grok-worker.env` + `grok logout`):
```bash
. "$HOME/.grok/grok-worker.env"
grok -p "<spec>" -m "$GROK_IMPL_MODEL" --always-approve --output-format json --cwd "$(pwd)" < /dev/null 2>/tmp/code-impl.err | tail -c 1200
```
- **NEVER background** the engine (no `--background`, no `run_in_background`). Foreground = its exit is your result.
- Keep the engine tight: exact files in the spec, low turn budget, no extra self-verify flags.

## 4. Verify — proportional to the change
- `git status --short` — expected files changed? Empty diff = engine did nothing = failure → retry once or do it yourself.
- Small/UI → typecheck the affected package / lint changed files / read the diff. **Do NOT run the full suite for a small change.** Logic/shared/API/many files → focused tests; full build/suite only if a shared contract changed. Paste what you ran.
- DONE only with real git + a proportional check. Engine self-report is advisory.

## 5. Fallback
Engine missing/failing → try the other engine → do it yourself.
