# Task Decomposition & Notes

How to break large work into engine-sized units, hand off across sessions, and accumulate reusable learnings. Pairs with the routing policy (which engine) and the liveness protocol (verify with receipts).

## 1. Decompose before delegating
- Big task → milestone → **slices**. A slice is the smallest unit that has **≥1 testable acceptance criterion** (the same AC the engines require in their spec). Can't name an AC → the slice is too vague; research or split first.
- Order slices by dependency. Mark which slices touch **shared files** — those cannot run in parallel (overlapping ownership).
- Each slice maps to exactly one engine call (codex/grok), one inline edit, or one `ui-vision-loop` run.

## 2. Slice lifecycle
1. **gap-research** (optional) — what's unknown or missing; the questions to answer before building. Cheap to skip for small slices.
2. **implement** — one engine call / inline edit, scoped to the slice's files only.
3. **validate** — the exact commands that prove the AC, plus their real output. **Proportional to the change** (small edit → typecheck/lint the touched files; full suite only when a shared contract changed).
4. **close** — a short evidence index so a future agent/engine doesn't rediscover the work. Use `templates/slice-closure.md`: reader contract + where-to-look + the exact rerun commands + what each proves.

## 3. CONTINUITY ledger (cross-session handoff)
Keep a tiny running ledger at the repo root or plan dir (`templates/CONTINUITY.md`), updated as you go:
`Ctx` (arch/stack in 2 lines) · `Goal` · `State` (✓ done / ○ todo checklist) · `Decisions` · `Working` (branch + touched files) · `?` (open questions).
It is the fastest way for the next session — or a fresh engine — to resume without re-scanning the repo. High signal, ~20 lines, always current.

## 4. Agent notes (accumulate learnings, stop re-solving)
Memory-enabled agents (this package's wrappers set `memory: project`) get a per-agent notes directory at `.claude/agent-memory/<agent>/`:
- **`MEMORY.md`** = one-line index (`- [Title](file.md) — hook`).
- **Topic files** = frontmatter (`name`, `description`, `metadata.type: project|feedback|reference`) + body with **Why** + **How to apply** + `[[links]]` to related notes.

Two patterns worth the discipline:
- **Verified findings** — facts confirmed by grep / a live check, anchored to `file:line` (not guesses). These are trustworthy across sessions.
- **Verified OK — don't re-flag** — things already checked and found fine, so the next review pass doesn't waste time re-litigating them.

Write a note when a review/debug/impl pass surfaces a reusable pattern or a decision worth not rediscovering. Keep one fact per file; update rather than duplicate.

## 5. How it ties together
- Slice ACs feed the engine spec (`code-impl` / `codex-impl` / `grok-impl`).
- "validate proportional to change" is the same rule the wrappers enforce.
- CONTINUITY + closure-evidence are the receipts discipline (see `liveness-protocol.md`) scaled to multi-slice work: nothing is "done" without a rerunnable proof someone can find later.
