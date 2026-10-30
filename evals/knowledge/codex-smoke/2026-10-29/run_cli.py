"""One authorized generation spike via saved ChatGPT login, never a production backend."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent


def main():
    if any((HERE / name).exists() for name in ("result.json", "run.json", "events.jsonl")):
        raise SystemExit("Run evidence exists; do not overwrite or silently spend more allowance")
    env = dict(os.environ)
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL"):
        env.pop(key, None)
    codex = shutil.which("codex")
    if codex is None:
        raise SystemExit("Codex CLI is unavailable")
    auth = subprocess.run([codex, "login", "status"], env=env, capture_output=True, text=True, timeout=20)
    auth_text = (auth.stdout + auth.stderr).strip()
    if auth.returncode or "logged in using chatgpt" not in auth_text.lower():
        raise SystemExit("This spike requires an existing ChatGPT login; no API fallback is allowed")
    (HERE / "auth-status.txt").write_text(auth_text + "\n")
    cli_version = subprocess.check_output([codex, "--version"], env=env, text=True).strip()
    record = {"started_at_utc": datetime.now(timezone.utc).isoformat(), "cli_version": cli_version,
              "authentication": "chatgpt_saved_login", "api_credentials_removed_from_environment": True,
              "production_integration": False, "model_override": None,
              "reported_model": None, "model_note": "Use CLI default; record a model only if runtime reports it",
              "inputs_sha256": {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                                for name in ("prompt.txt", "sources.json", "output-schema.json")}}
    with tempfile.TemporaryDirectory(prefix="coursemate-codex-generation-") as scratch:
        args = [codex, "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                "--sandbox", "read-only", "-C", scratch, "--json", "--color", "never",
                "-c", 'forced_login_method="chatgpt"',
                "--disable", "shell_tool", "--disable", "multi_agent", "--disable", "apps",
                "--disable", "plugins", "--disable", "hooks", "--disable", "browser_use",
                "--disable", "computer_use", "--disable", "image_generation",
                "--disable", "unbounded_connection_retries",
                "--output-schema", str(HERE / "output-schema.json"),
                "--output-last-message", str(HERE / "result.json"), "-"]
        record["command"] = args
        started = time.perf_counter()
        with (HERE / "events.jsonl").open("x") as stdout, (HERE / "stderr.log").open("x") as stderr:
            try:
                result = subprocess.run(args, input=(HERE / "prompt.txt").read_text(), text=True,
                                        stdout=stdout, stderr=stderr, env=env, timeout=150)
                record["exit_code"] = result.returncode
            except subprocess.TimeoutExpired:
                record["exit_code"] = None
                record["blocker"] = "Generation exceeded the 150-second bound; no automatic retry"
        record["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    record["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    events = []
    for line in (HERE / "events.jsonl").read_text().splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    record["usage"] = next((e.get("usage") for e in reversed(events) if e.get("type") == "turn.completed"), None)
    record["status"] = "generated" if record["exit_code"] == 0 and (HERE / "result.json").exists() else "blocked"
    (HERE / "run.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: record[k] for k in ("status", "exit_code", "elapsed_seconds", "usage")}))
    return 0 if record["status"] == "generated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
