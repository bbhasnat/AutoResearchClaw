---
name: ahvs_multiagent
description: >-
  Runs an AHVS (Adaptive Hypothesis Validation System) cycle using multi-agent
  supervision: team lead orchestrates, executor runs hypotheses, observer verifies
  results and fixes framework bugs. Handles the full 5-phase flow: hypothesis
  generation, browser GUI selection, team creation, per-hypothesis execution loop
  with verification, and final archival. Use this skill whenever the user says
  "run AHVS with multi-agent", "AHVS multi-agent cycle", "run hypotheses with
  supervision", "run AHVS with executor and observer", "supervised AHVS run",
  or asks to run AHVS with agents, teams, or multi-agent coordination. Also
  trigger when the user mentions running hypotheses with an observer or executor
  agent, or wants a supervised AHVS cycle with bug-fixing. If the user just
  wants a plain single-agent AHVS run without supervision, this skill is NOT
  needed — use the CLI directly.
---

# AHVS Multi-Agent Execution

This skill orchestrates a full AHVS hypothesis-validation cycle using three coordinated Claude Code agents: a team lead (your session), an executor, and an observer. The human's only manual step is selecting hypotheses in a browser GUI (or even that can be skipped with auto-approve).

## What This Skill Does

1. Generates hypotheses (AHVS Stages 1–3)
2. Presents them in a browser GUI for human selection (or auto-approves)
3. Creates an agent team with executor (sonnet) and observer (opus)
4. Runs each selected hypothesis one at a time — executor runs it, observer verifies
5. Re-runs hypotheses that failed due to framework bugs (after observer fixes them)
6. Archives results (Stages 7–8) and shuts down the team

## What This Skill Does NOT Do

