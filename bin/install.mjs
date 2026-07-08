#!/usr/bin/env node
/**
 * cc-engines installer.
 *
 * Copies the engine subagents, the ui-vision-loop skill, and the reference
 * docs into a Claude Code config directory. No credentials, no network, no
 * third-party deps — pure Node stdlib.
 *
 * Usage:
 *   npx cc-engines               # install into ./.claude (current project)
 *   npx cc-engines --user        # install into ~/.claude (all projects)
 *   npx cc-engines --dir <path>  # install into <path>/.claude
 *   npx cc-engines --force       # overwrite existing files
 */
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";
import { homedir } from "node:os";
import fs from "node:fs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = resolve(__dirname, "..");

const args = process.argv.slice(2);
const has = (f) => args.includes(f);
const flagVal = (f) => {
  const i = args.indexOf(f);
  return i >= 0 ? args[i + 1] : undefined;
};

// Resolve the base .claude directory.
let baseParent;
if (flagVal("--dir")) baseParent = resolve(flagVal("--dir"));
else if (has("--user")) baseParent = homedir();
else baseParent = process.cwd();
const CLAUDE_DIR = join(baseParent, ".claude");
const FORCE = has("--force");

const copied = [];
const skipped = [];

function copyInto(srcDir, destDir, { recursive = false } = {}) {
  if (!fs.existsSync(srcDir)) return;
  fs.mkdirSync(destDir, { recursive: true });
  for (const entry of fs.readdirSync(srcDir, { withFileTypes: true })) {
    const src = join(srcDir, entry.name);
    const dest = join(destDir, entry.name);
    if (entry.isDirectory()) {
      if (recursive) copyInto(src, dest, { recursive: true });
      continue;
    }
    if (fs.existsSync(dest) && !FORCE) {
      skipped.push(dest);
      continue;
    }
    fs.mkdirSync(dirname(dest), { recursive: true });
    fs.copyFileSync(src, dest);
    copied.push(dest);
  }
}

console.log(`cc-engines → installing into ${CLAUDE_DIR}\n`);

copyInto(join(PKG_ROOT, "assets/agents"), join(CLAUDE_DIR, "agents"));
copyInto(join(PKG_ROOT, "assets/skills"), join(CLAUDE_DIR, "skills"), { recursive: true });
copyInto(join(PKG_ROOT, "assets/docs"), join(CLAUDE_DIR, "cc-engines"), { recursive: true });
copyInto(join(PKG_ROOT, "templates"), join(CLAUDE_DIR, "cc-engines/templates"));

console.log(`Copied ${copied.length} file(s).`);
for (const p of copied) console.log(`  + ${p.replace(baseParent, ".")}`);
if (skipped.length) {
  console.log(`\nSkipped ${skipped.length} existing file(s) (use --force to overwrite):`);
  for (const p of skipped) console.log(`  = ${p.replace(baseParent, ".")}`);
}

const isWin = process.platform === "win32";
const grokSetup = isWin
  ? `2. For Grok (grok-impl) on native Windows PowerShell, set the vars in your session/profile:
     $env:XAI_API_KEY = "sk-..."; $env:GROK_MODELS_BASE_URL = "https://your-endpoint/v1"; $env:GROK_IMPL_MODEL = "<model>"
     grok logout
     (Under WSL2 / Git Bash, use the POSIX steps in cc-engines/cross-platform.md.)`
  : `2. For Grok (grok-impl), configure BYOK auth OUTSIDE any repo:
     cp ${CLAUDE_DIR}/cc-engines/templates/grok-worker.env.example ~/.grok/grok-worker.env
     # edit it: set XAI_API_KEY, GROK_MODELS_BASE_URL, GROK_IMPL_MODEL
     chmod 600 ~/.grok/grok-worker.env
     grok logout   # so the API key is used instead of a cached login`;

console.log(`
Next steps
----------
1. Install the engine CLI(s) you want (each is optional; the agents fall back
   to Claude if their engine is absent):
     - OpenAI Codex   : the codex@openai-codex Claude Code plugin (provides codex-companion)
     - xAI Grok       : https://x.ai/cli  (install per its docs)
     - Antigravity agy: install the 'agy' CLI (Google Antigravity)
     - ui-vision-loop : any python3 with venv (Playwright is self-bootstrapped)

${grokSetup}

3. (Optional) Paste cc-engines/orchestration-routing-policy.md into your
   project's CLAUDE.md or a memory file so the model routes consistently.

4. Restart Claude Code so the new agents/skills load into the registry.
${isWin ? "\nWindows: the agents use POSIX shell. Use WSL2 or Git Bash (simplest), or translate per cc-engines/cross-platform.md.\n" : ""}`);
