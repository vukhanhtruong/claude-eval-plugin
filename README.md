# Claude Eval Plugin

A Claude Code plugin for evaluating LLM applications: prompts, RAG pipelines, tool calls, and agents. Built for prompt engineers and AI builders who want a repeatable loop of "edit, eval, see scores, improve" instead of vibes-based iteration.

**No API key required** — Claude Code performs all LLM work natively.

## Installation

**Prerequisites:** [Node.js](https://nodejs.org/en/download) (for `npx`), [uv](https://docs.astral.sh/uv/) (skills invoke Python via `uvx`)

### User-level (personal use)

```bash
npx plugins add vukhanhtruong/claude-eval-plugin
```

Then restart Claude Code or run `/reload-plugins`.

### Project-level (scoped to one project)

```bash
npx plugins add vukhanhtruong/claude-eval-plugin
```

Plugin only loads when you're in that project directory. Teammates need to run the same command.

### Project-level (committed to git for team)

For sharing the plugin via your repo:

```bash
# Option 1: Clone directly
git clone https://github.com/vukhanhtruong/claude-eval-plugin.git .claude-plugins/prompt-eval

# Option 2: Git submodule (easier updates)
git submodule add https://github.com/vukhanhtruong/claude-eval-plugin.git .claude-plugins/prompt-eval
```

Then add to `.claude/settings.json`:

```json
{
  "plugins": [".claude-plugins/prompt-eval"]
}
```

Teammates just need to clone/pull - no extra install step.

## Available Skills

| Skill                                       | Description                                                                                                                                     | Status    |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| [prompt_eval](skills/prompt_eval/README.md) | Build, test, and improve a Claude prompt. 5 coaching steps, test dataset generation, Claude-as-judge grading, MkDocs site for results.          | Available |
| `rag_eval`                                  | Evaluate retrieval quality (recall, precision, MRR) and answer quality (faithfulness, context relevance, answer correctness) for RAG pipelines. | Planned   |
| `tool_eval`                                 | Evaluate tool selection accuracy, argument correctness, and multi-step tool-call trajectories.                                                  | Planned   |
| `agent_eval`                                | End-to-end agent evals — planning, multi-turn task completion, trajectory scoring, side-effect verification.                                    | Planned   |

## Quick Start

```bash
# Evaluate a prompt (auto-generates name from description)
/prompt-eval:prompt_eval summarize tech articles from hackernews

# Or specify a name explicitly
/prompt-eval:prompt_eval --prompt summarizer
```

See each skill's README for detailed usage.

## Plugin Structure

```
claude-eval-plugin/
├── .claude-plugin/
│   └── plugin.json         # plugin manifest
├── skills/
│   └── prompt_eval/        # prompt evaluation skill
│       ├── SKILL.md
│       ├── README.md       # detailed documentation
│       └── scripts/
└── agents/
    └── llm-judge.md        # GEval grading subagent
```

## Langfuse (optional)

Push eval scores to [Langfuse](https://langfuse.com) for team review and historical comparison.
Langfuse is purely additive — local artifacts are always written first; push failures never block the eval workflow.

**Setup:** Add to your project's `.env` (see `.env.example`):

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com   # or your self-hosted URL
```

**How it works:** After each `save-scores` run the skill checks for credentials and prompts you to push. You can also push retroactively:

```bash
uvx --from "${CLAUDE_SKILL_DIR}" prompt-eval push \
  --prompt summarizer \
  --run-id run_001            # pushes all scored versions
```

Each push creates a Langfuse dataset (idempotent), one span per case, and attaches a
`Task Quality` score (0.0–1.0, normalized from the 1–10 GEval score).

## Development

```bash
cd skills/prompt_eval
uv sync
uv run pytest              # 81 tests
```

## License

MIT License
