# Claude Code Agent Teams — Practical Guide

## What Are Agent Teams?

Agent Teams let you run multiple Claude Code agents as a coordinated group within a single session. One agent acts as the **team lead** (your main session), and it spawns **teammates** — independent agents that each get their own context window, can message each other, and share a task list.

This is different from subagents, which are lightweight workers that report back to the main session. Teammates are full agents that persist, communicate, and coordinate.

## Prerequisites

### 1. Enable Agent Teams

Add to your global settings (`~/.claude/settings.json`):

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

Or set the environment variable before launching:

```bash
export CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1
claude
```

### 2. tmux (for split-pane view on Linux)

```bash
# Install
sudo apt install tmux

# Start a tmux session BEFORE launching claude
tmux new -s agents
claude
```

On macOS, iTerm2 also works natively.

## Core Concepts

| Concept | Description |
|---------|-------------|
| **Team Lead** | Your main Claude Code session. Creates the team, spawns teammates, assigns tasks. |
| **Teammate** | An independent agent spawned by the lead. Has its own context window and tools. |
| **Task List** | Shared list at `~/.claude/tasks/{team-name}/`. All teammates can read, claim, and update tasks. |
| **Team Config** | Stored at `~/.claude/teams/{team-name}/config.json`. Contains member list with names and IDs. |
| **Idle State** | Normal state — teammates go idle after every turn. They wake up when you send them a message. |

## Step-by-Step Workflow

### Step 1: Create a Team

In your Claude Code session, the lead creates a team:

```
TeamCreate:
  team_name: "ahvs-improvement"
  description: "Run AHVS on autoqa and improve framework code"
```

This creates:
- `~/.claude/teams/ahvs-improvement/config.json`
- `~/.claude/tasks/ahvs-improvement/`

### Step 2: Create Tasks

Break the work into tasks before spawning teammates:

```
TaskCreate: "Read CLAUDE.md and all memory files. Run AHVS cycle on autoqa repo with --auto-approve.
             Report cycle_summary.json path and exit code when done."
TaskCreate: "Continuously monitor AHVS hypothesis results while executor runs. Classify each failure
             as FRAMEWORK_BUG, HYPOTHESIS_MISS, or AMBIGUOUS. Fix framework bugs only (run pytest
             before and after). Record all lessons immediately. Never fix hypothesis misses."
```

Tasks support dependencies — a task can be blocked until another completes.

**Rule:** Task 2 (observer) runs *concurrently* with Task 1 (executor), not after it. The observer
monitors while the executor is still running so framework bugs can be caught and fixed mid-cycle.

### Step 3: Spawn Teammates

Use the Agent tool with `team_name` and `name` parameters:

