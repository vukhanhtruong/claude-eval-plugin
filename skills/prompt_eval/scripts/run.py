"""CLI entry point for /prompt_eval skill."""
import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from prompt_eval.docs_generator import _load_version_results, regenerate_for_run
from prompt_eval.data_helpers import DatasetHelper, MetadataHelper, OutputHelper, ResultsHelper


MKDOCS_PORT = 8000


def _resolve_artifact_root() -> Path:
    """Return `<project_dir>/prompt_eval_runs/`.

    Priority for `<project_dir>`:
    1. ``$PROMPT_EVAL_PROJECT_DIR`` (explicit override — always trusted)
    2. cwd, when prompt_eval_runs/ already exists there (checked before
       CLAUDE_PROJECT_DIR to prevent stale env var poisoning)
    3. ``$CLAUDE_PROJECT_DIR`` (fallback for fresh projects where prompt_eval_runs/
       hasn't been created yet)
    """
    explicit_project = os.environ.get("PROMPT_EVAL_PROJECT_DIR")
    if explicit_project:
        return Path(explicit_project) / "prompt_eval_runs"

    cwd = Path(os.getcwd())
    cwd_root = cwd / "prompt_eval_runs"
    if cwd_root.exists():
        return cwd_root

    claude_project = os.environ.get("CLAUDE_PROJECT_DIR")
    if claude_project:
        return Path(claude_project) / "prompt_eval_runs"

    raise FileNotFoundError(
        f"prompt_eval_runs/ not found in current directory ({cwd}).\n"
        f"Run this skill only in the project root where prompt_eval_runs/ exists, "
        f"or set $PROMPT_EVAL_PROJECT_DIR to override."
    )


_PROMPT_NAME_RE = re.compile(r"^[a-z0-9_-]+$")


def _validate_prompt_name(name: str) -> None:
    """Reject prompt names that aren't filesystem- and URL-safe.

    Allowed: lowercase letters, digits, underscore, hyphen. 1-64 chars.
    Restrictive on purpose so paths don't need escaping anywhere.
    """
    if not isinstance(name, str) or not (1 <= len(name) <= 64) or not _PROMPT_NAME_RE.match(name):
        raise ValueError(
            f"prompt name must match [a-z0-9_-]+ and be 1-64 chars; got {name!r}"
        )


def _resolve_prompts_dir() -> Path:
    """Return ``<artifact_root>/prompts/`` (the parent of all prompt namespaces)."""
    return _resolve_artifact_root() / "prompts"


def _resolve_runs_dir(prompt_name: str) -> Path:
    """Return ``<artifact_root>/prompts/<prompt_name>/runs/``. Validates name."""
    _validate_prompt_name(prompt_name)
    return _resolve_prompts_dir() / prompt_name / "runs"


def _migrate_legacy_layout(artifact_root: Path) -> bool:
    """Move legacy ``runs/`` and ``docs-site/docs/runs/`` into the new
    ``prompts/default/`` namespace. Returns True if anything moved.

    Only runs when ``runs/`` exists AND ``prompts/`` does not. Anything
    else is a no-op so we never clobber a partially-migrated tree.
    """
    artifact_root = Path(artifact_root)
    legacy_runs = artifact_root / "runs"
    new_prompts = artifact_root / "prompts"

    if not legacy_runs.exists() or new_prompts.exists():
        return False

    # 1. Move the runs/ directory under prompts/default/runs/
    target_runs = new_prompts / "default" / "runs"
    target_runs.parent.mkdir(parents=True, exist_ok=True)
    legacy_runs.rename(target_runs)

    # 2. Stamp prompt_name="default" into each run's metadata if missing
    for run_dir in target_runs.iterdir():
        if not run_dir.is_dir():
            continue
        meta_path = run_dir / "metadata.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        meta.setdefault("prompt_name", "default")
        meta_path.write_text(json.dumps(meta, indent=2))

    # 3. Move docs-site pages: docs/runs/ -> docs/prompts/default/runs/
    docs_runs = artifact_root / "docs-site" / "docs" / "runs"
    if docs_runs.exists():
        target_docs_runs = artifact_root / "docs-site" / "docs" / "prompts" / "default" / "runs"
        target_docs_runs.parent.mkdir(parents=True, exist_ok=True)
        docs_runs.rename(target_docs_runs)

    # 4. Rewrite mkdocs.yml nav: replace top-level "Runs" with nested
    #    "Prompts > default > <run_id>" structure
    cfg_path = artifact_root / "docs-site" / "mkdocs.yml"
    if cfg_path.exists():
        import yaml as _yaml  # local import to avoid widening top-of-file imports
        cfg = _yaml.safe_load(cfg_path.read_text())
        nav = cfg.get("nav", [])
        new_nav = []
        legacy_runs_entries = []
        for item in nav:
            if isinstance(item, dict) and "Runs" in item:
                legacy_runs_entries = item["Runs"]  # list of {run_id: [pages]}
            else:
                new_nav.append(item)
        if legacy_runs_entries:
            # Rewrite each page path: runs/<id>/X.md -> prompts/default/runs/<id>/X.md
            rewritten = []
            for run_dict in legacy_runs_entries:
                # run_dict looks like {"run_001": [{"Summary": "runs/run_001/index.md"}, ...]}
                for run_id, pages in run_dict.items():
                    new_pages = []
                    for page in pages:
                        for title, path in page.items():
                            new_pages.append({
                                title: path.replace(
                                    f"runs/{run_id}/",
                                    f"prompts/default/runs/{run_id}/",
                                    1,
                                ),
                            })
                    rewritten.append({run_id: new_pages})
            new_nav.append({"Prompts": [{"default": rewritten}]})
        cfg["nav"] = new_nav
        cfg_path.write_text(_yaml.safe_dump(cfg, sort_keys=False))

    print(f"Migrated legacy runs/ to prompts/default/")
    return True


