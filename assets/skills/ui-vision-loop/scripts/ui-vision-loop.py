#!/usr/bin/env python3
"""Self-contained UI vision loop: agy edits → Playwright screenshots → agy sees → iterate.

Replaces the agy-ui MCP server's `ui_implement` with a plain CLI so there is no
per-session MCP token cost. The whole loop runs in this subprocess and returns a
single JSON summary; screenshots stay on disk (their paths are fed back to agy,
which opens them with its own read_file tool — the agy CLI has no image flag).

Dependencies: the `agy` CLI on PATH. Playwright is self-bootstrapped into a
dedicated virtualenv when missing. No third-party imports at module load so
`--help` works anywhere; playwright is imported lazily inside capture().

Key agy quirk (verified): agy loses stdout when not attached to a TTY, so it is
driven through a pseudo-terminal, never a plain pipe.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

# --- agy runner (PTY-based; agy drops stdout on a non-TTY) --------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\r", "")


def run_agy(prompt: str, cwd: str, *, model: str | None, continue_: bool,
            add_dirs: list[str], timeout: int) -> str:
    """Run `agy -p <prompt>` in cwd through a PTY; return cleaned stdout."""
    import pty  # POSIX-only; local import keeps non-POSIX --help working.

    argv = ["agy", "--dangerously-skip-permissions"]
    if model:
        argv += ["--model", model]
    if continue_:
        argv.append("--continue")  # keep conversation context across rounds
    for d in add_dirs:
        argv += ["--add-dir", d]    # let agy read screenshots outside cwd
    argv += ["-p", prompt]

    master_fd, slave_fd = pty.openpty()
    chunks: list[bytes] = []
    proc = subprocess.Popen(argv, cwd=cwd, stdin=slave_fd, stdout=slave_fd,
                            stderr=slave_fd, close_fds=True)
    os.close(slave_fd)
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                break
            ready, _, _ = select.select([master_fd], [], [], min(remaining, 1.0))
            if master_fd in ready:
                try:
                    data = os.read(master_fd, 65536)
                except OSError:
                    break
                if not data:
                    break
                chunks.append(data)
            elif proc.poll() is not None:
                break
        proc.wait(timeout=5)
    finally:
        os.close(master_fd)
    return _strip_ansi(b"".join(chunks).decode("utf-8", errors="replace"))


_SCORE_RE = re.compile(r"^\s*MATCH_SCORE:\s*(-?\d+)", re.MULTILINE)
_GAPS_RE = re.compile(r"^\s*GAPS:\s*(.*?)\s*$", re.MULTILINE)


def parse_match(text: str) -> tuple[int | None, str]:
    """Extract the last MATCH_SCORE (0-100) and GAPS line agy self-reports."""
    score = None
    scores = _SCORE_RE.findall(text or "")
    if scores:
        score = max(0, min(100, int(scores[-1])))
    gaps = ""
    gs = _GAPS_RE.findall(text or "")
    if gs and gs[-1].strip() and gs[-1].strip().upper() != "NONE":
        gaps = gs[-1].strip()
    return score, gaps


def build_prompt(task: str, shots: list[str], design_refs: list[str],
                 allow: str, deny: str, want_score: bool) -> str:
    """Assemble one vision-loop turn. Image *paths* are inlined; agy opens them."""
    L = ["You are a frontend UI engineer working in this project.", "",
         f"Task: {task}", ""]
    if shots:
        L.append("Current rendered screenshots (open each with your read_file tool):")
        L += [f"  - {p}" for p in shots]
        L.append("")
    if design_refs:
        L.append("Design reference images to match (open each with read_file):")
        L += [f"  - {p}" for p in design_refs]
        L.append("")
    L += [
        "Scope rules (enforced after your turn by a git diff-gate):",
        f"  - You MAY edit: {allow}",
        f"  - You MUST NOT touch: {deny}",
        "  - Only change styling and presentational component markup. No backend, "
        "API, routing, data fetching, or business logic.",
        "",
        "Compare the current screenshots against the intent and edit files to close "
        "the gap. Make the smallest change that improves fidelity. Do NOT run the "
        "dev server or git commands yourself.",
    ]
    if want_score:
        L += ["",
              "After editing, end your reply with EXACTLY these two lines and nothing after:",
              "MATCH_SCORE: <integer 0-100>",
              "GAPS: <comma-separated remaining visual differences, or NONE>"]
    return "\n".join(L)


# --- Playwright capture -------------------------------------------------------

def wait_ready(url: str, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=3)
            return True
        except urllib.error.HTTPError:
            return True  # server responded (even 4xx) → it is up
        except Exception:
            time.sleep(1)
    return False


def capture(url: str, out_path: str, device: dict, settle_ms: int = 800) -> str:
    """Screenshot url at a device viewport to out_path (PNG). Returns the path."""
    from playwright.sync_api import sync_playwright

    ctx_kwargs: dict = {
        "viewport": {"width": device["width"], "height": device["height"]},
        "device_scale_factor": device.get("device_scale_factor", 1),
        "is_mobile": device.get("is_mobile", False),
        "has_touch": device.get("has_touch", False),
        "reduced_motion": "reduce",
    }
    if device.get("user_agent"):
        ctx_kwargs["user_agent"] = device["user_agent"]
    dest = Path(out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=15000)
        except Exception:
            page.goto(url, wait_until="load", timeout=15000)
        page.wait_for_timeout(settle_ms)
        page.screenshot(path=str(dest), full_page=device.get("full_page", False),
                        type="png")
        browser.close()
    return str(dest)


# --- git diff-gate helper -----------------------------------------------------

def _status_hash(project_dir: str) -> str:
    out = subprocess.run(["git", "status", "--porcelain"], cwd=project_dir,
                         capture_output=True, text=True).stdout
    return hashlib.sha256(out.encode()).hexdigest()


def _changed_files(project_dir: str) -> list[str]:
    return [path for _, path in _status_entries(project_dir)]


def _status_entries(project_dir: str) -> list[tuple[str, str]]:
    out = subprocess.run(["git", "status", "--porcelain"], cwd=project_dir,
                         capture_output=True, text=True).stdout
    entries = []
    for line in out.splitlines():
        if not line.strip():
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1]
        entries.append((line[:2], path))
    return entries


def _venv_python(env_dir: Path) -> Path:
    return env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _venv_bin(env_dir: Path, name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    return env_dir / ("Scripts" if os.name == "nt" else "bin") / f"{name}{suffix}"


def _ensure_playwright() -> None:
    try:
        __import__("playwright")
        return
    except ImportError:
        pass

    cache_home = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    env_dir = Path(os.environ.get("UI_VISION_ENV_DIR",
                                  os.path.join(cache_home, "ui-vision-loop/env")))
    env_python = _venv_python(env_dir)
    noticed = False
    if not env_python.exists():
        print("Bootstrapping Playwright for ui-vision-loop (~150MB one-time download)...",
              file=sys.stderr)
        noticed = True
        subprocess.check_call([sys.executable, "-m", "venv", str(env_dir)])

    has_playwright = subprocess.run(
        [str(env_python), "-c", "import playwright"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0
    if not has_playwright:
        if not noticed:
            print("Bootstrapping Playwright for ui-vision-loop (~150MB one-time download)...",
                  file=sys.stderr)
        subprocess.check_call([str(env_python), "-m", "pip", "install", "-q", "playwright"])
        subprocess.check_call([str(_venv_bin(env_dir, "playwright")), "install", "chromium"])

    if os.path.realpath(sys.executable) != os.path.realpath(env_python):
        if os.environ.get("UI_VISION_BOOTSTRAPPED") == "1":
            raise RuntimeError("Playwright bootstrap re-exec guard tripped")
        env = os.environ.copy()
        env["UI_VISION_BOOTSTRAPPED"] = "1"
        os.execve(str(env_python), [str(env_python), str(Path(__file__).resolve()), *sys.argv[1:]], env)

    __import__("playwright")


def _parse_port(url: str) -> int | None:
    match = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://[^/:?#]+:(\d+)", url)
    return int(match.group(1)) if match else None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _resolve_port(url: str, serve_cmd: str, requested: int | None) -> int | None:
    port = _parse_port(url) if requested is None else requested
    if port == 0 or (port is None and ("{port}" in url or "{port}" in serve_cmd)):
        return _free_port()
    return port


def _with_port_template(value: str, port: int | None) -> str:
    return value if port is None else value.replace("{port}", str(port))


def _git_root(project_dir: str) -> str | None:
    proc = subprocess.run(["git", "-C", project_dir, "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _symlink(src: Path, dest: Path) -> bool:
    if dest.exists() or dest.is_symlink():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src, dest, target_is_directory=src.is_dir())
    return True


def _link_runtime_deps(repo_root: str, worktree: str) -> set[str]:
    root = Path(repo_root)
    wt = Path(worktree)
    linked: set[str] = set()
    for dirpath, dirs, _ in os.walk(root):
        rel_parts = Path(dirpath).relative_to(root).parts
        if ".git" in rel_parts or "node_modules" in rel_parts:
            dirs[:] = []
            continue
        if len(rel_parts) >= 3:
            dirs[:] = []
        for name in list(dirs):
            if name == "node_modules":
                rel = Path(dirpath).relative_to(root) / name
                if len(rel.parts) <= 3 and _symlink(root / rel, wt / rel):
                    linked.add(str(rel))
                dirs.remove(name)
        if ".git" in dirs:
            dirs.remove(".git")

    for dirpath, dirs, files in os.walk(root):
        rel_parts = Path(dirpath).relative_to(root).parts
        if ".git" in rel_parts or "node_modules" in rel_parts:
            dirs[:] = []
            continue
        if len(rel_parts) > 2:
            dirs[:] = []
            continue
        for name in files:
            if name.startswith(".env"):
                rel = Path(dirpath).relative_to(root) / name
                if _symlink(root / rel, wt / rel):
                    linked.add(str(rel))
    return linked


def _create_worktree(project_dir: str, warnings: list[str]) -> tuple[str | None, str | None, set[str]]:
    repo_root = _git_root(project_dir)
    if not repo_root:
        warnings.append("not a git repository; falling back to in-place mode")
        return None, None, set()
    if subprocess.run(["git", "-C", repo_root, "status", "--porcelain"],
                      capture_output=True, text=True).stdout.strip():
        warnings.append("uncommitted changes are NOT included; worktree is created from HEAD")
    worktree = tempfile.mkdtemp(prefix="ui-vision-worktree-")
    shutil.rmtree(worktree)
    try:
        subprocess.check_call(["git", "-C", repo_root, "worktree", "add", "--detach", worktree, "HEAD"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return repo_root, worktree, _link_runtime_deps(repo_root, worktree)
    except Exception:
        _remove_worktree(repo_root, worktree)
        raise


def _split_patterns(value: str) -> list[str]:
    return [p.strip() for p in value.split(",") if p.strip()]


def _in_scope(path: str, allow: list[str], deny: list[str]) -> bool:
    if any(fnmatch.fnmatch(path, pattern) for pattern in deny):
        return False
    return any(fnmatch.fnmatch(path, pattern) for pattern in allow)


def _copy_in_scope_changes(worktree: str, project_dir: str,
                           allow: str, deny: str, skip: set[str]) -> tuple[list[str], list[str]]:
    allow_patterns = _split_patterns(allow) or ["**"]
    deny_patterns = _split_patterns(deny)
    applied, gated = [], []
    for status, rel in _status_entries(worktree):
        if any(rel == s or rel.startswith(f"{s}/") for s in skip):
            gated.append(rel)
            continue
        if not _in_scope(rel, allow_patterns, deny_patterns):
            gated.append(rel)
            continue
        src = Path(worktree) / rel
        dest = Path(project_dir) / rel
        if status.strip() == "D" or not src.exists():
            if dest.exists() or dest.is_symlink():
                if dest.is_dir() and not dest.is_symlink():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            applied.append(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src, dest, symlinks=True)
        else:
            shutil.copy2(src, dest)
        applied.append(rel)
    return applied, gated


def _remove_worktree(repo_root: str | None, worktree: str | None) -> None:
    if not repo_root or not worktree:
        return
    subprocess.run(["git", "-C", repo_root, "worktree", "remove", "--force", worktree],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- main loop ----------------------------------------------------------------

DEFAULT_DEVICES = [
    {"name": "desktop-large", "width": 1920, "height": 1080,
     "device_scale_factor": 1, "is_mobile": False, "has_touch": False},
    {"name": "ios", "width": 390, "height": 844, "device_scale_factor": 3,
     "is_mobile": True, "has_touch": True,
     "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                   "Mobile/15E148 Safari/604.1"},
]


def main() -> int:
    ap = argparse.ArgumentParser(description="agy UI vision loop (no MCP).")
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--url", required=True, help="Base dev-server URL, e.g. http://localhost:3000")
    ap.add_argument("--route", default="", help="Route appended to url, e.g. /dashboard")
    ap.add_argument("--serve-cmd", default="", help="Command to start the dev server if not already up")
    ap.add_argument("--port", type=int, default=None, help="Port for {port} templates; 0 chooses a free port")
    ap.add_argument("--ready-timeout", type=int, default=60)
    ap.add_argument("--devices", default="", help="JSON list of device dicts; default = desktop-large + ios")
    ap.add_argument("--design-ref", action="append", default=[], help="Design reference image path (repeatable)")
    ap.add_argument("--allow", default="**")
    ap.add_argument("--deny", default="")
    ap.add_argument("--max-iters", type=int, default=4)
    ap.add_argument("--match-threshold", type=int, default=90)
    ap.add_argument("--model", default="Gemini 3.5 Flash (High)")
    ap.add_argument("--agy-timeout", type=int, default=600)
    wt = ap.add_mutually_exclusive_group()
    wt.add_argument("--worktree", dest="worktree", action="store_true", default=True)
    wt.add_argument("--no-worktree", dest="worktree", action="store_false")
    args = ap.parse_args()

    _ensure_playwright()

    project_dir = str(Path(args.project_dir).resolve())
    devices = json.loads(args.devices) if args.devices else [dict(d) for d in DEFAULT_DEVICES]
    port = _resolve_port(args.url, args.serve_cmd, args.port)
    url = _with_port_template(args.url, port)
    serve_cmd = _with_port_template(args.serve_cmd, port)
    target_url = url.rstrip("/") + (args.route or "")
    design_refs = [str(Path(p).resolve()) for p in args.design_ref]
    want_score = bool(design_refs)

    result: dict = {"iterations": 0, "files_changed": [], "shots_before": [],
                    "shots_after": [], "match_score": None, "match_gaps": "",
                    "stopped_reason": "", "warnings": [], "worktree_used": False,
                    "gated_files": [], "applied_files": []}

    started_server = None
    repo_root = None
    worktree = None
    runtime_links: set[str] = set()
    run_dir = project_dir
    exit_code = 0
    try:
        if args.worktree:
            repo_root, worktree, runtime_links = _create_worktree(project_dir, result["warnings"])
            if worktree:
                run_dir = worktree
                result["worktree_used"] = True

        # Ensure dev server.
        if not wait_ready(target_url, timeout=3):
            if not serve_cmd:
                result["stopped_reason"] = f"dev server not reachable at {target_url} and no --serve-cmd given"
                exit_code = 2
            else:
                started_server = subprocess.Popen(serve_cmd, cwd=run_dir, shell=True,
                                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                                  start_new_session=True)
                if not wait_ready(target_url, timeout=args.ready_timeout):
                    result["stopped_reason"] = f"dev server failed to become ready at {target_url}"
                    exit_code = 2

        if exit_code == 0:
            shots_dir = tempfile.mkdtemp(prefix="ui-vision-shots-")
            add_dirs = [shots_dir, run_dir] + [str(Path(p).parent) for p in design_refs]

            def shoot(tag: str) -> list[str]:
                paths = []
                for i, dev in enumerate(devices):
                    name = dev.get("name", f"dev{i}")
                    out = os.path.join(shots_dir, f"{tag}-{name}.png")
                    try:
                        paths.append(capture(target_url, out, dev))
                    except Exception as e:  # a capture failure shouldn't kill the loop
                        result["warnings"].append(f"capture {tag}/{name} failed: {e}")
                return paths

            result["shots_before"] = shoot("iter0")
            last_shots = result["shots_before"]
            for it in range(1, args.max_iters + 1):
                result["iterations"] = it
                before_hash = _status_hash(run_dir)
                prompt = build_prompt(args.task, last_shots, design_refs,
                                      args.allow, args.deny, want_score)
                out = run_agy(prompt, run_dir, model=args.model, continue_=(it > 1),
                              add_dirs=add_dirs, timeout=args.agy_timeout)
                score, gaps = parse_match(out)
                if score is not None:
                    result["match_score"] = score
                result["match_gaps"] = gaps
                after_hash = _status_hash(run_dir)

                last_shots = shoot(f"iter{it}")
                result["shots_after"] = last_shots

                if after_hash == before_hash:
                    result["stopped_reason"] = "no new edits this round (converged/stuck)"
                    break
                if want_score and score is not None and score >= args.match_threshold:
                    result["stopped_reason"] = f"match_score {score} >= threshold {args.match_threshold}"
                    break
            else:
                result["stopped_reason"] = f"reached max_iters {args.max_iters}"

            result["files_changed"] = _changed_files(run_dir)
            if worktree:
                applied, gated = _copy_in_scope_changes(worktree, project_dir,
                                                        args.allow, args.deny, runtime_links)
                result["applied_files"] = applied
                result["gated_files"] = gated
    finally:
        _stop(started_server)
        _remove_worktree(repo_root, worktree)

    print(json.dumps(result, indent=2))
    return exit_code


def _stop(proc) -> None:
    if proc is None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), 15)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