```
Agent:
  name: "executor"
  team_name: "ahvs-improvement"
  subagent_type: "general-purpose"
  prompt: |
    You are the executor agent for an AHVS cycle.

    BEFORE STARTING:
    - Read /home/ubuntu/vision/AutoResearchClaw/CLAUDE.md
    - Read all memory files in the target repo's .ahvs/memory/ directory
    - Confirm you are on branch avhs_man_llm and the working tree is clean
      (cd /home/ubuntu/vision/AutoResearchClaw && git status)

    YOUR TASK: Run one AHVS cycle using this exact command:

      cd /home/ubuntu/vision/AutoResearchClaw && \
      export $(grep -v '^#' /home/ubuntu/vision/rnd_user_cohort/.env | xargs) && \
      /home/ubuntu/miniconda3/envs/cohort_work/bin/python -m researchclaw ahvs \
        --repo /home/ubuntu/vision/rnd_user_cohort/autoqa \
        --max-hypotheses 3 --auto-approve \
        --provider openrouter --model anthropic/claude-opus-4-6 \
        --api-key-env OPENROUTER_API_KEY \
        2>&1 | tee /tmp/ahvs_poc_run.log

    DURING EXECUTION:
    - Each hypothesis runs in its own worktree under .ahvs/cycles/<cycle_id>/worktrees/
    - Do NOT modify any hypothesis output or results manually
    - If the cycle crashes with a framework error (not a hypothesis miss), SendMessage to observer:
        "FRAMEWORK_ERROR: <error message and stack trace>. Cycle stopped."

    WHEN CYCLE COMPLETES (success or partial):
    - SendMessage to observer: "Cycle complete. Summary at: <path to cycle_summary.json>. Exit code: <N>."
    - SendMessage to lead: "Cycle complete. <N> hypotheses run, <kept> kept, <reverted> reverted."
    - Check TaskList for further instructions (e.g., re-run a specific hypothesis)

    RE-RUNNING A SINGLE HYPOTHESIS:
    - If lead asks you to re-run hypothesis H<N>, add --hypothesis-id <N> flag to the command above
    - Report result back to lead and observer

    Check TaskList for your assignments.

Agent:
  name: "observer"
  team_name: "ahvs-improvement"
  subagent_type: "general-purpose"
  model: "opus"
  prompt: |
    You are the observer agent for an AHVS cycle. Your job is to monitor hypothesis execution,
    classify failures, fix framework bugs (NOT hypothesis misses), and ensure lessons are recorded.

    BEFORE STARTING:
    - Read /home/ubuntu/vision/AutoResearchClaw/CLAUDE.md — follow its memory discipline exactly
    - Read all memory files in the target repo's .ahvs/memory/ directory
    - Read /home/ubuntu/vision/AutoResearchClaw/README_AHVS.md sections 1-3 for AHVS architecture

    YOUR RESPONSIBILITIES:

    1. MONITOR — continuously poll .ahvs/cycles/*/cycle_summary.json and /tmp/ahvs_poc_run.log
       for new hypothesis results while the executor is running. Do not wait until the cycle ends.

    2. CLASSIFY every failure into exactly one category:
       - FRAMEWORK_BUG: wrong path, ImportError, truncated CodeAgent output, missing worktree subdir,
         eval_command crash unrelated to hypothesis code
       - HYPOTHESIS_MISS: hypothesis ran correctly, metric did not improve (EXPECTED — do not fix)
       - AMBIGUOUS: escalate to lead with evidence

    3. FOR FRAMEWORK_BUG ONLY — follow this exact sequence:
       a. Run full test suite baseline:
            cd /home/ubuntu/vision/AutoResearchClaw && \
            /home/ubuntu/miniconda3/envs/cohort_work/bin/python -m pytest tests/ -v \
            --ignore=tests/e2e_docker_sandbox.py --ignore=tests/e2e_real_llm.py \
            2>&1 | tee /tmp/pytest_before_fix.log
          Note the number of passing/failing tests. This is your baseline.
       b. Use Context7 (mcp__claude_ai_Context7__query-docs) to look up relevant library docs
          if the bug involves an unfamiliar API
       c. Read the relevant source files in researchclaw/ahvs/ carefully before editing
       d. Apply the minimal fix — do not refactor surrounding code
       e. Run full test suite again:
            cd /home/ubuntu/vision/AutoResearchClaw && \
            /home/ubuntu/miniconda3/envs/cohort_work/bin/python -m pytest tests/ -v \
            --ignore=tests/e2e_docker_sandbox.py --ignore=tests/e2e_real_llm.py \
            2>&1 | tee /tmp/pytest_after_fix.log
       f. Compare before vs after. Requirements:
          - All tests that passed before must still pass (no regressions)
          - The specific regression test for this bug class must pass:
            * Bug A/C/E: tests/test_ahvs.py::TestBugA_* / TestBugC_* / TestBugE_*
       g. If any previously-passing test now fails: revert the fix, escalate to lead with both logs
       h. If all tests pass: proceed to step 4

    4. RECORD EVERY BUG IMMEDIATELY (do not defer to end of session):
       - Append to .ahvs/cycles/<cycle_id>/friction_log.md under ## Operator Notes
       - Append JSON line to .ahvs/evolution/lessons.jsonl
       - Write a memory file to the target repo's .ahvs/memory/ directory
       - Update .ahvs/memory/INDEX.md

    5. NOTIFY AND COORDINATE:
       - SendMessage to lead: "FRAMEWORK_BUG fixed: <one-line description>. Tests pass.
         Recommend re-running H<N>."
       - Do NOT ask executor to re-run directly — always go through lead

    6. FOR HYPOTHESIS_MISS — record the lesson only:
       - Append to lessons.jsonl: what was tried, what metric was measured, what the result was
       - SendMessage to lead: "H<N> = HYPOTHESIS_MISS. Metric: <value vs baseline>. Lesson recorded."
       - Do NOT modify eval thresholds, target repo metrics, or hypothesis code to make it pass

    SKILLS AND TOOLS TO USE:
    - mcp__claude_ai_Context7__query-docs — look up library/framework docs before fixing unfamiliar APIs
    - mcp__claude_ai_Context7__resolve-library-id — resolve library name to Context7 ID first
    - Grep / Read — read source before editing; never edit blind
    - Bash (pytest only) — run tests to validate fixes; do not use for edits
    - Edit tool — apply fixes; prefer minimal, targeted edits over rewrites

    Check TaskList for your assignments.
```