- Onboard a repo for AHVS (use `ahvs_onboarding` skill for that)
- Run the 23-stage research paper pipeline (that's the `researchclaw` skill)
- Force every hypothesis to pass — genuine misses are expected and recorded as lessons

## Prerequisites

Before running, verify:

1. **AHVS is onboarded**: the target repo has `.ahvs/baseline_metric.json`
2. **Branch is correct**: `cd <ARC_DIR> && git branch --show-current` should show the expected branch
3. **Working tree is clean**: `git status` shows no uncommitted changes
4. **Env vars are loadable**: the target repo's `.env` file exists
5. **Python env**: the correct conda/venv has all dependencies

If any prerequisite fails, stop and tell the user what's missing.

## Configuration

The skill needs these values. Extract them from the user's message, CLAUDE.md, or ask:

| Parameter | Source | Example |
|---|---|---|
| `ARC_DIR` | AutoResearchClaw install path | `/home/ubuntu/vision/AutoResearchClaw` |
| `REPO_PATH` | Target repo for AHVS | `/home/ubuntu/vision/rnd_user_cohort/autoqa` |
| `ENV_FILE` | Env vars file (API keys etc.) | `/home/ubuntu/vision/rnd_user_cohort/.env` |
| `PYTHON` | Python binary with dependencies | `/home/ubuntu/miniconda3/envs/cohort_work/bin/python` |
| `MAX_HYPS` | Number of hypotheses (1–5) | `3` |
| `PROVIDER` | LLM provider | `openrouter` |
| `MODEL` | LLM model | `anthropic/claude-opus-4-6` |
| `API_KEY_ENV` | Env var name holding the API key | `OPENROUTER_API_KEY` |
| `AUTO_APPROVE` | Skip GUI selection? | `false` (default) |

## The 5-Phase Flow

### Phase 1 — Generate Hypotheses

Run AHVS Stages 1–3 only. This produces `hypotheses.md` in the cycle dir.

```bash
cd {ARC_DIR} && \
export $(grep -v '^#' {ENV_FILE} | xargs) && \
{PYTHON} -m researchclaw ahvs \
  --repo {REPO_PATH} \
  --max-hypotheses {MAX_HYPS} \
  --until-stage AHVS_HYPOTHESIS_GEN \
  --provider {PROVIDER} --model {MODEL} \
  --api-key-env {API_KEY_ENV} \
  2>&1 | tee /tmp/ahvs_gen.log
```

**Parse the cycle directory** from the output. Look for the line:
```
[AHVS] Cycle: <cycle_id>
```
The full cycle dir is: `{REPO_PATH}/.ahvs/cycles/<cycle_id>`

Tell the user: "Generated {N} hypotheses. Opening selection GUI..."

### Phase 2 — Human Selection (or Auto-Approve)

**If AUTO_APPROVE is false** (default): launch the browser GUI.

```bash
{PYTHON} -m researchclaw.ahvs.hypothesis_selector \
  {REPO_PATH}/.ahvs/cycles/{CYCLE_ID}
```

This is a **blocking call** — it starts a localhost HTTP server and opens the browser. The human sees hypothesis cards with checkboxes. When they click Submit, the script writes `selection.json` and exits.

Run this as a **foreground** Bash call (not `run_in_background`). The Bash tool returns when the human submits.

After it returns, read the selection:
```
Read: {REPO_PATH}/.ahvs/cycles/{CYCLE_ID}/selection.json
```
Extract the `selected` array — these are the hypothesis IDs to run (e.g., `["H1", "H3"]`).

**If AUTO_APPROVE is true**: skip the GUI entirely. All hypotheses are selected. Read `hypotheses.md` to get the IDs.

Tell the user which hypotheses were selected.

### Phase 3 — Team Setup

Create the agent team and spawn executor + observer.

```
TeamCreate:
  team_name: "ahvs-cycle"
  description: "AHVS multi-agent hypothesis execution + verification"
```

Spawn executor and observer using the prompts in `references/agent_prompts.md`. Read that file now and use the exact prompts, substituting the configuration values.

```
Agent:
  name: "executor"
  team_name: "ahvs-cycle"
  subagent_type: "general-purpose"
  prompt: <executor prompt from references/agent_prompts.md>

Agent:
  name: "observer"
  team_name: "ahvs-cycle"
  subagent_type: "general-purpose"
  model: "opus"
  prompt: <observer prompt from references/agent_prompts.md>
```

### Phase 4 — Per-Hypothesis Loop

For each selected hypothesis ID, run this loop **sequentially** (one at a time):

#### Step A: Ask executor to run the hypothesis

```
SendMessage:
  to: "executor"
  message: |
    Run hypothesis {H_ID}. Use this exact command:

    cd {ARC_DIR} && \
    export $(grep -v '^#' {ENV_FILE} | xargs) && \
    {PYTHON} -m researchclaw ahvs \
      --repo {REPO_PATH} \
      --from-stage AHVS_HUMAN_SELECTION \
      --until-stage AHVS_EXECUTION \
      --run-dir {REPO_PATH}/.ahvs/cycles/{CYCLE_ID} \
      --provider {PROVIDER} --model {MODEL} \
      --api-key-env {API_KEY_ENV} \
      2>&1 | tee /tmp/ahvs_{H_ID}.log

    When done, report: exit code, result path, any errors.
```

Wait for executor to respond.

#### Step B: Ask observer to verify

```
SendMessage:
  to: "observer"
  message: |
    Verify {H_ID} result.
    Result dir: {REPO_PATH}/.ahvs/cycles/{CYCLE_ID}/tool_runs/{H_ID}/
    Log: /tmp/ahvs_{H_ID}.log
    Classify as FRAMEWORK_BUG, HYPOTHESIS_MISS, or AMBIGUOUS.
    If FRAMEWORK_BUG: fix it (pytest gate required), then report RERUN_NEEDED.
    If HYPOTHESIS_MISS: record lesson, report PASS.
    If AMBIGUOUS: escalate to me with evidence.
```

Wait for observer to respond.

#### Step C: Decide next action

| Observer says | Action |
|---|---|
| **PASS** (hypothesis miss or metric improved) | Move to next hypothesis |
| **RERUN_NEEDED** (framework bug was fixed) | Go back to Step A for same H_ID |
| **AMBIGUOUS** | Read observer's evidence, make a decision, then PASS or RERUN |

Track re-run count per hypothesis. If the same hypothesis needs re-running more than 3 times, escalate to the human — something deeper is wrong.

#### Step D: Report progress

After each hypothesis completes, tell the user:
```
"{H_ID} complete — {outcome}. {N_remaining} hypotheses remaining."
```

### Phase 5 — Archive and Shutdown

After all hypotheses are done, run the archive stages (7–8):

```bash
cd {ARC_DIR} && \
export $(grep -v '^#' {ENV_FILE} | xargs) && \
{PYTHON} -m researchclaw ahvs \
  --repo {REPO_PATH} \
  --from-stage AHVS_REPORT_MEMORY \
  --run-dir {REPO_PATH}/.ahvs/cycles/{CYCLE_ID} \
  --provider {PROVIDER} --model {MODEL} \
  --api-key-env {API_KEY_ENV}
```

Then shut down the team:

```
SendMessage: to="executor", type="shutdown_request", reason="All hypotheses complete"
SendMessage: to="observer", type="shutdown_request", reason="All lessons recorded"
TeamDelete
```

Report to the user:
```
"Done. {kept}/{total} hypotheses improved metric.
 {bugs_fixed} framework bugs found and fixed.
 Report: {REPO_PATH}/.ahvs/cycles/{CYCLE_ID}/report.md"
```

## Memory Discipline

This is critical — follows CLAUDE.md rules. As team lead, you must:

- Write a memory file for every framework bug the observer fixes
- Update MEMORY.md index after each memory write
- Record lessons to `.ahvs/evolution/lessons.jsonl`
- Do NOT defer memory writes to end of session

The observer also writes memory and lessons independently. The team lead should verify this happened by checking the files after the observer reports a fix.

## Failure Classification

Read `references/failure_classification.md` for the full rules. Summary:

| Type | Meaning | Who fixes | Re-run? |
|---|---|---|---|
| FRAMEWORK_BUG | AHVS framework code is broken | Observer | Yes |
| HYPOTHESIS_MISS | Hypothesis ran fine, metric didn't improve | Nobody | No |
| AMBIGUOUS | Can't tell from logs | Lead decides | Maybe |

## Error Handling

| Situation | Action |
|---|---|
| Phase 1 fails (gen error) | Show error to user, do not proceed |
| GUI times out or user closes browser | Ask user if they want to retry or auto-approve |
| Executor crashes mid-hypothesis | Ask observer to classify, then re-run or skip |
| Observer fix breaks tests | Observer reverts, escalates to lead |
| Same hypothesis fails 3+ times | Stop loop, escalate to human |
| Archive stage fails | Show error, but hypotheses results are already saved |

## Reference Files

Read these when spawning agents — they contain the full prompts and rules:

- `references/agent_prompts.md` — Executor and observer agent prompts (read before Phase 3)
- `references/failure_classification.md` — Full classification rules, pytest gate procedure, memory write requirements
