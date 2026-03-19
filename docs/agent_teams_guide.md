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
TaskCreate: "Run AHVS cycle on autoqa repo with --auto-approve"
TaskCreate: "Monitor cycle results and diagnose any failures"
TaskCreate: "Fix framework bugs found during monitoring"
```

Tasks support dependencies — a task can be blocked until another completes.

### Step 3: Spawn Teammates

Use the Agent tool with `team_name` and `name` parameters:

```
Agent:
  name: "executor"
  team_name: "ahvs-improvement"
  subagent_type: "general-purpose"
  prompt: "You are the executor agent. Run AHVS on /home/ubuntu/vision/rnd_user_cohort/autoqa. Check TaskList for your assignments."

Agent:
  name: "observer"
  team_name: "ahvs-improvement"
  subagent_type: "general-purpose"
  prompt: "You are the observer agent. Monitor AHVS results and fix framework code. Check TaskList for your assignments."
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
├── executor: runs the experiment
└── observer: watches results, fixes code
```

The observer reads executor's output files and sends findings to the lead or directly fixes issues.

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

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Agent Teams tools not appearing | Verify `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is set, restart Claude Code |
| No split panes | Must be inside a tmux session before launching `claude` |
| Teammate not responding | It's probably idle — send it a message via `SendMessage` |
| TeamDelete fails | Shutdown all teammates first, then delete |
| File conflicts between teammates | Use `isolation: "worktree"` when spawning |

## Example: AHVS Observer/Executor Team

This is the pattern we use for autonomous hypothesis validation:

```
# 1. Create team
TeamCreate: team_name="ahvs-cycle", description="AHVS run + framework improvement"

# 2. Create tasks
TaskCreate: "Run AHVS on autoqa: researchclaw ahvs --repo /home/ubuntu/vision/rnd_user_cohort/autoqa --auto-approve"
TaskCreate: "After cycle completes, read .ahvs/cycles/*/cycle_summary.json and diagnose failures"
TaskCreate: "Fix any framework bugs in AutoResearchClaw based on diagnosis" (blocked by task 2)

# 3. Spawn teammates
Agent: name="executor", team_name="ahvs-cycle", prompt="Run AHVS. Check TaskList."
Agent: name="observer", team_name="ahvs-cycle", prompt="Monitor results, fix code. Check TaskList."

# 4. Assign
TaskUpdate: task_id=1, owner="executor"
TaskUpdate: task_id=2, owner="observer"

# 5. Watch them work in tmux split panes
# 6. Teammates communicate findings via SendMessage
# 7. Shutdown when done
```
