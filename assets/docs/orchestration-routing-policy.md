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

## Step 4 — Parallel waves + per-slice engine choice
Split a big task into independent slices (non-overlapping file ownership) and run them in parallel — but **choose the engine per slice by risk and kind**, not one engine for all:

- **Sensitive code** (revenue/billing/payments, auth/security, DB migrations, wide blast radius, hard to reverse) → run it as a **Claude subagent (in-context)**, NOT an external engine. Edits stay inside the permission system and are fully visible; external engines edit in an opaque sandbox. Then **mandatory independent review** (`codex-review`) on that slice.
- **Normal code, well-specified, speed matters** → **Grok** (fastest).
- **Normal code, intricate / Grok weak here / want a second engine** → **Codex** (also implements code, a bit slower — still fine).
- **UI / layout** → **agy** (+ `ui-vision-loop` for render fidelity).
- **Glue / integration / cross-cutting** (needs the plan context, touches several areas) → **Claude** directly.

Rules:
- Parallelize ONLY slices with non-overlapping file ownership (no shared file, migration sequence, or config). A sensitive slice can still run in parallel — just as a Claude subagent.
- **Wave by dependency**: independent slices in Wave 1 (parallel) → verify each (review + proportional test) → then Wave 2 slices that consume Wave 1's output. The host notifies when each subagent finishes.
- **Feed scout findings** (verified, `file:line`) into each slice's spec. If the plan's anchors are wrong (a named file/function doesn't exist), re-scout the real integration points before building that slice.
- Don't over-spawn (performance + host policy).

### Parallel safety — isolate, checkpoint, guard git
The real hazard of parallel engines is a **shared working tree**: N engines editing at once can stomp each other, and one destructive git command (`reset --hard`, `checkout`/`restore` of tracked files, `clean`, `stash`, `rebase`, `push --force`) wipes *everyone's* uncommitted work at once. Defend with, in order of strength:
1. **One git worktree per parallel slice** (best). Each engine runs in its own working dir + branch, so slices can't touch each other's files and a bad git command only affects that slice's worktree. grok has `-w` built in; for a Codex/Claude slice use `git worktree add <dir> HEAD` (symlink `node_modules`/env in for a monorepo). Merge each slice back after it verifies.
2. **Checkpoint before the wave.** If you don't isolate, `git add -A && git commit` (or stash to a named ref) a recovery point before launching, so a wipe is recoverable via `git reflog`.
3. **Forbid destructive git in every slice's spec** (see the engine agents) — engines edit files only; all git stays with the orchestrator.
Also: keep each slice's file ownership strictly non-overlapping, and commit each slice to its own branch/commit as it lands so a later slice can't lose an earlier one.

### Tracking a wave
`TaskList` doesn't see engine jobs. Use `codex-companion status --all` for live Codex jobs; the host notifies when each Claude subagent finishes. Keep a small CONTINUITY-style ledger of `slice → engine → files → status` so the whole wave is visible.

## Always
- Foreground, never engine-level `--background` (see the liveness protocol).
- Verify with git + tests you run yourself before calling anything DONE; engine self-reports are advisory.
- Keep a fallback chain: engine → other engine → Claude.
