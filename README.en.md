# Coder Assist Personal

🇧🇷 [Português](README.md) | 🇺🇸 English

AI-assisted code editing CLI — local-first, with mandatory approval before any
write and a complete audit trail in SQLite.

The installed command is **`coder-dev`** and it works from inside any project:
it detects the project root automatically (via `.git` or the current folder)
and keeps history, memory, and backups separated per project.

**Status: V2 complete** (spec roadmap: MVP → V1 → V2 ✓).

## Principles

1. The AI never writes directly: proposal → diff → approval → backup → atomic write.
2. Every model call goes through the Router, which records 100% of interactions.
3. No writes outside the project root (path guard with symlink resolution).
4. Secrets are redacted before any persistence (log or database).
5. Fail safely: an error at any step aborts without touching your files.
6. Offline-first: works 100% without internet using Ollama.

## Installation

Prerequisites:

- **Python 3.12+**
- **[Ollama](https://ollama.com)** running locally with the configured model:
  `ollama pull gpt-oss:20b` (and `ollama pull nomic-embed-text` for the vector memory)
- Optional: **Claude Code CLI** authenticated (`claude login`) to escalate complex
  tasks — see the [Using Claude](#using-claude) section

```bash
cd ~/dev/coder-assist-personal  # or wherever the repo is
pipx install --editable .       # recommended (isolates dependencies)
# alternative: python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
```

`--editable` makes source-code changes take effect immediately, without
reinstalling. If the `coder-dev` command is not found after installing, make
sure `~/.local/bin` is in your PATH:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```

Verify the installation:

```bash
coder-dev --help
```

### Where the data lives

Runtime state lives in **`~/.coder-assist-personal/`**, separate from the
source code and shared across all projects:

| Folder               | Contents                                                        |
| -------------------- | --------------------------------------------------------------- |
| `db/`                | SQLite database (history, decisions, tags, commits) and vector index |
| `backups/<project>/` | Backups used by `undo`, one per written edit                    |
| `logs/`              | JSON logs with secrets redacted (`coder-assist.log`)            |
| `config/`            | `settings.yaml` with your local overrides (not versioned)      |

## Command guide

All commands are run from inside the project folder you are working on
(`cd ~/dev/my-project`).

### `coder-dev index` — index the project into vector memory

Scans the project files, splits them into chunks respecting function
boundaries, and stores embeddings in the vector database (ChromaDB). This is
what powers `recall` and the editing context. It respects the project's real
`.gitignore` and skips binaries.

```bash
coder-dev index .          # incremental: only re-indexes changed files (by hash)
coder-dev index . --full   # forces full re-indexing (e.g. after changing the embeddings model)
```

**When to use:** the first time in each project and after large changes.
Incremental mode is cheap — run it as often as you like.

### `coder-dev edit` — edit a file with AI

The heart of the tool. The AI proposes the change, you see the **diff per
file** and approve (or reject) before anything is written. Every approved edit
creates an automatic backup before writing (atomic write).

```bash
coder-dev edit lib/home_page.dart -m "convert to ConsumerWidget"
coder-dev edit lib/service.dart -m "refactor" --plan        # shows a step-by-step plan before editing
coder-dev edit lib/complex.dart -m "..." --provider claude  # escalates straight to Claude (confirms cost)
```

| Option           | Effect                                                          |
| ---------------- | --------------------------------------------------------------- |
| `-m, --message`  | Edit instruction (without it, the CLI prompts interactively)    |
| `--plan`         | The AI presents a step-by-step plan for approval before proposing the diff |
| `--provider`     | Forces `ollama` (local, default) or `claude` (paid, asks for cost confirmation) |

**When to use:** any code change. Edits touching multiple files show one diff
per file, with individual or batch approval.

### `coder-dev ask` — ask without editing anything

Free-form chat with project context. **Never writes to files** — safe for
exploration. Everything is recorded in the history and becomes memory
searchable via `recall`.

```bash
coder-dev ask "why does this screen use Provider?"
coder-dev ask "what is the authentication flow?" --provider claude
```

**When to use:** understanding code, discussing approaches, clearing up
architecture questions before editing.

### `coder-dev recall` — search the accumulated knowledge

Hybrid search (vector + FTS5 keyword, RRF fusion) over everything the tool
has seen: indexed code, past interactions, and recorded decisions. Always
shows the **sources** of each result. If the vector database is unavailable,
it automatically degrades to keyword search.

```bash
coder-dev recall "google login bug" -k 5        # top 5 results with sources
coder-dev recall "why did we migrate?" --synthesize  # AI-consolidated answer, citing sources
coder-dev recall --tag auth                     # lists interactions marked with the tag
```

| Option          | Effect                                                    |
| --------------- | ---------------------------------------------------------- |
| `-k`            | Number of results (default: 5)                             |
| `--synthesize`  | The AI consolidates the results into a single answer, with sources |
| `--tag`         | Instead of searching, lists the interactions with the given tag |

**When to use:** "where did we touch this?", "why did we decide that?",
picking context back up after weeks away from the project.

### `coder-dev decision` — record an architecture decision

Stores a decision document in memory (one decision per document),
retrievable later via `recall`. It is the project's logbook.

```bash
coder-dev decision "We adopted Riverpod instead of Provider" --tag architecture
coder-dev decision "Payments API will be synchronous in the MVP" --tag payments --tag mvp
```

The `--tag` option is repeatable. **When to use:** whenever you settle a
decision that "future you" will want to understand.

### `coder-dev history` — view the interaction history

Lists the interactions recorded by the Router (edits, asks, commits…), with
ID, date, provider, and summary.

```bash
coder-dev history            # last 20
coder-dev history -n 50      # last 50
coder-dev history --tag auth # filtered by tag
coder-dev history --project my-project
```

### `coder-dev tag` — tag an interaction

Applies a free-form tag (created on demand) to an interaction in the history,
for later filtering with `history --tag` and `recall --tag`.

```bash
coder-dev history          # find the interaction ID
coder-dev tag 42 auth      # tags interaction #42 with "auth"
```

### `coder-dev undo` — undo the last edit

Restores the backup of the last written edit, showing the diff of what will
be restored and asking for confirmation. Backups form a per-project stack
(configurable retention, default 20).

```bash
coder-dev undo          # restores the most recent backup (with diff + confirmation)
coder-dev undo --list   # shows the stack of available backups
```

**When to use:** you approved an edit and regret it. Since every `edit`
creates a backup before writing, undo always has somewhere to go back to.

### `coder-dev stats` — usage observability

Interaction totals, usage per provider (how much stayed on Ollama vs.
escalated to Claude), rejection/escalation rates, and most-edited files.

```bash
coder-dev stats                  # everything, since the beginning
coder-dev stats --since 30d     # last 30 days (accepts d, w, h — e.g. 2w, 12h)
coder-dev stats --project my-project
```

### `coder-dev commit` — assisted commit

Generates a **suggested** commit message from the staged diff — you edit and
confirm; it is never automatic and **never pushes**. If nothing is staged, it
offers `git add -A` (with confirmation). The commit is recorded in the tool's
history.

```bash
git add -p          # optional: choose what to commit
coder-dev commit    # suggests the message, you edit and confirm
```

### `coder-dev config` — view and adjust configuration

Shows the effective configuration (repo defaults + your overrides) or writes
a local override to `~/.coder-assist-personal/config/settings.yaml`.

```bash
coder-dev config --show
coder-dev config --set providers.ollama.model=llama3
coder-dev config --set providers.claude.max_budget_usd=1.00
coder-dev config --set router.confidence_threshold=0.70
```

Keys use dotted notation (`section.subsection.key=value`) and the value is
parsed as YAML (numbers, booleans, and strings work naturally). The
configuration is revalidated on the spot — an invalid value is rejected with
a clear error.

## Operating modes

The tool operates in one of three modes, controlled by `mode` in the
configuration (`coder-dev config --set mode=<mode>`):

| Mode | What it enables | Who it's for |
| --- | --- | --- |
| `offline` | **Ollama only.** The Claude provider is not even registered — no external call is possible, not even by accident. | Corporate deployment without external-traffic approval; environments with DLP/restrictive policies. |
| `provider` (default) | Ollama + Claude via the **personal Claude Code CLI** (`claude login`). | Personal use, your own projects. |
| `corporate` | Ollama + Claude via the **organization-sanctioned endpoint** (AWS Bedrock, Google Vertex, or an internal gateway). | Companies that approved an official Claude access channel. |

```bash
coder-dev config --set mode=offline     # locks the tool to 100% local
coder-dev config --set mode=provider    # back to default (personal Claude)
coder-dev config --set mode=corporate   # uses the organization's endpoint
```

In `offline` mode, `--provider claude` and escalation offers are disabled
with a clear message — local behavior (edit, ask, index, recall, memory,
undo) remains complete.

In `corporate` mode, configure the endpoint under
`providers.claude.corporate` (via `settings.yaml` or `config --set`):

```yaml
providers:
  claude:
    corporate:
      model: us.anthropic.claude-sonnet-4-6-v1:0   # model id on the endpoint
      env:                                          # AWS Bedrock example:
        CLAUDE_CODE_USE_BEDROCK: "1"
        AWS_REGION: us-east-1
      # Google Vertex: CLAUDE_CODE_USE_VERTEX=1, CLOUD_ML_REGION,
      #                ANTHROPIC_VERTEX_PROJECT_ID
      # Internal gateway (LiteLLM etc.): ANTHROPIC_BASE_URL
```

The variables are injected only into the `claude` binary invocation — the
endpoint credentials (AWS/GCP) follow your organization's standard mechanism,
and the tool still stores no keys whatsoever.

## Using Claude

By default everything runs on **Ollama** (local and free). Claude is the
"reinforcement" provider for tasks the local model can't handle — and its
use is always **paid, explicit, and confirmed**. (Available in the `provider`
and `corporate` modes — see [Operating modes](#operating-modes).)

### Initial setup (once)

1. Install the [Claude Code CLI](https://claude.com/claude-code):

   ```bash
   npm install -g @anthropic-ai/claude-code
   ```

2. Authenticate with your account:

   ```bash
   claude login
   ```

3. Verify:

   ```bash
   claude --version
   ```

Authentication belongs to Claude Code itself — the tool **never handles API
keys**; it only invokes the already-authenticated `claude` binary.

### The two ways to use it

**1. Force Claude on a command** — when you already know the task is complex:

```bash
coder-dev edit lib/complex.dart -m "refactor the payment flow" --provider claude
coder-dev ask "explain the offline sync architecture" --provider claude
```

**2. Escalation recommended by the Router** — in the normal flow (without
`--provider`), the Router monitors the local model's response and
**recommends** escalating when:

- the response confidence falls below the threshold (`router.confidence_threshold`, default 0.60);
- the context exceeds the local model's window (`providers.ollama.context_window_tokens`);
- there are two consecutive failures parsing the response.

In both cases the behavior is the same: before calling Claude, the tool shows
the **cost estimate in USD and asks for your confirmation**. Nothing is
charged without your approval. The real cost of the call (reported by Claude
Code itself) is recorded in the history — see the running total with
`coder-dev stats`.

### Cost control and configuration

| Key                                    | Default             | Effect                                              |
| -------------------------------------- | ------------------- | --------------------------------------------------- |
| `providers.claude.max_budget_usd`      | `0.50`              | Hard cap per call — Claude Code aborts if exceeded  |
| `providers.claude.model`               | `claude-sonnet-4-6` | Model used for escalations                          |
| `providers.claude.timeout_seconds`     | `300`               | Call timeout                                        |
| `router.confidence_threshold`          | `0.60`              | Below this, the Router recommends escalating        |
| `router.confirm_cost_before_claude`    | `true`              | Asks for cost confirmation before each call         |

```bash
coder-dev config --set providers.claude.max_budget_usd=1.00
coder-dev config --set providers.claude.model=claude-sonnet-4-6
```

### Security

The call is headless and isolated: prompt via stdin, **no tools**, a single
turn (`--max-turns 1`), and a neutral working directory — Claude **does not
read or edit your project directly**; it only sees the context the tool puts
in the prompt, and any proposed edit goes through the same diff + approval +
backup flow as always.

## Backup and migrating to another machine

All state (history, decisions, vector memory, undo backups, and
configuration) lives in a single directory: `~/.coder-assist-personal/`. To
take everything to another machine:

**On the source machine:**

```bash
tar czf coder-assist-backup.tar.gz -C ~ .coder-assist-personal
# copy the file via scp, USB drive, cloud…
```

**On the destination machine:**

```bash
# 1. Install the tool (Installation section)
# 2. Restore the state BEFORE first use:
tar xzf coder-assist-backup.tar.gz -C ~
```

Notes:

- Project paths are recorded in the database; if the projects live at
  different paths on the new machine, history and decisions remain
  accessible, but run `coder-dev index .` in each project to rebuild the link
  with the new location.
- The vector index depends on the embeddings model: ensure the same model on
  the destination (`ollama pull nomic-embed-text`) or re-index with
  `coder-dev index . --full`.
- For a periodic safety backup, the same `tar` works — the directory can be
  restored over the existing one (it replaces the current state).

## Removal (uninstall)

Removal has two independent parts — the program and the data:

**1. Remove the program:**

```bash
pipx uninstall coder-assist-personal
# or, if installed with pip: pip uninstall coder-assist-personal
```

**2. Remove the data (optional and irreversible):**

```bash
rm -rf ~/.coder-assist-personal
```

> **Warning:** this deletes the interaction history, recorded decisions,
> vector memory, and `undo` backups for **all projects**. If there is any
> chance you will want the data later, run the `tar` from the backup section
> first. Your projects and repositories **are not touched** — the tool never
> writes outside `~/.coder-assist-personal/` and the project root during
> approved edits.

Uninstalling only the program (step 1) and keeping the data is safe: after
reinstalling, everything picks up where it left off.

## Tests

```bash
pytest
```

## Roadmap

- **MVP (done)**: edit/ask/history/undo/config, Ollama + Router with full
  recording, SQLite (schema section 11), search/replace with validation and
  parse retry, diff + approval + backup + atomic write, path guard, redactor,
  tests.
- **V1 (done)**: ChromaDB + embeddings (`nomic-embed-text`, optional
  sentence-transformers fallback), chunking with function boundaries and
  hash-based invalidation, incremental `coder-dev index .` respecting the real
  `.gitignore` (pathspec), FTS5 kept in sync by triggers (recall degradation),
  vector `recall` with mandatory provenance, `recall --tag`, `stats`, assisted
  `coder-dev commit` recorded in the `commits` table, interactions indexed
  best-effort.
- **V2 (done)**: Claude provider via Claude Code CLI (headless `claude -p`,
  prompt via stdin, neutral cwd, no tools, `--max-turns 1`,
  `--max-budget-usd`, real cost from `total_cost_usd`, flags validated against
  `--help`), full routing policy (confidence, context window, parse failures,
  complex task) with cost estimate and confirmation, RRF hybrid search +
  `recall --synthesize` with cited sources, multi-file editing with individual
  or batch approval, decision documents (`coder-dev decision`), planning
  (`coder-dev edit --plan`), Claude provider tested with a mocked binary.

Optional improvements not implemented (listed as such in the spec):
tree-sitter for chunking, Knowledge Graph, streaming.