Each teammate appears in its own tmux pane (if running inside tmux).

### Step 4: Assign Tasks

```
TaskUpdate:
  task_id: 1
  owner: "executor"
  status: "in_progress"

TaskUpdate:
  task_id: 2
  owner: "observer"
  status: "in_progress"
```

### Step 5: Communicate

**Direct message to a teammate:**
```
SendMessage:
  to: "executor"
  message: "H1 got sandbox_error. Check the agent's generated code — it's writing standalone scripts instead of repo-targeted edits."
  summary: "Flag H1 sandbox error to executor"
```

**Broadcast to all (use sparingly — costs scale with team size):**
```
SendMessage:
  to: "*"
  message: "Merge freeze in 1 hour. Wrap up current tasks."
  summary: "Announce merge freeze"
```

Messages from teammates are **automatically delivered** to you — no polling needed.

### Step 6: Shutdown

When work is done, gracefully shut down each teammate:

```
SendMessage:
  to: "executor"
  message:
    type: "shutdown_request"
    reason: "All tasks complete"

SendMessage:
  to: "observer"
  message:
    type: "shutdown_request"
    reason: "All tasks complete"
```

Teammates can approve (exit) or reject (keep working) the shutdown.

After all teammates have shut down, clean up:

```
TeamDelete
```

This removes team and task directories.

## Agent Types for Teammates

Choose the right `subagent_type` based on what the teammate needs to do:

| Agent Type | Can Edit Files? | Best For |
|------------|----------------|----------|
| `general-purpose` | Yes | Implementation, bug fixes, running commands |
| `Explore` | No (read-only) | Codebase research, finding files, answering questions |
| `Plan` | No (read-only) | Architecture planning, design decisions |
| Custom (`.claude/agents/`) | Depends on config | Specialized workflows |

**Important:** Never assign implementation tasks to read-only agents (Explore, Plan).

## Teammate Lifecycle

```
Spawned → Working → Idle → (message received) → Working → Idle → ... → Shutdown
```

- **Idle is normal.** Teammates go idle after every turn. This does NOT mean they crashed or finished.
- **Idle teammates wake up** when you send them a message via `SendMessage`.
- **Don't react to idle notifications** unless you have new work to assign.

## Coordination Patterns

### Pattern 1: Observer / Executor (what we do with AHVS)

```
Lead (you)
├── executor: runs hypotheses in parallel (one worktree per hypothesis)
└── observer: continuously monitors results, classifies failures, fixes framework bugs
```

