---
name: ui-vision-loop
description: Closed-loop UI implementation where Gemini (agy) edits code, Playwright screenshots the rendered result, and the screenshot is fed back to agy to iterate — until it visually matches the intent or a design mockup. Use for pixel-level layout/visual fidelity on a running web app (a page/component that renders at a URL). Token-free CLI (no MCP). Not for pure markup with nothing to render, or non-UI code.
---

# UI Vision Loop

A subprocess loop that gives Gemini **eyes**: it edits the UI, sees its own render via a real browser screenshot, and closes the gap — with almost no Claude tokens spent (the whole loop runs in one CLI call; only a JSON summary returns).

## When to use
A page/component that **renders at a URL** and must match a visual intent or a design mockup, where fidelity should be *verified by looking* — not by reading class names. Not for pure markup with nothing to render, backend, or non-UI code.

## Prerequisites (self-contained)
- `agy` CLI (Google Antigravity) on PATH, configured with a model.
- Any `python3` (3.8+) with `venv`. Playwright is **self-provisioned**: on first run the script creates its own venv (default `~/.cache/ui-vision-loop/venv`, override `UI_VISION_ENV_DIR`), installs playwright + chromium (~150MB, once), and re-execs into it. Copy this folder into any repo and it bootstraps itself.
- The web app's dev-server command + URL.

## Usage
ONE foreground call under plain `python3`:
```bash
python3 .claude/skills/ui-vision-loop/scripts/ui-vision-loop.py \
  --project-dir "$(pwd)" \
  --task "<what the UI should look like>" \
  --url "http://localhost:{port}" --route "/some-route" \
  --serve-cmd "<command that starts the dev server on {port}>" --port 0 \
  --model "Gemini 3.5 Flash (High)" --max-iters 4
```
`{port}` is substituted into `--url`/`--serve-cmd`; `--port 0` auto-picks a free port (so an isolated worktree server never collides with an already-running dev server). Returns JSON: `iterations`, `files_changed`, `applied_files`, `gated_files`, `shots_before`, `shots_after`, `match_score`, `stopped_reason`, `warnings`, `worktree_used`.

### Key options
- `--design-ref <path>` (repeatable): mockup image(s) to match → enables self-scored convergence (agy reports `MATCH_SCORE: 0-100` per round; stops at `--match-threshold`, default 90).
- `--devices <json>`: override viewports. Default captures TWO every round: `desktop-large` (1920×1080) + `ios` (390×844 @3x, mobile+touch).
- `--worktree` / `--no-worktree`: worktree isolation is ON by default (agy edits in a throwaway git worktree; only files matching `--allow` and not `--deny` are copied back — out-of-scope edits are gated and never applied). `--no-worktree` runs in place.
- `--allow` / `--deny`: comma-separated globs (deny wins) — scope for the diff-gate. Defaults: allow `**`, deny empty (set them to your project's UI paths).
- `--model`: default `Gemini 3.5 Flash (High)`; use a Pro tier for hard/ambiguous visual tasks.

## How it converges
Each round: screenshot both devices → build a prompt with the shot paths (agy opens them with its own read_file tool; the CLI has no image flag) → `agy -p --continue` edits (in the worktree) → re-screenshot. Stops when agy makes no new edit, or `match_score ≥ threshold` (with `--design-ref`), or `max_iters`.

## After the loop (caller's job)
Worktree mode writes back only in-scope files, so the working tree already has a clean gated diff. Still verify: `git status --short`, grep changed files for anything your project forbids (e.g. hardcoded colors), run your typecheck/build. `shots_after` are the visual evidence — read the final PNGs to confirm.

## Design notes
- agy is driven through a **pseudo-terminal** (it drops stdout on a plain pipe); the loop never backgrounds it.
- Path-gating does NOT catch bad styling *inside* an allowed file — pair with a content check + a re-prompt round.
