# Liveness & Verification Protocol

Why the engine subagents in this package are built the way they are. The failure modes below are real; the rules prevent them.

## The one thing to internalize
A completion notification tells you the Claude wrapper's turn ended — **NOT** that the engine finished, **NOT** that the code is correct. Correctness is known only from ground truth you run yourself: `git diff` + tests. Every self-report (the engine's, or a Claude subagent's) is **advisory**.

## Two nested layers
| Layer | What it is | Notifies? |
|---|---|---|
| Outer = the wrapper subagent (`codex-impl`, `grok-impl`, …) | A real Claude instance; its system prompt tells it to call an engine | ✅ when its turn ends |
| Inner = Codex / Grok / agy | A CLI process, own sandbox, outside Claude Code's permission model | ❌ notifies no one — writes files + returns stdout |

## Failure modes
1. **Orphan** — the wrapper runs the engine with `--background` then ends its turn → engine detached, code lands on disk, nobody verifies. The "subagent finished" signal is misleading.
2. **Blind wait** — waiting on something that never signals → stall.
3. **Trust-the-report** — accepting "done" without git + tests → subtle wrong code passes.
4. **Survivor after stop** — killing/stopping the wrapper (`TaskStop`, timeout, harness kill) does NOT stop the engine it spawned. Codex dispatches to a **persistent `codex app-server` broker** that keeps running server-side after the stop (and can keep writing the tree + spawn child MCP processes, eating RAM); a lingering `grok`/`agy` process is possible too. The "stopped" signal is misleading — reap explicitly (Rule 7).

## Rules
1. **Prefer main-thread-direct.** Call the engine from the main context (foreground); spawn a wrapper subagent only to isolate a large/noisy transcript or to parallelize.
2. **Foreground + redirect verbose to a log; read only a tail.** The engine's narration is noise; ground truth is git + tests.
3. **Never engine-level `--background`.** Inside a subagent it orphans. Long task on the main thread → wrap a foreground engine call in the harness's own `run_in_background` (its exit == the engine's exit == an accurate notification); a subagent cannot reliably receive that callback, so subagents run foreground only.
4. **Every wait is a bounded poll to ground truth, never a blind sleep**; on deadline, cancel/kill then verify on disk.
5. **DONE requires receipts** — `git status` + the narrowest real check, run and pasted, in the same turn. No receipts → BLOCKED.
6. **Fallback chain**: engine → other engine → Claude. Never silently skip verification.
7. **Reap on kill.** After any `TaskStop` / timeout / kill of an engine subagent, immediately reap its leftovers before anything else: `ps -eo pid,ppid,command | grep -E 'app-server-broker| grok | agy'` → for a broker reparented to init (`ppid=1`), confirm its `--cwd` is THIS project (never kill another project's broker) → `kill -9` the broker + its children (or the companion's `cancel <job-id>`), verify gone, THEN verify the disk. Skipping this leaves orphaned daemons eating RAM (a killed Codex wrapper left a ~93 MB broker tree that had even spawned its own child MCPs).

## Context cost (why redirect-to-file matters)
The main context is a **recurring** cost (re-sent every turn). A subagent's context is a **one-time** cost. So: small/modest output → inline + redirect-to-file + read a tail; huge/noisy → subagent (its transcript never touches the main window; you only get its summary).

## Residual risk
git + tests catch everything except *the engine writes subtly-wrong code AND its own test doesn't cover it*. Mitigate with TDD-lock (author/lock the test first, engine implements against a test it didn't write) + an independent review pass. Highest feasible assurance, not absolute.