**The correct goal for AHVS:** Fix framework bugs that prevent fair hypothesis evaluation. Let genuine hypothesis misses fail — they teach the next cycle what not to try. Do NOT try to make every hypothesis pass.

**Failure classification — the observer must distinguish:**

| Failure Type | Description | Correct Action |
|---|---|---|
| **FRAMEWORK_BUG** | Wrong path, ImportError, truncated output, missing worktree subdir | Observer fixes AutoResearchClaw, runs tests, notifies lead to re-run the hypothesis |
| **HYPOTHESIS_MISS** | Code ran correctly, metric did not improve | Record lesson in `lessons.jsonl`. Do nothing else — this is expected and valuable. |
| **AMBIGUOUS** | Can't tell from logs alone | Observer escalates to lead with evidence for a decision |

**Parallel hypothesis + fix-and-rerun flow:**

```
executor starts H1, H2, H3 in parallel (separate worktrees)
        │
        ├── H2 fails: ImportError in framework code
        │       └── observer detects it → classifies as FRAMEWORK_BUG
        │               → runs pytest tests/test_ahvs.py (baseline)
        │               → applies fix to AutoResearchClaw
        │               → runs pytest again (must pass)
        │               → writes friction_log.md + lessons.jsonl + memory
        │               → SendMessage to lead: "Bug fixed. Re-run H2."
        │                       └── lead SendMessage to executor: "Re-run H2"
        │
        ├── H1 completes: metric improved → kept
        └── H3 completes: metric did not improve → reverted (HYPOTHESIS_MISS, expected)
```

The observer reads executor output files (`.ahvs/cycles/*/`) and sends findings to the lead. The lead decides whether to re-run a specific hypothesis or start a fresh cycle.

### Pattern 2: Parallel Module Development

```
Lead
├── frontend: works on React components
├── backend: works on API endpoints
└── tester: writes and runs tests
```

Each teammate owns specific directories. The tester runs tests after frontend/backend signal completion via task updates.

### Pattern 3: Research + Implement

```
Lead
├── researcher: explores codebase, reads docs (Explore agent)
├── planner: designs approach (Plan agent)
└── coder: implements the plan (general-purpose agent)
```

Researcher and planner finish first, then coder gets their findings via messages.

### Pattern 4: Competing Hypotheses

```
Lead
├── approach-a: implements solution A in a worktree
├── approach-b: implements solution B in a worktree
└── evaluator: compares results
```

Use `isolation: "worktree"` when spawning to give each agent an isolated copy of the repo.

## Git Worktrees for Isolation

When teammates edit the same repo, use worktrees to avoid conflicts:

```
Agent:
  name: "feature-agent"
  team_name: "my-team"
  isolation: "worktree"
  prompt: "Implement feature X..."
```

Each worktree gets its own branch. Changes don't affect the main repo until merged.

## Task List Best Practices

1. **Check TaskList after completing each task** — new tasks may have been created or unblocked
2. **Claim tasks in ID order** (lowest first) — earlier tasks often set up context for later ones
3. **Create new tasks** when you discover additional work — don't just do it silently
4. **Mark tasks completed** promptly — this may unblock dependent tasks

## Discovering Team Members

Any teammate can read the team config to find other members:

```bash
# File: ~/.claude/teams/{team-name}/config.json
{
  "members": [
    {"name": "executor", "agentId": "abc123", "agentType": "general-purpose"},
    {"name": "observer", "agentId": "def456", "agentType": "general-purpose"}
  ]
}
```

Always use **name** (not agentId) when sending messages or assigning tasks.

## Communication Rules

1. **Text output is NOT visible to teammates.** You MUST use `SendMessage` to communicate.
2. **Don't send structured JSON status messages.** Use `TaskUpdate` for task status; system handles idle notifications automatically.
3. **Default to direct messages.** Broadcast (`to: "*"`) is expensive — only for critical team-wide issues.
4. **Don't quote received messages** when reporting to the user — they're already rendered in the UI.

