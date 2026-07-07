# Orchestration Routing Policy

Guidance for the main Claude Code model to decide, after planning, **which engine** to use and **how** to run it. Not rigid rules — judgment per task. Paste the relevant parts into your project's `CLAUDE.md` or a memory file so routing is consistent.

## Tools on hand (whichever you installed)
- **Codex** → subagents `codex-impl` / `codex-debug` / `codex-review`, or `codex-companion task` directly.
- **Grok** → subagent `grok-impl`, or `grok -p` directly.
- **Antigravity (agy)** → subagent `agy-ui` (markup/layout), skill `ui-vision-loop` (render/vision).
- **Claude (self)** → planning, glue, fallback, small tasks not worth an engine.

## Step 0 — Size gate
Trivial edits (a few lines, files already known) → do them directly, no engine. Only delegate substantial / multi-file / backend work — the engine's agentic loop + verify costs minutes, which dwarfs a tiny change.

## Step 1 — By task type
- UI layout with a render surface (page/component at a URL, fidelity matters) → **`ui-vision-loop`** skill. Pure markup → **`agy-ui`**.
- Backend/frontend code implementation → **Grok or Codex** (your call).
- Debug / root-cause → **`codex-debug`**.
- Plan / architecture → usually do it yourself; delegate only large research.
- Code review / red-team → **`codex-review`**.

## Step 2 — Grok vs Codex (for code impl)
Both are fine; pick per task. Light heuristic: Codex is a solid default (mature, handles ambiguous/complex/debug-adjacent work); Grok suits well-specified tasks with testable acceptance criteria that should run fast. On failure, cross-fall back to the other, then to Claude.

## Step 3 — Inline vs subagent
- **Inline** (call the engine directly in the main context: foreground + redirect log + verify) — the default for a single task where you want the result in context. Cheapest: no second Claude instance, no orphan risk. Best run via the **`code-impl` skill**.
- **Subagent** — only when (a) the engine output would be large/noisy and you want it isolated from the main context, or (b) you need parallelism.

## Step 4 — Parallel
Only when you have N **independent** tasks with **non-overlapping file ownership** (no shared file, migration sequence, or config) → spawn N subagents in one message. Interdependent → run sequentially. Don't over-spawn (performance + host policy).

## Always
- Foreground, never engine-level `--background` (see the liveness protocol).
- Verify with git + tests you run yourself before calling anything DONE; engine self-reports are advisory.
- Keep a fallback chain: engine → other engine → Claude.
