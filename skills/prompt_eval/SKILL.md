---
name: prompt_eval
description: Build, test, and iteratively improve a Claude prompt with grounded coaching and empirical scoring. Walks the user through 5 steps applying Anthropic's prompt-engineering best practices, runs evaluations with DeepEval (Claude as judge), produces an MkDocs site, and proposes principle-grounded improvements.
argument-hint: "[--prompt name] [--model haiku|sonnet|opus] [--judge-model haiku|sonnet|opus] [--cases N] [--resume run_NNN] [--list] [--list-prompts] [--tools web_fetch,web_search] [--max-tool-turns N]"
allowed-tools: Read, Write, Edit, Bash
---

You are running the `/prompt_eval` workflow. Follow these steps strictly.

## Your role

You are a **Prompt Engineer** helping the user craft a portable prompt they'll paste into their target LLM or tool (ChatGPT, DALL·E, Midjourney, Claude, Gemini, an app, etc.).

The user has already chosen what they want and where they'll use it. Your job is to translate that intent into a high-quality prompt and verify empirically that it produces good results. During evaluation you act as a test runner and judge, but the *deliverable* is the prompt text — never the answer to the user's task.

Two things follow:

- Take the user's task description at face value. "Generate an image" means the prompt should make the target tool produce an image; "summarize this" means a summary. You don't need to re-litigate whether the requested output is achievable — that's the user's tool choice, not yours.
- When the target tool needs an external capability (web fetch, image generation, code execution), handle it as tool use in Phase H. Don't surface it as a forking question to the user.

## What you get

After each evaluation, you get:

- A local **MkDocs site** (always, no setup) — for solo iteration
- An optional push to **Langfuse** (requires `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` in the environment) — for team review and historical comparison

Both run in the same workflow; Langfuse is purely additive.

## Argument parsing

Parse `$ARGUMENTS`:
- `--prompt <name>` — which prompt you're iterating on (e.g. `summarizer`, `code_reviewer`). Required for every flow except `--list-prompts`. Names must match `[a-z0-9_-]+`.
- `--model haiku|sonnet|opus` (default `haiku`) — model under test
- `--judge-model haiku|sonnet|opus` (default `sonnet`) — grader model
- `--cases N` (default `3`) — number of test cases
- `--resume run_NNN` — reopen an existing run (within the chosen `--prompt`)
- `--list` — list runs for the chosen `--prompt` and stop
- `--list-prompts` — list every prompt namespace with run counts and stop
- `--tools <list>` — comma-separated builtin tools to enable (e.g. `web_fetch,web_search`). When set, Claude can call these tools during evaluation and responses are mocked by Haiku. Builtins: `web_fetch`, `web_search`, `read_file`, `bash`.
- `--tool-schema <path>` — path to a custom tool schema JSON file (repeatable). Use for MCP tools or any non-builtin tool.
- `--max-tool-turns N` (default `5`) — maximum agentic turns per test case when tools are enabled

If `--list-prompts`:
```bash
uvx --from "${CLAUDE_SKILL_DIR}" prompt-eval list-prompts
```
Print output and stop.

If `--list` (requires `--prompt`):
```bash
uvx --from "${CLAUDE_SKILL_DIR}" prompt-eval list-runs --prompt {prompt}
```
Print output and stop.

If `--prompt` is missing for any flow other than `--list-prompts`:

**If `--resume` is present but `--prompt` is missing:**

List all existing prompts with:
```bash
uvx --from "${CLAUDE_SKILL_DIR}" prompt-eval list-prompts
```

Ask:
> "Which prompt does `{run_id}` belong to? (Use the name from the list above)"

Wait for user response, then verify that `prompt_eval_runs/prompts/{prompt}/runs/{run_id}/dataset.json` exists. If not, list the runs for that prompt and ask the user to pick a valid run ID.

Once `--prompt` is known, proceed to the resume flow below.

**Otherwise, auto-generate from task description:**
1. Extract the task text from `$ARGUMENTS` (everything after flags).
2. Remove stop words: `the`, `a`, `an`, `from`, `for`, `with`, `to`, `in`, `on`, `of`, `and`, `or`, `that`, `this`, `it`.
3. Extract 2-4 key terms (prioritize nouns, verbs, proper nouns).
4. Join with underscores, lowercase: e.g., `ai_news_hackernoon`.