## Plan Approval (Optional)

Spawn teammates in plan mode for extra control:

```
Agent:
  name: "risky-refactor"
  mode: "plan"
  team_name: "my-team"
  prompt: "Refactor the auth module..."
```

The teammate must get plan approval before implementing:
1. Teammate creates a plan and calls `ExitPlanMode`
2. Lead receives a `plan_approval_request`
3. Lead approves or rejects with feedback:

```
SendMessage:
  to: "risky-refactor"
  message:
    type: "plan_approval_response"
    request_id: "abc-123"
    approve: true
```

## Comparison: When to Use What

| Need | Use |
|------|-----|
| Quick focused task, results back to main context | **Subagent** (Agent tool) |
| Long-running parallel work, inter-agent communication | **Agent Team** |
| Independent feature branches, no coordination needed | **Worktrees** (`claude --worktree`) |
| Visual monitoring of multiple agents | **tmux/iTerm2 + Agent Teams** |

## Observer: Skills and Tools Reference

The observer agent must use the right tool for each action. Using the wrong tool leads to blind edits,
untested fixes, or missed context.

| Task | Tool to Use | Notes |
|---|---|---|
| Understand an unfamiliar API before fixing | `mcp__claude_ai_Context7__resolve-library-id` then `mcp__claude_ai_Context7__query-docs` | Always resolve library ID first |
| Read source files before editing | `Read` tool | Never edit without reading first |
| Search for a function or pattern across the codebase | `Grep` tool | Use before and after fixes to verify scope |
| Apply a fix | `Edit` tool | Prefer targeted edits over full-file rewrites |
| Run tests | `Bash` tool (pytest only) | Run full suite (`tests/`) before AND after every fix; skip e2e tests |
| Write lessons / memory | `Write` tool | friction_log.md, lessons.jsonl, memory files |
| Communicate with lead | `SendMessage` | Always go through lead to trigger re-runs |

### Context7 Usage Pattern

Before fixing a bug involving an unfamiliar library or API:

```
# Step 1: resolve the library
mcp__claude_ai_Context7__resolve-library-id:
  libraryName: "ast"   # or "pathlib", "subprocess", etc.

# Step 2: query for relevant docs
mcp__claude_ai_Context7__query-docs:
  context7CompatibleLibraryID: "/python/cpython"
  topic: "ast.parse function signatures and NodeTransformer"
  tokens: 3000
```

### What the Observer Must NOT Do

- Do NOT modify `baseline_metric.json` or eval thresholds in the target repo to make numbers look better
- Do NOT rewrite surrounding code beyond the minimal fix
- Do NOT commit to the branch without running pytest
- Do NOT re-run hypotheses directly — always notify the lead and let them instruct the executor
- Do NOT classify a genuine metric miss as a framework bug

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Agent Teams tools not appearing | Verify `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is set, restart Claude Code |
| No split panes | Must be inside a tmux session before launching `claude` |
| Teammate not responding | It's probably idle — send it a message via `SendMessage` |
| TeamDelete fails | Shutdown all teammates first, then delete |
| File conflicts between teammates | Use `isolation: "worktree"` when spawning |

## Example: AHVS Team Lead / Executor / Observer

This is the full multi-agent pattern for an AHVS cycle. For a skill that encodes this entire flow (so Claude Code follows it exactly without improvisation), see [`skills/ahvs_multiagent/SKILL.md`](../skills/ahvs_multiagent/SKILL.md).

### Roles

| Agent | Model | Responsibility |
|---|---|---|
| **Team Lead** (you / main session) | opus | Generates hypotheses, presents GUI, routes results, coordinates re-runs |
| **executor** | sonnet | Runs one hypothesis at a time when asked; reports result back to lead |
| **observer** | opus | Verifies each result when asked; fixes framework bugs; says yes/no to re-run |

### Goal

Complete every selected hypothesis without skipping any due to framework errors.
Genuine hypothesis misses are recorded as lessons and the cycle moves on —
**do NOT force every hypothesis to pass.**

### Step-by-step flow

```
═══════════════════════════════════════════════════════════
PHASE 1 — HYPOTHESIS GENERATION (team lead does this alone)
═══════════════════════════════════════════════════════════

