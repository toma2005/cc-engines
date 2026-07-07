# cc-engines

Delegate Claude Code work to external coding-agent CLIs — **OpenAI Codex**, **xAI Grok**, and **Google Antigravity (Gemini)** — as native subagents and a skill, with a liveness-safe orchestration policy so nothing is left running unverified.

Each engine is a thin Claude Code **subagent** (or skill) that: builds a self-contained spec, runs the engine's CLI **foreground** (no orphaned background jobs), **verifies with `git` + tests you actually run**, and **falls back** to another engine or to Claude. The main model decides — after planning — which engine to use and whether to run inline, in a subagent, or in parallel.

> Nothing here contains credentials. Bring your own CLIs and keys. See [Security](#security).

## What you get

| Component | Type | Engine | Use for |
|---|---|---|---|
| `codex-impl` | subagent | OpenAI Codex | code implementation |
| `codex-debug` | subagent | OpenAI Codex | root-cause investigation |
| `codex-review` | subagent | OpenAI Codex | code review / red-team |
| `grok-impl` | subagent | xAI Grok | code implementation |
| `agy-ui` | subagent | Antigravity (Gemini) | UI / layout, mockup→spec |
| `ui-vision-loop` | skill | Antigravity + Playwright | closed-loop visual fidelity (edit → screenshot → iterate) |
| routing policy + liveness protocol | docs | — | how the model routes + why it's safe |

Every engine is optional and independent — if its CLI isn't installed, that agent falls back to Claude.

## Install

```bash
npx cc-engines            # install into ./.claude (current project)
npx cc-engines --user     # install into ~/.claude (all projects)
npx cc-engines --force    # overwrite existing files
```

Or from GitHub before it's published to npm:
```bash
npx github:<your-org>/cc-engines
```

This copies the agents into `<target>/.claude/agents/`, the skill into `.claude/skills/`, and the docs + env template into `.claude/cc-engines/`. **Restart Claude Code** afterward so the registry reloads.

## Prerequisites (install only the engines you want)

- **OpenAI Codex** — the [`codex@openai-codex`](https://github.com/openai/codex-plugin-cc) Claude Code plugin (provides the `codex-companion` runtime), authenticated.
- **xAI Grok** — `curl -fsSL https://x.ai/cli/install.sh | bash`, plus BYOK config (below).
- **Google Antigravity `agy`** — install the `agy` CLI and pick a model (`agy models`).
- **ui-vision-loop** — any `python3` with `venv`; Playwright + Chromium are self-bootstrapped on first run (~150MB once).

### Grok BYOK setup
```bash
cp <target>/.claude/cc-engines/templates/grok-worker.env.example ~/.grok/grok-worker.env
# edit: set XAI_API_KEY, GROK_MODELS_BASE_URL (must end in /v1), GROK_IMPL_MODEL
chmod 600 ~/.grok/grok-worker.env
grok logout   # so the API key is used instead of a cached login
```

## Usage

After install + restart, the agents are available to Claude Code (via the Agent tool / `/agents`) and auto-trigger by their descriptions. You can also invoke explicitly, e.g. "use codex-impl to implement X" or "run the ui-vision-loop skill on /dashboard".

The model routes per [`orchestration-routing-policy.md`](assets/docs/orchestration-routing-policy.md): pick the engine by task type, prefer running **inline** (cheapest), use a **subagent** only to isolate a noisy task or to **parallelize** N independent tasks. To make routing consistent, paste that policy into your project's `CLAUDE.md` or a memory file.

Read [`liveness-protocol.md`](assets/docs/liveness-protocol.md) for why the wrappers run engines foreground and gate "done" on real `git` + test output.

## Security

- **No credentials ship with this package.** The Grok key/endpoint live only in `~/.grok/grok-worker.env` (outside any repo, `chmod 600`), created from a placeholder template.
- Codex/Grok/agy edit files in their own sandboxes, outside Claude Code's permission prompts — review the resulting `git diff` before committing.
- Confirm your own repo stays clean: `grep -rn "sk-" .` should find nothing but the `.example` placeholder.

## Notes & limitations

- Grok and agy CLIs need a real terminal for their interactive modes; the wrappers use their headless paths (`grok -p`, `agy -p`) to run non-interactively.
- The `agy-ui` and `ui-vision-loop` scope defaults are generic (`allow **`); set `--allow`/`--deny` (or edit the agent) to your project's UI paths.
- Model ids and CLI flags belong to the upstream tools and may change; the agents pin nothing engine-specific beyond what the env/config provides.

## License

MIT — see [LICENSE](LICENSE).