def _bootstrap_docs_site(target: Path) -> None:
    """Copy the bundled docs-site template to `target` if `target/mkdocs.yml` doesn't exist.

    Runs once per project — first time the user evaluates a prompt. After that, the per-project
    docs-site is the source of truth (the user can theme it, add nav entries, etc.).
    """
    if (target / "mkdocs.yml").exists():
        return
    template_dir = Path(__file__).parent / "docs-site-template"
    target.mkdir(parents=True, exist_ok=True)
    # Copy contents (not the template_dir itself).
    for item in template_dir.iterdir():
        dest = target / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _kill_mkdocs() -> None:
    """Send SIGTERM to any 'mkdocs serve' processes. Best-effort.

    We use ``pgrep -f 'mkdocs serve'`` instead of port-based discovery so we
    only kill our own processes, not whatever else might be on port 8000.
    """
    try:
        out = subprocess.check_output(
            ["pgrep", "-f", "mkdocs serve"],
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return  # nothing to kill, or no pgrep on PATH

    for raw in out.decode().split():
        try:
            os.kill(int(raw), signal.SIGTERM)
        except (ProcessLookupError, ValueError):
            pass

    # Wait up to 2s for the OS to release the port
    for _ in range(20):
        if not _port_in_use(MKDOCS_PORT):
            return
        time.sleep(0.1)


def _start_mkdocs_background(docs_site_dir: Path) -> None:
    log_path = docs_site_dir / "mkdocs.log"
    subprocess.Popen(
        ["uv", "run", "mkdocs", "serve", "--dev-addr", f"127.0.0.1:{MKDOCS_PORT}"],
        cwd=docs_site_dir,
        stdout=open(log_path, "ab"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    print(f"mkdocs serve at http://127.0.0.1:{MKDOCS_PORT}  (log: {log_path})")


def restart_mkdocs(docs_site_dir: Path) -> None:
    """Stop any running ``mkdocs serve`` and start a fresh one.

    mkdocs serve's filesystem watcher silently misses files written to docs/
    after the server starts (mkdocs 1.6 + Material on Linux), so we restart
    it on every regeneration. Costs ~1 sec; cheap relative to the LLM calls
    that surround it.
    """
    if _port_in_use(MKDOCS_PORT):
        _kill_mkdocs()
    _start_mkdocs_background(docs_site_dir)


def list_runs(runs_dir: Path) -> None:
    runs_dir = Path(runs_dir)
    if not runs_dir.exists() or not any(runs_dir.iterdir()):
        print("No runs found.")
        return

    print("Available runs:")
    for run_path in sorted(runs_dir.iterdir()):
        if not run_path.is_dir():
            continue
        meta_file = run_path / "metadata.json"
        if not meta_file.exists():
            continue
        meta = json.loads(meta_file.read_text())
        versions = meta.get("versions", [])
        version_str = (
            f"{versions[0]}→{versions[-1]}" if len(versions) > 1 else
            (versions[0] if versions else "—")
        )
        avg = meta.get("latest_avg_score", 0)
        size = meta.get("dataset_size", "?")
        print(f"  {run_path.name}  {size} cases  {version_str}  avg {avg}")


def list_prompts(prompts_dir: Path) -> None:
    """Print each prompt namespace with its run count."""
    prompts_dir = Path(prompts_dir)
    if not prompts_dir.exists() or not any(prompts_dir.iterdir()):
        print("No prompts found.")
        return

    print("Available prompts:")
    for entry in sorted(prompts_dir.iterdir()):
        if not entry.is_dir():
            continue
        runs_dir = entry / "runs"
        if not runs_dir.exists():
            count = 0
        else:
            count = sum(
                1 for r in runs_dir.iterdir()
                if r.is_dir() and (r / "metadata.json").exists()
            )
        print(f"  {entry.name}  {count} runs")




def _do_show(out_dir: Path, version: str, json_output: bool = False) -> None:
    """Print a scoreboard for one (run, version). With --json, emit structured
    JSON for programmatic consumption (Claude can parse it without re-reading
    the underlying files itself)."""
    version_dir = out_dir / version
    output_file = version_dir / "output.json"
    scores_file = version_dir / "scores.json"
    if not output_file.exists() and not scores_file.exists():
        print(f"No results at {output_file}", file=sys.stderr)
        sys.exit(1)

    results = _load_version_results(version_dir)
    cases = []
    for r in results:
        sc = r["test_case"].get("scenario", "")
        scenario = sc.get("title", str(sc)) if isinstance(sc, dict) else str(sc)
        cases.append({
            "scenario": scenario,
            "score": r["score"],
            "output_length": len(r.get("output", "")),
            "reasoning": r["reasoning"],
        })

    scores = [c["score"] for c in cases]
    avg = round(sum(scores) / len(scores), 1) if scores else 0.0
    pass_rate = round(100 * len([s for s in scores if s >= 7]) / len(scores), 1) if scores else 0.0

    summary = {
        "run_id": out_dir.name,
        "version": version,
        "average_score": avg,
        "pass_rate": pass_rate,
        "cases": cases,
    }

    if json_output:
        print(json.dumps(summary, indent=2))
        return

    print(f"Run: {summary['run_id']}  Version: {version}")
    print(f"Average: {avg}/10  Pass rate: {pass_rate}%")
    print()
    for i, c in enumerate(cases, 1):
        print(f"=== Case {i}: {c['scenario']}")
        print(f"  Score: {c['score']}/10")
        print(f"  Output length: {c['output_length']} chars")
        print(f"  Reasoning: {c['reasoning']}")
        print()


def _do_save_output(
    prompt_name: str, run_id: str, version: str, json_data: str, model: str | None = None
) -> None:
    """Save output.json."""
    outputs = json.loads(json_data)
    root = _resolve_artifact_root()
    path = root / "prompts" / prompt_name / "runs" / run_id / version / "output.json"
    OutputHelper.save(outputs, path, model=model)
    print(f"Saved outputs to {path}")


def _do_save_dataset(prompt_name: str, run_id: str, json_data: str) -> None:
    """Validate and save dataset.json."""
    dataset = json.loads(json_data)
    root = _resolve_artifact_root()
    path = root / "prompts" / prompt_name / "runs" / run_id / "dataset.json"
    DatasetHelper.save(dataset, path)
    print(f"Saved dataset to {path}")


def _next_run_id(runs_dir: Path) -> str:
    """Return the next free run_NNN id, scanning existing dirs."""
    existing = {
        d.name for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith("run_")
    }
    n = 1
    while f"run_{n:03d}" in existing:
        n += 1
    return f"run_{n:03d}"


def _update_metadata(run_dir: Path, version: str, run_id: str) -> None:
    """Ensure metadata.json exists in run_dir and the version is registered."""
    meta_path = run_dir / "metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
    else:
        meta = {"run_id": run_id, "versions": []}
    versions = meta.setdefault("versions", [])
    if version not in versions:
        versions.append(version)
    meta_path.write_text(json.dumps(meta, indent=2))


def _refresh_docs(prompt_name: str, run_id: str) -> None:
    """Bootstrap docs-site, regenerate this run's pages, restart mkdocs."""
    root = _resolve_artifact_root()
    run_dir = root / "prompts" / prompt_name / "runs" / run_id
    docs_site = root / "docs-site"
    _bootstrap_docs_site(docs_site)
    regenerate_for_run(
        run_dir=run_dir,
        docs_root=docs_site / "docs",
        mkdocs_yml=docs_site / "mkdocs.yml",
        prompt_name=prompt_name,
    )
    restart_mkdocs(docs_site)


def _do_save_scores(
    prompt_name: str, run_id: str, version: str, json_data: str, model: str | None = None
) -> None:
    """Validate scores, save scores.json, update metadata, regenerate docs,
    restart the mkdocs server."""
    scores = json.loads(json_data)
    root = _resolve_artifact_root()
    run_dir = root / "prompts" / prompt_name / "runs" / run_id
    path = run_dir / version / "scores.json"
    ResultsHelper.save(scores, version, path, model=model)
    print(f"Saved scores to {path}")
    _update_metadata(run_dir, version, run_id)
    _refresh_docs(prompt_name, run_id)


def _do_set_models(
    prompt_name: str, run_id: str, test_model: str, judge_model: str
) -> None:
    root = _resolve_artifact_root()
    run_dir = root / "prompts" / prompt_name / "runs" / run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run_dir}")
    MetadataHelper.set_models(run_dir, test_model, judge_model)
    print(f"Locked models for {prompt_name}/{run_id}: test={test_model}, judge={judge_model}")


def _do_clone_for_crossval(
    prompt_name: str,
    from_run_id: str,
    from_version: str,
    test_model: str,
    judge_model: str,
) -> None:
    root = _resolve_artifact_root()
    runs_dir = root / "prompts" / prompt_name / "runs"
    src_run = runs_dir / from_run_id
    src_prompt = src_run / from_version / "prompt.txt"
    src_dataset = src_run / "dataset.json"
    if not src_prompt.exists():
        raise FileNotFoundError(f"Source prompt.txt not found: {src_prompt}")
    if not src_dataset.exists():
        raise FileNotFoundError(f"Source dataset.json not found: {src_dataset}")
    new_run_id = _next_run_id(runs_dir)
    new_run = runs_dir / new_run_id
    (new_run / "v1").mkdir(parents=True)
    shutil.copy2(src_dataset, new_run / "dataset.json")
    shutil.copy2(src_prompt, new_run / "v1" / "prompt.txt")
    MetadataHelper.write(new_run, {"run_id": new_run_id, "versions": ["v1"]})
    MetadataHelper.set_models(new_run, test_model, judge_model)
    MetadataHelper.set_cross_validation_link(new_run, from_run_id, from_version)
    _refresh_docs(prompt_name, from_run_id)
    _refresh_docs(prompt_name, new_run_id)
    print(
        f"Cloned {prompt_name}/{from_run_id}/{from_version} → "
        f"{prompt_name}/{new_run_id} (test={test_model}, judge={judge_model})"
    )


def _do_langfuse_status() -> int:
    from prompt_eval import langfuse_push  # lazy import keeps startup fast
    if langfuse_push.is_configured():
        print("configured")
        return 0
    missing = langfuse_push.missing_env_vars()
    print(f"not configured: missing {', '.join(missing)}", file=sys.stderr)
    return 1


def _add_json_payload_args(parser: argparse.ArgumentParser) -> None:
    """Add a mutually-exclusive (--json | --json-file) payload group.

    --json takes raw JSON text. --json-file takes a path whose contents are JSON.
    The file path is preferred when payloads contain shell-hostile characters
    (apostrophes, $, backticks); the skill writes payloads via the Write tool
    and passes the path here to skip shell quoting entirely.
    """
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--json", dest="json_data", help="raw JSON payload")
    group.add_argument(
        "--json-file", dest="json_file",
        help="path to a file whose contents are the JSON payload",
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="prompt-eval")
    sub = p.add_subparsers(dest="cmd", required=True)

    lr = sub.add_parser("list-runs", help="List existing runs for one prompt")
    lr.add_argument("--prompt", required=True, help="prompt name, e.g. summarizer")

    sub.add_parser("list-prompts", help="List all prompt namespaces with run counts")

    s = sub.add_parser("show", help="Print scoreboard for one (run, version)")
    s.add_argument("--run-id", required=True, help="e.g. run_001")
    s.add_argument("--version", required=True, help="e.g. v1, v2")
    s.add_argument("--json", action="store_true", help="Emit structured JSON")
    s.add_argument("--prompt", required=True, help="prompt name, e.g. summarizer")

    sub.add_parser("stop-server", help="Stop the mkdocs serve process")

    sub.add_parser("langfuse-status", help="Check if Langfuse credentials are configured")

    save_dataset_parser = sub.add_parser("save-dataset", help="Save dataset.json")
    save_dataset_parser.add_argument("--prompt", required=True)
    save_dataset_parser.add_argument("--run-id", required=True)
    _add_json_payload_args(save_dataset_parser)

    save_output_parser = sub.add_parser("save-output", help="Save output.json")
    save_output_parser.add_argument("--prompt", required=True)
    save_output_parser.add_argument("--run-id", required=True)
    save_output_parser.add_argument("--version", required=True)
    _add_json_payload_args(save_output_parser)
    save_output_parser.add_argument("--model", required=False, default=None)

    save_scores_parser = sub.add_parser("save-scores", help="Save scores.json")
    save_scores_parser.add_argument("--prompt", required=True)
    save_scores_parser.add_argument("--run-id", required=True)
    save_scores_parser.add_argument("--version", required=True)
    _add_json_payload_args(save_scores_parser)
    save_scores_parser.add_argument("--model", required=False, default=None)

    set_models_parser = sub.add_parser(
        "set-models", help="Lock test_model and judge_model into metadata.json"
    )
    set_models_parser.add_argument("--prompt", required=True)
    set_models_parser.add_argument("--run-id", required=True)
    set_models_parser.add_argument("--test-model", required=True)
    set_models_parser.add_argument("--judge-model", required=True)

    clone_parser = sub.add_parser(
        "clone-for-crossval",
        help="Create a sibling run with the same dataset/prompt but new models",
    )
    clone_parser.add_argument("--prompt", required=True)
    clone_parser.add_argument("--from-run-id", required=True)
    clone_parser.add_argument("--from-version", required=True)
    clone_parser.add_argument("--test-model", required=True)
    clone_parser.add_argument("--judge-model", required=True)

    return p


def main(argv: list | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "stop-server":
        _kill_mkdocs()
        print("mkdocs server stopped.")
        return 0

    if args.cmd == "langfuse-status":
        return _do_langfuse_status()

    # Handle read-only commands gracefully on fresh projects (no prompt_eval_runs/ yet)
    if args.cmd in ("list-prompts", "list-runs"):
        try:
            artifact_root = _resolve_artifact_root()
            _migrate_legacy_layout(artifact_root)
        except FileNotFoundError:
            print("No prompts found." if args.cmd == "list-prompts" else "No runs found.")
            return 0
        if args.cmd == "list-prompts":
            list_prompts(_resolve_prompts_dir())
        else:
            list_runs(_resolve_runs_dir(args.prompt))
        return 0

    artifact_root = _resolve_artifact_root()
    _migrate_legacy_layout(artifact_root)
    if getattr(args, "json_file", None):
        try:
            args.json_data = Path(args.json_file).read_text()
        except OSError as e:
            print(f"Error: cannot read --json-file {args.json_file}: {e}", file=sys.stderr)
            return 2
    if args.cmd == "show":
        runs_dir = _resolve_runs_dir(args.prompt)
        out_dir = runs_dir / args.run_id
        _do_show(out_dir, args.version, json_output=args.json)
        return 0
    if args.cmd == "save-dataset":
        _do_save_dataset(args.prompt, args.run_id, args.json_data)
        return 0
    if args.cmd == "save-output":
        _do_save_output(
            args.prompt, args.run_id, args.version, args.json_data, args.model
        )
        return 0
    if args.cmd == "save-scores":
        _do_save_scores(
            args.prompt, args.run_id, args.version, args.json_data, args.model
        )
        return 0
    if args.cmd == "set-models":
        _do_set_models(args.prompt, args.run_id, args.test_model, args.judge_model)
        return 0
    if args.cmd == "clone-for-crossval":
        _do_clone_for_crossval(
            args.prompt,
            args.from_run_id,
            args.from_version,
            args.test_model,
            args.judge_model,
        )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