# 1a. Run AHVS stages 1–3 only (preflight + context load + hypothesis gen)
cd /home/ubuntu/vision/AutoResearchClaw
export $(grep -v '^#' /home/ubuntu/vision/rnd_user_cohort/.env | xargs)

/home/ubuntu/miniconda3/envs/cohort_work/bin/python -m researchclaw ahvs \
  --repo /home/ubuntu/vision/rnd_user_cohort/autoqa \
  --max-hypotheses 3 \
  --until-stage AHVS_HYPOTHESIS_GEN \
  --provider openrouter --model anthropic/claude-opus-4-6 \
  --api-key-env OPENROUTER_API_KEY \
  2>&1 | tee /tmp/ahvs_gen.log

# This produces: .ahvs/cycles/<cycle_id>/hypotheses.md
# Note the cycle_id from the log output.

# 1b. Launch the GUI — human selects hypotheses via browser
/home/ubuntu/miniconda3/envs/cohort_work/bin/python \
  -m researchclaw.ahvs.hypothesis_selector \
  /home/ubuntu/vision/rnd_user_cohort/autoqa/.ahvs/cycles/<cycle_id>

# Browser opens automatically. Human checks boxes → clicks Submit.
# This writes selection.json into the cycle dir and exits.

═══════════════════════════════════════════════════════════
PHASE 2 — TEAM SETUP
═══════════════════════════════════════════════════════════

TeamCreate:
  team_name: "ahvs-cycle"
  description: "AHVS hypothesis execution + verification"

TaskCreate: "Execute hypothesis when team lead sends you an H-ID. Report result back."
TaskCreate: "Verify hypothesis result when team lead sends you an H-ID + result path.
             Classify as FRAMEWORK_BUG, HYPOTHESIS_MISS, or AMBIGUOUS.
             Fix framework bugs (pytest gate required). Report PASS or RERUN_NEEDED."

Agent:
  name: "executor"
  team_name: "ahvs-cycle"
  subagent_type: "general-purpose"
  prompt: "<use executor prompt from Step 3>"

Agent:
  name: "observer"
  team_name: "ahvs-cycle"
  subagent_type: "general-purpose"
  model: "opus"
  prompt: "<use observer prompt from Step 3>"

TaskUpdate: task_id=1, owner="executor"
TaskUpdate: task_id=2, owner="observer"

═══════════════════════════════════════════════════════════
PHASE 3 — PER-HYPOTHESIS LOOP (sequential for now)
═══════════════════════════════════════════════════════════

# For each hypothesis H1, H2, H3 ... repeat this loop:

# Step A: ask executor to run H<N>
SendMessage:
  to: "executor"
  message: |
    Run hypothesis H1. Use this exact command:

    cd /home/ubuntu/vision/AutoResearchClaw
    export $(grep -v '^#' /home/ubuntu/vision/rnd_user_cohort/.env | xargs)
    /home/ubuntu/miniconda3/envs/cohort_work/bin/python -m researchclaw ahvs \
      --repo /home/ubuntu/vision/rnd_user_cohort/autoqa \
      --from-stage AHVS_HUMAN_SELECTION \
      --until-stage AHVS_EXECUTION \
      --run-dir /home/ubuntu/vision/rnd_user_cohort/autoqa/.ahvs/cycles/<cycle_id> \
      --provider openrouter --model anthropic/claude-opus-4-6 \
      --api-key-env OPENROUTER_API_KEY \
      2>&1 | tee /tmp/ahvs_h1.log

    When done, SendMessage to lead with: exit code, result path, any errors.

# Step B: executor reports back
#   "H1 done. Exit 0. Result: .ahvs/cycles/<id>/tool_runs/H1/result.json"