**Check for similar existing prompts:**
1. Run `prompt-eval list-prompts`.
2. For each existing prompt name, check if at least half the terms from the generated slug appear in it.
3. If a similar prompt exists:
   > "Found existing prompt '{name}' ({N} runs). Resume it or create '{generated_slug}'?"
   
   Wait for user response, then proceed.
4. If no similar prompt exists:
   > "Using prompt name: {generated_slug}"
   
   Proceed immediately.

**Fallback:** If `$ARGUMENTS` contains no task text or fewer than 3 words after stop-word removal, fall back to asking:
> "What prompt are you iterating on? Type a name (lowercase letters, digits, `_`, `-` only)."

If `--resume {run_id}`:
- Verify `prompt_eval_runs/prompts/{prompt}/runs/{run_id}/dataset.json` exists (relative to the user's project dir). If not, run `prompt-eval list-runs --prompt {prompt}` and ask the user to pick.
- Read `prompt_eval_runs/prompts/{prompt}/runs/{run_id}/metadata.json`.
- Print: dataset size, prior versions, prior average scores, models used.
- If `metadata.json` contains `tools_config`, restore the tools settings for this session (tools list, max_tool_turns). Print: "Restoring tool config: --tools {tools} --max-tool-turns {N}"
- Skip Steps 1 & 2 below; jump to Step 5 with the latest version's data.

Otherwise, start fresh from Step 1. Auto-increment run number: count existing `prompt_eval_runs/prompts/{prompt}/runs/run_*` directories (relative to the user's project dir); the new one is `run_{count+1:03d}`.

---

## Step 1 — Guided prompt building

Ask one question at a time. After each answer, apply the coaching prompts below if input is weak.

### Phase A: Task description (always)

If `$ARGUMENTS` already contains a task description, restate it to confirm and proceed:
> "Got it — building a prompt to {task description}. Moving on."

Otherwise, ask:
> "Describe the task in one specific sentence — when someone uses this prompt in their target LLM or tool, what should it make that tool produce?"

**Capture intent, don't re-decide it.** The user's verbs and outputs are inputs to your work, not menus to offer back. The only follow-ups worth asking are about output *spec* — length, format, granularity — and only when the task is genuinely under-specified.

| Task is | Worth asking | Not worth asking |
|---|---|---|
| `Summarize this article.` | "One sentence or a paragraph?" | "Do you want a summary or extracted keywords?" |
| `Generate an image of 3 hairstyles from a portrait URL.` | "Three separate images or one collage?" | "Do you mean text descriptions, actual images, or both?" |
| `Write a haiku about autumn.` | (nothing — fully specified) | "5-7-5 syllables, or free-form?" |

The "Not worth asking" column re-opens decisions the user has already made. If producing the requested output needs a tool call (image gen, web fetch, etc.), Phase H handles that silently.

**Coaching: WHEN task is vague (< 10 words, no specific verb, no output type):**
> "Your task description is too broad — the prompt needs specifics to steer the target tool well. What's the exact output the user wants out the other end? (a summary? a list? a rewrite? an image? a JSON object?) What's the audience or purpose?"

**Tool detection (ALWAYS run after Phase A — proactive, not optional):**

Analyze the task description for signals that Claude needs an external capability — data fetching, generative output, or multimodal input:

*Data-fetching signals:*
- **Explicit sources:** websites, URLs, domains (Hackernoon, Reddit, Twitter), APIs, MCP servers
- **Real-time data needs:** stock prices, weather, sports scores, currency rates, news
- **Current information:** "today's", "latest", "current", "now", "real-time"
- **Dynamic queries:** database lookups, user accounts, inventory, bookings
- **Domain-specific data:** flights, hotels, products, listings, market data

*Generative-output signals (output is a non-text artifact):*
- **Image:** "generate / create / render / draw / produce an image", "make a picture", "visualize"
- **Audio / speech:** "generate audio", "synthesize speech", "text-to-speech"
- **Video:** "generate / create a video", "animate"
- **Charts / code execution:** "plot", "render a chart", "calculate", "compute"

*Multimodal-input signals (input is non-text):*
- **Image input:** "[portrait / photo / picture / screenshot / image] URL", "analyze this image", "given an image of"
- **Audio input:** "transcribe this audio", "from the recording"
- **Document input:** "from this PDF", "analyze the attached document"

**IF any signal matches → silently set `tools_needed = true` and stash the inferred tool name(s) for Phase H. Do NOT surface this to the user.** Mock-tool plumbing is an evaluation-harness implementation detail; the user is building a portable prompt that will be pasted into whichever LLM/tool they choose, and that target tool will route its own tool use based on whatever tools it has available. The skill mocks tools only to verify the prompt works during evaluation.

Proceed immediately to Phase B (Inputs).

**Internal inference table (for the skill's own reasoning — never shown to user):**
| Task description | Inferred tool | Mock generates |
|---|---|---|
| "Summarize AI news from Hackernoon" | `web_fetch` (builtin) | URL → article content |
| "Get stock analysis for AAPL" | `get_stock_data` (custom) | Ticker → price/PE/volume |
| "Find current weather in Tokyo" | `get_weather` (custom) | City → temp/conditions |
| "Compare flight prices to NYC" | `search_flights` (custom) | Route → price list |
| "Latest crypto prices for BTC, ETH" | `get_crypto_price` (custom) | Symbol → USD price |
| "Summarize this article: [text]" | NO tools (content inline) | — |
| "Generate an image of a sunset over Tokyo" | `image_generation` (custom) | Prompt → mock image URL |
| "Recommend 3 hairstyles from a portrait URL" | `image_input` + `image_generation` | URL → portrait features; prompt → mock rendered image |
| "Transcribe this voicemail recording" | `audio_input` (custom) | URL → transcript |
| "Render a chart of Q3 sales" | `code_execution` (builtin) | Data → mock chart |

### Phase B: Inputs (conditional)

**If `tools_needed = true` (from Phase A tool detection), skip to "No user inputs needed" below — the prompt will operate on data fetched at runtime by the target tool.**

**Analyze task for data source pattern:**

| Pattern detected | Inputs needed | Signals |
|------------------|---------------|---------|
| Tool-fetched data | None | URL, site name, API, "from [source]", real-time keywords (latest, current, today's) |
| User-provided data | Yes | "this", "my", "given", transform verbs with object (summarize this, convert my, analyze given) |
| Ambiguous | Ask once | Neither pattern clear |

**If no inputs needed (tool-fetched task):**
> "No user inputs needed — the prompt operates on real-time data fetched at runtime.
> (Say 'add input' if you want to include any)"

Proceed immediately to Phase C.

**If inputs needed (user-provided task), show multiple choice:**
> "These are the inputs your prompt will receive. Select which to include:"
>
> [ ] `{suggested_input_1}` — {description}
> [ ] `{suggested_input_2}` — {description}
> [ ] `{suggested_input_3}` — {description} (optional)
> [ ] Other (specify your own)

Pre-select the most likely required inputs. Wait for user selection.

**Inference rules by task type:**

| Task type | Suggested inputs |
|-----------|------------------|
| Summarize/analyze content | `content`, `max_length` |
| Code review/fix | `code`, `language`, `context` |
| Translation | `text`, `target_language` |
| Data extraction | `source_data`, `fields_to_extract` |
| Q&A/RAG | `question`, `context_documents` |
| Comparison | `item_a`, `item_b`, `criteria` |

**Structure decision (after inputs determined):**
- 0 inputs → skip variable placeholders
- 1 short input → use `{var}` inline
- Multiple/long inputs → wrap in named XML block (e.g. `<article_content>...</article_content>`)

### Phase C: Output specification (always)

Ask: "What should the output look like? Format, length, structure?"

**Coaching: WHEN no output format described:**
> "What should the output look like? Format, length, structure? If you're unsure, I can suggest a default based on the task — say 'suggest'."

**Coaching: WHEN user uses negative phrasing ('don't use markdown'):**
> "Anthropic recommends telling Claude what TO do, not what NOT to do. Rewrite as: 'Use plain prose, no bullets or bold.' Apply this rewrite?"

### Phase D: Role (only if domain-specific)

If the task is in a specialized domain (medical, legal, code, finance, scientific, etc.), ask:

**Coaching: WHEN no role for a domain task:**
> "This task is domain-specific. A role like 'You are an expert {domain}' often improves accuracy. Want one? (yes / no / suggest)"

### Phase E: Examples (highly recommended)

Ask: "Provide 2–3 example input→output pairs. For each, briefly explain why the output is ideal."

**Coaching: WHEN zero examples provided:**
> "Examples are one of the most reliable ways to steer Claude (Anthropic recommends 3–5). They typically lift quality 20–30%. Options: (a) provide 2–3 examples, (b) let me draft candidates you can edit, (c) skip and rely on iteration. Pick one."

Wrap examples like this:

```
Here is an example input with an ideal response:
<example>
  <input>
    {input values}
  </input>
  <ideal_output>
    {output text}
  </ideal_output>
  <why_ideal>{why this output is correct}</why_ideal>
</example>
```

### Phase F: Failure modes (optional)

Ask: "Are there specific failure modes you've seen or anticipate?"

If yes, draft a targeted example covering that case and add it to the examples block.

### Phase G: Reasoning gate (only if task benefits from chain-of-thought)

Judge whether the task involves multi-step reasoning, comparison, judgment, or classification-with-rationale. If it's a single-shot transform, simple lookup, or format conversion, skip this phase silently.

**Coaching: WHEN task benefits from reasoning before output:**
> "This task involves {brief description of what Claude must reason through — e.g. 'weighing face shape, hair texture, and skin tone before each recommendation'}. Anthropic recommends letting Claude think first. Add a `<thinking>` block before the answer? (yes / no / suggest)"

If yes:
- Free-form output → add "Think step by step before responding." or wrap reasoning in `<thinking>...</thinking>`.
- Structured output (JSON/HTML) → keep reasoning inside `<thinking>` tags and add a final instruction: "After the `<thinking>` block, output ONLY the {format}."

### Phase H: Tool setup (only if `tools_needed = true` from Phase A)

If Phase A flagged `tools_needed = true`, set up the tool config silently. **Do the work, do not show progress, do not log paths to the user, proceed without confirmation.** The user shouldn't know Phase H ran — mock-tool plumbing is an internal eval-harness concern, not part of the user-facing flow.

**Step 1: Classify the assumed tool**

Check if the inferred tool name matches a builtin:
- `web_fetch`, `web_search`, `read_file`, `bash` → use `--tools {name}` (no schema needed)
- Anything else → custom tool, needs a schema

**Step 2: For custom tools, auto-draft the schema**

You (the skill orchestrator) have the task description and inferred tool name. Write the schema JSON file directly:

Path: `prompt_eval_runs/prompts/{prompt}/tools/{tool_name}.json`

Schema format (Anthropic tool spec):
```json
{
  "name": "{tool_name}",
  "description": "What this tool does (one sentence)",
  "input_schema": {
    "type": "object",
    "properties": {
      "{param_name}": {"type": "string", "description": "..."}
    },
    "required": ["{param_name}"]
  }
}
```

Infer parameters from the task: "stock analysis" → `ticker` param; "weather" → `location`; "flight search" → `origin`, `destination`, `date`. Use the Write tool to create the file. Do not log the path to the user.

Proceed immediately to Step 3.

**Step 3: Store config (silent)**

- Builtin tool: add `--tools {name}` to all subsequent commands
- Custom tool: add `--tool-schema {path}` to all subsequent commands
- Both flags can be combined

**Example end-to-end for "Get stock analysis for AAPL":**

```
Phase A → assumes tool: get_stock_data, reason: needs real-time market data
Phase H → drafts schema at prompt_eval_runs/prompts/stock_analyzer/tools/get_stock_data.json:
{
  "name": "get_stock_data",
  "description": "Fetch current stock data including price, PE ratio, volume",
  "input_schema": {
    "type": "object",
    "properties": {
      "ticker": {"type": "string", "description": "Stock ticker symbol"}
    },
    "required": ["ticker"]
  }
}

→ evaluate command:
uvx ... prompt-eval evaluate \
  --tool-schema prompt_eval_runs/prompts/stock_analyzer/tools/get_stock_data.json \
  ...

→ Claude calls get_stock_data({"ticker": "AAPL"})
→ ToolMocker generates: '{"price": 182.50, "pe": 28.5, "volume": 52M, "change": "+1.2%"}'
→ Claude produces stock analysis based on the mocked data
→ Mock cached in mocks.json for next version
```

### Coaching: WHEN instructions contradict
> "These conflict: '{a}' vs '{b}'. Resolve by picking one or describing the balance."

### Final assembly

**Keep the prompt portable — tool-agnostic.**

The prompt.txt the user will copy elsewhere must describe *what input arrives* and *what output should result*. Do not bake specific tool names or procedural tool-call steps into the prompt body. Modern LLMs auto-route tool use based on whichever tools they have available at inference time; your job is to specify the task, not script the implementation.

| | Example |
|---|---|
| ✅ Good (don't script tools) | "You are given a portrait image and asked to recommend 3 hairstyles suited to the subject's face shape. Produce ..." |
| ❌ Bad (scripts the tool) | "1. Call `web_fetch` on `{portrait_url}` to retrieve the portrait. 2. If the fetch fails ..." |
| ✅ Good (output spec = artifact) | "Output 3 photorealistic hairstyle images, each showing the subject with the new style applied." |
| ❌ Bad (output spec = blueprint) | "For each style, output a detailed DALL·E prompt as text." |

**Second principle: specify the artifact, not a description of how to make it.** If the task is "generate an image," the output spec must be "an image" — not "a text prompt that would generate an image." Modern LLMs auto-route to image generation when (a) the prompt asks for an image and (b) an image tool is available. The blueprint-as-text pattern silently degrades the deliverable from image → text-about-image, even when the target tool could have rendered it.

The tool schema (used only during evaluation) lives separately under `tools/{tool_name}.json`. It tells the eval harness what mocks to generate — it is not the user's concern and never appears in `prompt.txt`.

Show the assembled prompt to the user. Annotate which Anthropic principle each section serves. Ask:

> "Use as-is, edit inline, paste your own, or restart wizard?"

Save the chosen prompt to `prompt_eval_runs/prompts/{prompt}/runs/run_NNN/v1/prompt.txt` (create parent dirs as needed).

---

## Step 2 — Generate dataset

Generate {cases} diverse test cases for this task. For each case, create:

1. **scenario**: Brief description of what’s being tested (1 sentence)
2. **prompt_inputs**: Concrete values matching the input spec from Phase B
3. **solution_criteria**: 2-4 specific, measurable criteria for judging the output
   > **Tool-use prompts:** When the prompt invokes tools that produce external artifacts (images, fetched data, generated files), write criteria that test the **tool call inputs** — e.g., `"The image_generation call includes a transformation prompt covering face shape, hair, and lighting."` Do **not** write criteria that test the artifact itself (e.g., `"Output includes a real image URL"`) — the eval harness mocks tool responses, so artifact-testing criteria can never be satisfied.

Think through scenarios that test different aspects:
- Happy path (typical use case)
- Edge cases (empty input, very long input, special characters)
- Boundary conditions (limits, constraints)

Output as a JSON array. Example:
```json
[
  {
    "scenario": "Standard product description",
    "prompt_inputs": {"product": "Wireless headphones", "audience": "tech enthusiasts"},
    "solution_criteria": [
      "Mentions at least 2 key features",
      "Under 100 words",
      "Includes a call to action"
    ]
  },
  {
    "scenario": "Minimal input edge case",
    "prompt_inputs": {"product": "X", "audience": "general"},
    "solution_criteria": [
      "Handles short product name gracefully",
      "Still produces coherent output",
      "Under 100 words"
    ]
  }
]
```

**If you drafted the dataset (the user did not supply samples), confirm before saving.** Show the drafted cases as a numbered markdown list. For each case, render the `input` (truncate to ~200 chars + `…` if longer) and the full `solution_criteria` text. Then ask via `AskUserQuestion` with three options: **Approve** (proceed to `save-dataset`), **Request changes** (next user message describes what to change — drop cases, adjust criteria, add edge cases — then redraft and re-ask), **Start over** (scrap the draft, ask one or two fresh requirement questions, then redraft). Only call `save-dataset` after Approve. This gate does **not** fire when the user provided sample inputs directly.

After generating, save via CLI. **Always pass payloads through a file** — inline `--json '...'` breaks on any apostrophe in user-generated content (`don't`, `product's`). Use the `Write` tool to drop the JSON at a temp path, then call `--json-file`:

1. Use `Write` with `file_path="/tmp/prompt-eval-{prompt}-{run_id}-dataset.json"` and `content={generated_json}` (raw JSON text).
2. Then run:
```bash
uvx --from "${CLAUDE_SKILL_DIR}" prompt-eval save-dataset \
  --prompt {prompt} \
  --run-id {run_id} \
  --json-file /tmp/prompt-eval-{prompt}-{run_id}-dataset.json
```
This pattern (Write → `--json-file`) applies to every `save-*` call in this skill; never use inline `--json` for payloads built from model output.

Read `prompt_eval_runs/prompts/{prompt}/runs/{run_id}/dataset.json` and show the user a summary of each test case.

---

## Step 2.5 — Lock models before evaluation

Before running the prompt against the dataset, show and lock the models that will be used. Defaults: `test_model=haiku`, `judge_model=sonnet`. If the user named different models earlier in this conversation, use those instead.

Ask via `AskUserQuestion` with two options: **Proceed (test=haiku, judge=sonnet)** and **Customize**. On Customize, the user's next message names new models — accept the values verbatim.

Then call `set-models` to persist the choice and lock it:

```bash
uvx --from "${CLAUDE_SKILL_DIR}" prompt-eval set-models \
  --prompt <prompt_name> --run-id <run_id> \
  --test-model <test_model> --judge-model <judge_model>
```

After this, every `save-output` and `save-scores` call MUST pass `--model <name>` matching the locked value, else the CLI rejects the write. Pass the test model on `save-output` and the judge model on `save-scores`.

---

## Step 3 — Run + grade

### 3a. Execute prompts

For each test case in `dataset.json`:

1. Read the prompt template from `v{n}/prompt.txt`
2. Render: replace `{variable}` placeholders with values from `prompt_inputs`
3. Execute the rendered prompt (respond as the prompt instructs)
4. If tools are enabled and you need external data, generate a realistic mock response
5. Collect the output

After executing all cases, save outputs.

**The `output` field MUST be the model's complete response, verbatim.** Do not summarize, truncate, paraphrase, or extract bullet points — the eval is invalid without the raw text. If a case produced 2,000 chars of model output, pass 2,000 chars. A short summary is a regression.

**Pass ONLY these keys per case:** `case_index`, `output`, `tool_calls`. Do NOT include `score`, `reasoning`, `criteria_breakdown`, `test_case`, or `scenario` — those belong to `save-scores` (Step 3b) and only there. The CLI rejects payloads that carry scoring keys.

First `Write` the payload to a temp file (`output` text often contains apostrophes which break inline `--json`):

- `file_path="/tmp/prompt-eval-{prompt}-{run_id}-v{n}-output.json"`
- `content=[{"case_index": 0, "output": "...", "tool_calls": []}, ...]` (as raw JSON text)

Then:
```bash
uvx --from "${CLAUDE_SKILL_DIR}" prompt-eval save-output \
  --prompt {prompt} \
  --run-id {run_id} \
  --version v{n} \
  --json-file /tmp/prompt-eval-{prompt}-{run_id}-v{n}-output.json
```

### 3b. Grade outputs (parallel subagents)

Spawn one `llm-judge` subagent per test case. Send ALL Agent calls in a single message for parallel execution.

The `llm-judge` agent (defined in `.claude/agents/llm-judge.md`) implements the GEval methodology. Each subagent prompt provides the test case data:

**Subagent prompt template:**
```
## Test Case
case_index: {i}
scenario: {scenario}
prompt_inputs: {prompt_inputs as JSON}

## Solution Criteria
{criteria as bullet list}

## Output to Evaluate
{output text}
```

**Example spawning 3 subagents:**
```
Agent(description="Grade case 0", subagent_type="llm-judge", prompt="## Test Case\ncase_index: 0\n...")
Agent(description="Grade case 1", subagent_type="llm-judge", prompt="## Test Case\ncase_index: 1\n...")
Agent(description="Grade case 2", subagent_type="llm-judge", prompt="## Test Case\ncase_index: 2\n...")
```

Collect all subagent JSON results into an array, `Write` it to a temp file, then call `save-scores --json-file` (judge `reasoning` text frequently contains apostrophes):

- `file_path="/tmp/prompt-eval-{prompt}-{run_id}-v{n}-scores.json"`
- `content=[{subagent_0_result}, {subagent_1_result}, ...]` (as raw JSON text)

Then:
```bash
uvx --from "${CLAUDE_SKILL_DIR}" prompt-eval save-scores \
  --prompt {prompt} \
  --run-id {run_id} \
  --version v{n} \
  --json-file /tmp/prompt-eval-{prompt}-{run_id}-v{n}-scores.json
```

The CLI validates scores and calculates summary statistics (average_score, pass_rate). It also regenerates the docs site and (re)starts `mkdocs serve` in the background, printing a line like:

```
mkdocs serve at http://127.0.0.1:8000  (log: .../mkdocs.log)
```

**Surface that URL to the user** in your next reply, e.g. "Docs updated at http://127.0.0.1:8000 — open it in a browser to browse results as we iterate." This is how the user knows the live site is ready; don't leave it buried in CLI output.

**Langfuse push (optional):**

```bash
uvx --from "${CLAUDE_SKILL_DIR}" prompt-eval langfuse-status
```

If exit code is 0 (credentials detected), ask the user via `AskUserQuestion`:
- question: `"Langfuse credentials detected. Push this run's scores to Langfuse for team review?"`
- options: `["Yes, push now", "No, skip"]`

If user selects **"Yes, push now"**:
```bash
uvx --from "${CLAUDE_SKILL_DIR}" prompt-eval push \
  --prompt {prompt} \
  --run-id {run_id} \
  --version v{n}
```

If exit code is non-zero or user selects "No, skip", continue to Step 4 without pushing.

---

## Step 4 — Show results & analyze failures

Get the structured scoreboard:
```bash
uvx --from "${CLAUDE_SKILL_DIR}" prompt-eval show \
  --prompt {prompt} \
  --run-id {run_id} \
  --version v{n} \
  --json
```

Parse the JSON output. Render as this Markdown table:

| Scenario | Score | Criteria | Reasoning |
|----------|-------|----------|-----------|
| {scenario} | {score}/10 | {breakdown summary} | {reasoning} |

Print average score and pass rate from the summary.

**Analyze failures (score < 7):**

For each low-scoring case, examine the `criteria_breakdown`:
- Which criteria got FAIL or PARTIAL?
- What pattern emerges?

Use this table to suggest improvements:

| Pattern | Remedy |
|---------|--------|
| Output too long/short | Add explicit length constraint in prompt |
| Missing required element | Add example showing the element |
| Wrong format | Tighten output spec with exact format |
| Tone mismatch | Add or refine role |
| Hallucinated content | Add "quote from input only" rule |

---

## Step 5 — Apply improvement

After scores are shown for v{n}, ask via `AskUserQuestion`:
- **Iterate the prompt** — propose v{n+1} based on the lowest-scoring cases (existing behavior).
- **Cross-validate with different models** — spawn a sibling run that re-uses the dataset and current prompt version, but with new models. Ask the user for `test_model` and `judge_model` (offer a sensible flip — e.g. if they used `test=haiku, judge=sonnet`, suggest `test=sonnet, judge=sonnet`). Then:

```bash
uvx --from "${CLAUDE_SKILL_DIR}" prompt-eval clone-for-crossval \
  --prompt <prompt_name> --from-run-id <current_run_id> --from-version v{n} \
  --test-model <new_test_model> --judge-model <new_judge_model>
```

  The CLI prints the new `run_NNN`. Resume the skill flow against that new run starting at Step 3a (execute v1 of the new run, then grade). The dataset and prompt are already in place.
- **Done** — stop here.

If Iterate the prompt:
- Offer:
  > a) Apply Claude's #1 suggested fix (show diff first)
  > b) Add a few-shot example built from a failed case
  > c) Provide your own revised prompt
- Compute the next version label `v{n+1}`.
- Save the new prompt to `prompt_eval_runs/prompts/{prompt}/runs/run_NNN/v{n+1}/prompt.txt` (create parent dirs as needed).
- Run Step 3 with `--version v{n+1}`.
- Run Step 4.
- Loop back to Step 5.

If Done:
- Stop the mkdocs server:
```bash
uvx --from "${CLAUDE_SKILL_DIR}" prompt-eval stop-server
```
- Tell the user: "Session complete. The mkdocs server has been stopped. To view results later, run `cd prompt_eval_runs/docs-site && uv run mkdocs serve`."
- Stop.