# Step C: ask observer to verify
SendMessage:
  to: "observer"
  message: |
    Verify H1 result.
    Result path: /home/ubuntu/vision/rnd_user_cohort/autoqa/.ahvs/cycles/<cycle_id>/tool_runs/H1/
    Log: /tmp/ahvs_h1.log
    Classify as FRAMEWORK_BUG, HYPOTHESIS_MISS, or AMBIGUOUS.
    Fix if FRAMEWORK_BUG (pytest gate). Report: PASS or RERUN_NEEDED.

# Step D: observer reports back
#   "H1 = HYPOTHESIS_MISS. Metric 0.74 vs baseline 0.75. Lesson recorded. PASS."
#   OR
#   "H1 = FRAMEWORK_BUG (ImportError). Fixed executor.py line 512. Tests pass. RERUN_NEEDED."

# Step E: if RERUN_NEEDED → go back to Step A for same H-ID
#         if PASS → move to next hypothesis

═══════════════════════════════════════════════════════════
PHASE 4 — ARCHIVE (once, after all hypotheses done)
═══════════════════════════════════════════════════════════

cd /home/ubuntu/vision/AutoResearchClaw
export $(grep -v '^#' /home/ubuntu/vision/rnd_user_cohort/.env | xargs)
/home/ubuntu/miniconda3/envs/cohort_work/bin/python -m researchclaw ahvs \
  --repo /home/ubuntu/vision/rnd_user_cohort/autoqa \
  --from-stage AHVS_REPORT_MEMORY \
  --run-dir /home/ubuntu/vision/rnd_user_cohort/autoqa/.ahvs/cycles/<cycle_id> \
  --provider openrouter --model anthropic/claude-opus-4-6 \
  --api-key-env OPENROUTER_API_KEY

═══════════════════════════════════════════════════════════
PHASE 5 — SHUTDOWN
═══════════════════════════════════════════════════════════

SendMessage: to="executor", type="shutdown_request", reason="All hypotheses complete"
SendMessage: to="observer", type="shutdown_request", reason="All lessons recorded"
TeamDelete
```

## Pure Conversational Multi-Agent Mode

In the flow above, the human runs CLI commands for Phase 1. In **pure conversational mode**,
you just talk to Claude Code and it does everything — the only human touchpoint is the browser
GUI for hypothesis selection.

### How to trigger it

Say this (or similar) to Claude Code:

```
Run AHVS on /home/ubuntu/vision/rnd_user_cohort/autoqa with multi-agent supervision.
Use 3 hypotheses. Show me the GUI for selection.
```

That's it. Claude Code (as team lead) handles the rest.

### What Claude Code does internally

```
┌─────────────────────────────────────────────────────────────┐
│  HUMAN says: "Run AHVS on autoqa with multi-agent"          │
└─────────────────┬───────────────────────────────────────────┘
                  ▼
┌─ TEAM LEAD (Claude Code, your session) ─────────────────────┐
│                                                              │
│  1. Bash: run AHVS --until-stage AHVS_HYPOTHESIS_GEN        │
│     → produces hypotheses.md in cycle dir                    │
│     → captures cycle_dir path from output                    │
│                                                              │
│  2. Bash: python -m researchclaw.ahvs.hypothesis_selector    │
│           <cycle_dir>                                        │
│     → opens browser on localhost                             │
│     → BLOCKS until human clicks Submit                       │
│     → writes selection.json, script exits                    │
│                                                              │
│  3. Read selection.json → extract selected hypothesis IDs    │
│                                                              │
│  4. TeamCreate "ahvs-cycle"                                  │
│     Spawn executor (sonnet) + observer (opus)                │
│                                                              │
│  5. FOR EACH selected hypothesis:                            │
│     ├─ SendMessage → executor: "Run H<N>"                    │
│     │   executor: Bash(--from-stage AHVS_HUMAN_SELECTION     │
│     │             --until-stage AHVS_EXECUTION)              │
│     │   executor → lead: "H<N> done. Exit <code>."           │
│     │                                                        │
│     ├─ SendMessage → observer: "Verify H<N>"                 │
│     │   observer reads result, classifies failure            │
│     │   observer → lead: "PASS" or "RERUN_NEEDED"            │
│     │                                                        │
│     └─ If RERUN_NEEDED: repeat for same H<N>                 │
│        If PASS: next hypothesis                              │
│                                                              │
│  6. Bash: run AHVS --from-stage AHVS_REPORT_MEMORY          │
│     → generates report.md + cycle_summary.json               │
│                                                              │
│  7. Shutdown executor + observer, TeamDelete                 │
│                                                              │
│  8. Tell human: "Done. <summary of results>"                 │
└──────────────────────────────────────────────────────────────┘
```

### The human's experience

```
You:    "Run AHVS on autoqa with multi-agent supervision. 3 hypotheses."
Claude: "Generating hypotheses..." (runs Stage 1–3)
Claude: "Opening hypothesis selector in your browser."
        → browser opens, you see 3 hypothesis cards with checkboxes
        → you check H1 and H3, click Submit
        → browser shows "Selection submitted. You can close this tab."
Claude: "You selected H1 and H3. Spawning executor and observer..."
Claude: "Running H1..." (executor runs, observer verifies)
Claude: "H1 complete — metric improved by +0.03. Running H3..."
Claude: "H3 complete — HYPOTHESIS_MISS (0.74 vs 0.75 baseline). Lesson recorded."
Claude: "Generating final report..."
Claude: "Done. 1/2 hypotheses improved. Report at .ahvs/cycles/<id>/report.md"
```

Zero CLI commands typed by the human. The only manual step is the browser checkbox form.

### Fully automatic mode (no GUI, no human)

If you don't want even the browser step:

```
Run AHVS on autoqa with multi-agent supervision. Auto-approve all hypotheses.
```

Claude Code skips the GUI entirely — uses `--auto-approve` for Stage 4 and runs
all hypotheses through the executor/observer loop.

### Implementation note for the team lead

The team lead needs to handle the `hypothesis_selector` blocking call correctly.
Since it's a localhost HTTP server that blocks until the human submits, use a
regular (foreground) Bash call — not `run_in_background`. The Bash tool will
return when the human submits in the browser, at which point `selection.json`
is ready.

```python
# What the team lead effectively does (as tool calls):

# Step 1: generate
Bash("cd /home/ubuntu/vision/AutoResearchClaw && "
     "python -m researchclaw ahvs --repo <repo> --question '...' "
     "--until-stage AHVS_HYPOTHESIS_GEN --provider openrouter ...")
# → parse cycle_dir from output

# Step 2: GUI (blocks until human submits)
Bash("python -m researchclaw.ahvs.hypothesis_selector <cycle_dir>")
# → returns after human submits

# Step 3: read selection
Read("<cycle_dir>/selection.json")
# → {"selected": ["H1", "H3"], ...}

# Step 4: team + loop
TeamCreate(...)
Agent(name="executor", ...)
Agent(name="observer", ...)
# ... per-hypothesis loop via SendMessage ...
```

### Why this flow is better than continuous monitoring

| Old approach | New approach |
|---|---|
| Observer monitors continuously — races with executor | Observer verifies on-demand — no race conditions |
| All hypotheses run at once, bugs found late | Each hypothesis verified before the next starts |
| Re-run requires restarting the whole cycle | Re-run is one executor call for one hypothesis |
| Human not involved in hypothesis selection | Human reviews and selects via GUI before any execution |

### What each agent edits

| Agent | Edits AutoResearchClaw? | Edits target repo? |
|---|---|---|
| executor | No | No (worktrees only, via AHVS) |
| observer | Yes (framework bugs only, after pytest gate) | No |
| lead (you) | No | No |
