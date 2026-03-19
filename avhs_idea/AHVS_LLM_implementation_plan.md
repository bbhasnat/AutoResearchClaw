# AHVS LLM Manual Plan — Implementation Plan

**Date:** 2026-03-17
**Branch:** avhs_man_llm
**Status:** Pre-implementation — approved for development

---

## 1. The Core Architectural Decision

Before any file is touched, one decision shapes everything else:

> **AHVS gets its own `researchclaw/ahvs/` subpackage. It does NOT extend ARC's `Stage` enum.**

### Why

ARC's `Stage` is an `IntEnum`, and `STAGE_SEQUENCE = tuple(Stage)`. Adding AHVS stages to the same enum would inject them into the 23-stage research pipeline's execution loop — a guaranteed corruption of the existing system. More importantly, AHVS and ARC are **different kinds of pipelines**:

- ARC: one-shot, linear, produces a paper
- AHVS: cyclic, hypothesis-driven, produces improvement decisions

They share infrastructure (EvolutionStore, CodeAgent, LLMClient, sandbox), not pipeline architecture. The right relationship is **composition, not inheritance**.

### What this means

```
researchclaw/
├── pipeline/         ← ARC's 23-stage research pipeline (UNCHANGED)
│   ├── stages.py
│   ├── contracts.py
│   ├── executor.py
│   └── runner.py
│
└── ahvs/             ← NEW: AHVS 8-stage cycle package
    ├── __init__.py
    ├── stages.py       ← AHVSStage enum (separate from Stage)
    ├── contracts.py    ← AHVS-specific I/O contracts
    ├── config.py       ← AHVSConfig dataclass
    ├── result.py       ← HypothesisResult dataclass
    ├── skills.py       ← SkillLibrary + CodeAgent skill injection
    ├── context_loader.py ← baseline + EvolutionStore → context_bundle.json
    ├── health.py       ← AHVS-specific pre-flight checks
    ├── executor.py     ← 8 stage handler functions
    └── runner.py       ← execute_ahvs_cycle() orchestrator
```

Zero changes to any existing ARC file except `cli.py` (new subcommand) and `prompts.default.yaml` (new prompt blocks).

---

## 2. The Eight AHVS Stages

```python
class AHVSStage(IntEnum):
    AHVS_SETUP           = 1   # Pre-flight, baseline validation, cycle dir creation
    AHVS_CONTEXT_LOAD    = 2   # EvolutionStore overlay + baseline → context_bundle.json
    AHVS_HYPOTHESIS_GEN  = 3   # Typed, capped hypothesis generation (1–5)
    AHVS_HUMAN_SELECTION = 4   # GATE: human selects hypotheses to run
    AHVS_VALIDATION_PLAN = 5   # Per-hypothesis: implementation spec + eval method
    AHVS_EXECUTION       = 6   # CodeAgent executes each selected hypothesis
    AHVS_REPORT_MEMORY   = 7   # LLM writes report, EvolutionStore archives lessons
    AHVS_CYCLE_VERIFY    = 8   # Contract validation — all artifacts present + valid
```

Gate stage: `AHVS_HUMAN_SELECTION` (stage 4). Rollback: → `AHVS_HYPOTHESIS_GEN` (re-generate).

---

## 3. Data Flow Across Stages

```
researchclaw ahvs --repo /path/to/repo --question "..."
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AHVS_SETUP (Stage 1)                                               │
│  Reads:  .ahvs/baseline_metric.json (pre-existing, operator-written)│
│  Writes: cycle_dir/.ahvs/cycles/<timestamp>/                        │
│          cycle_manifest.json  (cycle ID, question, timestamp)       │
│  Checks: Promptfoo/DSPy/Phoenix installed? baseline valid? branch? │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AHVS_CONTEXT_LOAD (Stage 2)                                        │
│  Reads:  .ahvs/baseline_metric.json                                 │
│          evolution/ store (EvolutionStore.build_overlay)            │
│  Writes: context_bundle.json                                        │
│    {                                                                │
│      "question": "...",                                             │
│      "baseline": { "metric": "...", "value": 0.74, ... },          │
│      "prior_lessons": [...],   # from EvolutionStore              │
│      "rejected_approaches": [...],                                  │
│      "domain_tags": [...]                                           │
│    }                                                                │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AHVS_HYPOTHESIS_GEN (Stage 3)                                      │
│  Reads:  context_bundle.json                                        │
│  Writes: hypotheses.md                                              │
│    Each hypothesis has:                                             │
│    - id: H1 | H2 | H3                                              │
│    - type: prompt_rewrite | model_comparison | code_change |        │
│            architecture_change | dspy_optimize | config_change      │
│    - description: what to try                                       │
│    - rationale: why this might help                                 │
│    - estimated_cost: low | medium | high                            │
│    - required_tools: [promptfoo] | [docker] | [dspy, promptfoo]    │
│  Cap: 1–3 default, 5 hard max                                       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AHVS_HUMAN_SELECTION (Stage 4) — GATE                              │
│  Reads:  hypotheses.md                                              │
│  Action: Display to operator, wait for approval/modification        │
│  Writes: selection.md                                               │
│    {                                                                │
│      "selected": ["H1", "H3"],                                      │
│      "rationale": "H2 too expensive for this cycle",               │
│      "approved_by": "operator",                                     │
│      "timestamp": "2026-03-17T10:30:00Z"                           │
│    }                                                                │
│  Gate: approve → proceed | reject → rollback to Stage 3            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AHVS_VALIDATION_PLAN (Stage 5)                                     │
│  Reads:  context_bundle.json, selection.md, hypotheses.md           │
│  Writes: validation_plan.md                                         │
│    Per selected hypothesis:                                         │
│    - implementation_approach: what CodeAgent should build           │
│    - eval_method: promptfoo | custom_script | dspy_then_promptfoo  │
│    - success_criterion: metric >= X (relative to baseline)          │
│    - available_skills: [skill names from skill registry]            │
│    - artifacts_to_produce: list of expected output files            │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AHVS_EXECUTION (Stage 6)                                           │
│  Reads:  validation_plan.md, selection.md                           │
│  For each selected hypothesis:                                      │
│    1. Load skills for hypothesis type from SkillLibrary             │
│    2. Invoke CodeAgent with: hypothesis spec + skills + baseline    │
│    3. CodeAgent: blueprints → generates → executes in sandbox       │
│       → invokes eval tool (Promptfoo / DSPy / custom script)        │
│       → captures metric                                             │
│    4. Run regression guard (if configured)                          │
│    5. Write HypothesisResult to tool_runs/<H_id>/result.json       │
│  Writes: results.json  (list of HypothesisResult)                  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AHVS_REPORT_MEMORY (Stage 7)                                       │
│  Reads:  results.json, context_bundle.json, hypotheses.md           │
│  Writes: report.md         (7-question cycle report)                │
│          friction_log.md   (what was slow/painful this cycle)       │
│  Also:   EvolutionStore.append_many(lessons_from_results)          │
│          MetaClaw bridge: promote patterns → skills (if enabled)    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  AHVS_CYCLE_VERIFY (Stage 8)                                        │
│  Reads:  all prior artifacts                                        │
│  Checks: all required files exist, results.json is valid JSON,      │
│          every selected hypothesis has a result entry               │
│  Writes: cycle_summary.json                                         │
│    {                                                                │
│      "cycle_id": "...",                                             │
│      "hypotheses_run": 2,                                           │
│      "hypotheses_improved": 1,                                      │
│      "best_hypothesis": "H1",                                       │
│      "best_delta": +0.06,                                           │
│      "recommendation": "keep H1 — exceeds threshold",              │
│      "next_cycle_suggested": "Explore chunk_size reduction"         │
│    }                                                                │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 4. Key Data Structures

### 4.1 HypothesisResult (`ahvs/result.py`)

The central, tool-agnostic output contract. Every execution path writes this.

```python
@dataclass
class HypothesisResult:
    hypothesis_id: str            # "H1", "H2", etc.
    hypothesis_type: str          # "prompt_rewrite", "architecture_change", etc.
    primary_metric: str           # metric name from baseline_metric.json
    metric_value: float           # measured value
    baseline_value: float         # from baseline_metric.json
    delta: float                  # metric_value - baseline_value
    delta_pct: float              # (delta / baseline_value) * 100
    regression_guard_passed: bool # True if guard script exited 0, or not configured
    eval_method: str              # "promptfoo", "phoenix", "custom_script", "dspy+promptfoo"
    skill_used: str | None        # skill name invoked by CodeAgent, if any
    artifact_paths: list[str]     # what was generated (relative to cycle dir)
    raw_output_path: str          # full eval output for audit
    duration_seconds: float       # wall time for this hypothesis
    error: str | None             # None on success
    kept: bool = False            # set by operator after human review
```

### 4.2 AHVSConfig (`ahvs/config.py`)

```python
@dataclass
class AHVSConfig:
    # Target
    repo_path: Path               # absolute path to target repo
    question: str                 # the cycle question

    # Cycle settings
    run_dir: Path                 # defaults to <repo_path>/.ahvs/cycles/<timestamp>
    max_hypotheses: int = 3       # soft default; hard max is 5

    # Guards
    regression_guard_path: Path | None = None

    # Skill system
    skill_registry_path: Path | None = None  # custom skill registry YAML

    # ARC infrastructure (reused)
    llm_config: RCConfig = field(default_factory=RCConfig.default)
    code_agent_config: CodeAgentConfig = field(default_factory=CodeAgentConfig)
```

### 4.3 SkillSpec (`ahvs/skills.py`)

```python
@dataclass(frozen=True)
class SkillSpec:
    name: str                    # "promptfoo_eval", "sandbox_run", "regression_guard"
    description: str             # shown to CodeAgent in context
    invocation_template: str     # template CodeAgent can reference in its plan
    applicable_types: tuple[str, ...]  # hypothesis types this skill applies to
    required_tools: tuple[str, ...]    # tools that must be installed
```

The built-in skill library:

| Skill Name | Applies To | Required Tools |
|---|---|---|
| `promptfoo_eval` | `prompt_rewrite`, `model_comparison`, `config_change` | `promptfoo` |
| `dspy_compile` | `dspy_optimize` | `dspy`, `promptfoo` |
| `phoenix_eval` | any | `arize-phoenix` |
| `sandbox_run` | `code_change`, `architecture_change`, `multi_llm_judge` | `docker` or sandbox |
| `regression_guard` | all | configured `regression_guard_path` |
| `metric_capture` | all | none (stdlib) |

---

## 5. Implementation Phases

### Phase 1 — Foundation (~1 day)

Create the `ahvs/` subpackage skeleton. All files are new; no existing files change.

#### 5.1.1 `researchclaw/ahvs/__init__.py`
```python
"""AHVS — Adaptive Hypothesis Validation System built on ARC."""
from researchclaw.ahvs.runner import execute_ahvs_cycle
from researchclaw.ahvs.config import AHVSConfig
__all__ = ["execute_ahvs_cycle", "AHVSConfig"]
```

#### 5.1.2 `researchclaw/ahvs/stages.py`

- `AHVSStage(IntEnum)` — 8 values as shown in Section 2
- `AHVS_STAGE_SEQUENCE: tuple[AHVSStage, ...]`
- `AHVS_GATE_STAGES: frozenset[AHVSStage]` — `{AHVS_HUMAN_SELECTION}`
- `AHVS_GATE_ROLLBACK: dict[AHVSStage, AHVSStage]` — `{AHVS_HUMAN_SELECTION: AHVS_HYPOTHESIS_GEN}`
- Reuse `StageStatus`, `TransitionEvent`, `TransitionOutcome`, `advance()` from `pipeline/stages.py` — they are stage-type-agnostic

#### 5.1.3 `researchclaw/ahvs/contracts.py`

Follow the exact same `StageContract` pattern from `pipeline/contracts.py`.

```python
AHVS_CONTRACTS: dict[AHVSStage, StageContract] = {
    AHVSStage.AHVS_SETUP: StageContract(
        stage=AHVSStage.AHVS_SETUP,
        input_files=(".ahvs/baseline_metric.json",),
        output_files=("cycle_manifest.json",),
        dod="Baseline file valid, cycle directory created, tools verified",
        error_code="EA01_SETUP_FAIL",
        max_retries=0,
    ),
    AHVSStage.AHVS_CONTEXT_LOAD: StageContract(
        stage=AHVSStage.AHVS_CONTEXT_LOAD,
        input_files=(".ahvs/baseline_metric.json",),
        output_files=("context_bundle.json",),
        dod="context_bundle.json written with baseline, lessons, and rejected approaches",
        error_code="EA02_CONTEXT_FAIL",
    ),
    AHVSStage.AHVS_HYPOTHESIS_GEN: StageContract(
        stage=AHVSStage.AHVS_HYPOTHESIS_GEN,
        input_files=("context_bundle.json",),
        output_files=("hypotheses.md",),
        dod="1–5 typed hypotheses with id, type, description, rationale, required_tools",
        error_code="EA03_HYP_FAIL",
    ),
    AHVSStage.AHVS_HUMAN_SELECTION: StageContract(
        stage=AHVSStage.AHVS_HUMAN_SELECTION,
        input_files=("hypotheses.md",),
        output_files=("selection.md",),
        dod="Human has selected hypotheses to run; selection.md written",
        error_code="EA04_GATE_REJECT",
        max_retries=0,
    ),
    AHVSStage.AHVS_VALIDATION_PLAN: StageContract(
        stage=AHVSStage.AHVS_VALIDATION_PLAN,
        input_files=("context_bundle.json", "selection.md", "hypotheses.md"),
        output_files=("validation_plan.md",),
        dod="Per-hypothesis implementation spec and eval method defined",
        error_code="EA05_PLAN_FAIL",
    ),
    AHVSStage.AHVS_EXECUTION: StageContract(
        stage=AHVSStage.AHVS_EXECUTION,
        input_files=("validation_plan.md", "selection.md"),
        output_files=("results.json", "tool_runs/"),
        dod="Every selected hypothesis has a HypothesisResult in results.json",
        error_code="EA06_EXEC_FAIL",
        max_retries=1,
    ),
    AHVSStage.AHVS_REPORT_MEMORY: StageContract(
        stage=AHVSStage.AHVS_REPORT_MEMORY,
        input_files=("results.json", "context_bundle.json"),
        output_files=("report.md", "friction_log.md"),
        dod="Cycle report written; lessons archived to EvolutionStore",
        error_code="EA07_REPORT_FAIL",
    ),
    AHVSStage.AHVS_CYCLE_VERIFY: StageContract(
        stage=AHVSStage.AHVS_CYCLE_VERIFY,
        input_files=("results.json", "report.md"),
        output_files=("cycle_summary.json",),
        dod="All artifacts present and valid; cycle_summary.json written",
        error_code="EA08_VERIFY_FAIL",
    ),
}
```

#### 5.1.4 `researchclaw/ahvs/result.py`
- `HypothesisResult` dataclass (see Section 4.1)
- `load_results(path: Path) -> list[HypothesisResult]`
- `save_results(results: list[HypothesisResult], path: Path) -> None`

#### 5.1.5 `researchclaw/ahvs/config.py`
- `AHVSConfig` dataclass (see Section 4.2)
- `AHVSConfig.from_cli_args(args)` — construct from argparse namespace
- `AHVSConfig.validate()` — raise `ValueError` on bad config

---

### Phase 2 — Context & Health (~0.5 day)

#### 5.2.1 `researchclaw/ahvs/context_loader.py`

Core logic:
```python
def load_context_bundle(
    repo_path: Path,
    question: str,
    evolution_dir: Path,
) -> dict:
    """Build context_bundle.json from baseline + EvolutionStore."""
    baseline = _load_baseline_metric(repo_path / ".ahvs" / "baseline_metric.json")
    store = EvolutionStore(evolution_dir)
    overlay = store.build_overlay("ahvs_hypothesis_gen", max_lessons=10)
    rejected = _extract_rejected(overlay)
    prior_lessons = _extract_lessons(overlay)
    return {
        "question": question,
        "baseline": baseline,
        "prior_lessons": prior_lessons,
        "rejected_approaches": rejected,
        "domain_tags": _infer_domain_tags(repo_path),
        "generated_at": _utcnow_iso(),
    }
```

`_infer_domain_tags()` scans the repo's `pyproject.toml` / `requirements.txt` / `package.json` to detect whether it's an LLM, RAG, ML, or general Python repo. This informs hypothesis type suggestions.

#### 5.2.2 `researchclaw/ahvs/health.py`

Extends ARC's `CheckResult` pattern:

```python
HYPOTHESIS_TOOL_REQUIREMENTS: dict[str, list[str]] = {
    "prompt_rewrite":      ["promptfoo"],
    "model_comparison":    ["promptfoo"],
    "config_change":       ["promptfoo"],
    "dspy_optimize":       ["dspy", "promptfoo"],
    "phoenix_eval":        ["arize-phoenix"],
    "code_change":         ["docker"],
    "architecture_change": ["docker"],
}

def check_tool(name: str) -> CheckResult:
    """Generic: CLI tool, Python package, or Node package."""
    # CLI: shutil.which(name)
    # Python: importlib.util.find_spec(name)
    # Node (promptfoo): shutil.which("promptfoo") or shutil.which("npx")

def check_baseline_metric(repo_path: Path) -> CheckResult:
    """Validates .ahvs/baseline_metric.json exists and has required fields."""

def check_regression_guard(guard_path: Path) -> CheckResult:
    """Validates regression_guard.sh exists and is executable."""

def check_clean_branch() -> CheckResult:
    """git status --porcelain — warns if dirty."""

def run_ahvs_preflight(config: AHVSConfig, hypothesis_types: list[str]) -> DoctorReport:
    """Run only the checks needed for the selected hypothesis types."""
    checks = [check_baseline_metric(config.repo_path)]
    required_tools = set()
    for h_type in hypothesis_types:
        required_tools.update(HYPOTHESIS_TOOL_REQUIREMENTS.get(h_type, []))
    for tool in required_tools:
        checks.append(check_tool(tool))
    if config.regression_guard_path:
        checks.append(check_regression_guard(config.regression_guard_path))
    checks.append(check_clean_branch())
    return DoctorReport(...)
```

Note: Pre-flight runs **twice** — once at `AHVS_SETUP` (minimal: baseline + LLM), then again at `AHVS_VALIDATION_PLAN` completion (full: all tools for selected hypothesis types). The second check happens after human selection so it only validates tools the selected hypotheses actually need.

---

### Phase 3 — Skill Library (~0.5 day)

#### 5.3.1 `researchclaw/ahvs/skills.py`

```python
BUILTIN_SKILLS: list[SkillSpec] = [
    SkillSpec(
        name="promptfoo_eval",
        description=(
            "Run a Promptfoo evaluation against a YAML config. Returns normalized "
            "metric value. Use for: prompt_rewrite, model_comparison, config_change."
        ),
        invocation_template=(
            "SKILL promptfoo_eval\n"
            "  config_path: <path to promptfoo YAML>\n"
            "  metric_key: <name of metric to extract from output>\n"
            "  output_path: tool_runs/{hypothesis_id}/promptfoo_output.json"
        ),
        applicable_types=("prompt_rewrite", "model_comparison", "config_change"),
        required_tools=("promptfoo",),
    ),
    SkillSpec(
        name="dspy_compile",
        description=(
            "Run DSPy optimization on a module, then run Promptfoo held-out eval. "
            "Two-step: compile → eval. Use for: dspy_optimize."
        ),
        invocation_template=(
            "SKILL dspy_compile\n"
            "  module_path: <path to DSPy module>\n"
            "  optimizer: BootstrapFewShot\n"
            "  then: promptfoo_eval\n"
            "  config_path: <path to held-out Promptfoo config>"
        ),
        applicable_types=("dspy_optimize",),
        required_tools=("dspy", "promptfoo"),
    ),
    SkillSpec(
        name="sandbox_run",
        description=(
            "Execute a Python script in an isolated sandbox and capture stdout as "
            "JSON metrics. Use for: code_change, architecture_change, multi_llm_judge."
        ),
        invocation_template=(
            "SKILL sandbox_run\n"
            "  entry_point: <path to Python script>\n"
            "  output_schema: {primary_metric: float, ...}\n"
            "  timeout_seconds: 300"
        ),
        applicable_types=("code_change", "architecture_change", "multi_llm_judge"),
        required_tools=("docker",),
    ),
    SkillSpec(
        name="regression_guard",
        description=(
            "Run the regression guard script against results. Exit 0 = pass. "
            "Always invoke after hypothesis execution."
        ),
        invocation_template=(
            "SKILL regression_guard\n"
            "  results_path: tool_runs/{hypothesis_id}/result.json\n"
            "  guard_script: {regression_guard_path}"
        ),
        applicable_types=("*",),    # all types
        required_tools=(),
    ),
]


class SkillLibrary:
    def __init__(self, custom_path: Path | None = None):
        self.skills = list(BUILTIN_SKILLS)
        if custom_path and custom_path.exists():
            self.skills.extend(self._load_custom(custom_path))

    def for_hypothesis_type(self, h_type: str, available_tools: set[str]) -> list[SkillSpec]:
        """Return skills applicable to this type whose tools are all available."""
        return [
            s for s in self.skills
            if (h_type in s.applicable_types or "*" in s.applicable_types)
            and all(t in available_tools for t in s.required_tools)
        ]

    def to_context_block(self, skills: list[SkillSpec]) -> str:
        """Render skills as a context block for CodeAgent injection."""
        ...
```

The skill context block injected into CodeAgent looks like:
```
=== AVAILABLE SKILLS ===
You may invoke these skills in your implementation plan.
Reference them by name in your plan; the executor will resolve them.

SKILL: promptfoo_eval
  Description: Run a Promptfoo evaluation against a YAML config...
  When to use: prompt_rewrite, model_comparison, config_change hypotheses
  Template:
    SKILL promptfoo_eval
      config_path: <path to promptfoo YAML>
      metric_key: answer_relevance
      output_path: tool_runs/H1/promptfoo_output.json
...
```

---

### Phase 4 — Stage Executors (~1 day)

#### 5.4.1 `researchclaw/ahvs/executor.py`

```python
def execute_ahvs_stage(
    stage: AHVSStage,
    *,
    cycle_dir: Path,
    config: AHVSConfig,
    skill_library: SkillLibrary,
) -> StageResult:
    """Dispatch to the appropriate stage handler."""
    handlers = {
        AHVSStage.AHVS_SETUP:           _execute_setup,
        AHVSStage.AHVS_CONTEXT_LOAD:    _execute_context_load,
        AHVSStage.AHVS_HYPOTHESIS_GEN:  _execute_hypothesis_gen,
        AHVSStage.AHVS_HUMAN_SELECTION: _execute_human_selection,
        AHVSStage.AHVS_VALIDATION_PLAN: _execute_validation_plan,
        AHVSStage.AHVS_EXECUTION:       _execute_hypotheses,
        AHVSStage.AHVS_REPORT_MEMORY:   _execute_report_and_memory,
        AHVSStage.AHVS_CYCLE_VERIFY:    _execute_cycle_verify,
    }
    return handlers[stage](cycle_dir=cycle_dir, config=config, skill_library=skill_library)
```

**`_execute_setup`**
1. Validate `baseline_metric.json` exists and has required fields
2. Create `cycle_dir` directory tree
3. Run minimal pre-flight (LLM connectivity, baseline validity)
4. Write `cycle_manifest.json`
5. Return `StageResult(status=DONE, artifacts=["cycle_manifest.json"])`

**`_execute_context_load`**
1. Call `context_loader.load_context_bundle(repo_path, question, evolution_dir)`
2. Write result to `cycle_dir/context_bundle.json`
3. Return `StageResult(status=DONE, artifacts=["context_bundle.json"])`

**`_execute_hypothesis_gen`**
1. Load `context_bundle.json`
2. Load `ahvs_hypothesis_gen` prompt from `PromptManager`
3. Build prompt: inject question, baseline, prior lessons, rejected approaches, domain tags
4. Call LLM, parse response into typed hypotheses
5. Enforce cap: if > 5 hypotheses, truncate and log warning
6. Write `hypotheses.md`
7. Return `StageResult(status=DONE, artifacts=["hypotheses.md"])`

**`_execute_human_selection`** (Gate stage)
1. Read `hypotheses.md`
2. Display to operator (print to stdout in rich format)
3. Wait for input: operator types which hypothesis IDs to run (or `all` / `none`)
4. Also accept a JSON file path if running non-interactively (`--select-file`)
5. Write `selection.md`
6. Run secondary pre-flight for selected hypothesis types (tool availability)
7. Return `StageResult(status=DONE, artifacts=["selection.md"])`

Note: `auto_approve_gates=True` selects all hypotheses automatically (useful for testing).

**`_execute_validation_plan`**
1. Load `context_bundle.json`, `selection.md`, `hypotheses.md`
2. Load `ahvs_validation_plan` prompt from `PromptManager`
3. For each selected hypothesis, generate implementation spec + eval method
4. Resolve available skills per hypothesis type (from `SkillLibrary`)
5. Write `validation_plan.md` (includes skill context per hypothesis)
6. Return `StageResult(status=DONE, artifacts=["validation_plan.md"])`

**`_execute_hypotheses`** (The core loop)
```python
def _execute_hypotheses(cycle_dir, config, skill_library):
    selection = _load_selection(cycle_dir / "selection.md")
    plan = _load_validation_plan(cycle_dir / "validation_plan.md")
    baseline = _load_baseline(config.repo_path)
    results = []

    for hyp_id in selection.selected:
        hyp_plan = plan.for_hypothesis(hyp_id)
        skills = skill_library.for_hypothesis_type(
            hyp_plan.hypothesis_type,
            available_tools=_detect_available_tools()
        )
        skill_context = skill_library.to_context_block(skills)

        # Invoke CodeAgent with hypothesis spec + skills
        code_agent_result = _invoke_code_agent(
            problem=hyp_plan.to_code_agent_prompt(),
            skill_context=skill_context,
            work_dir=cycle_dir / "tool_runs" / hyp_id,
            config=config,
        )

        # Parse CodeAgent's metric output into HypothesisResult
        metric_value = _extract_metric(code_agent_result, hyp_plan.primary_metric)
        guard_passed = _run_regression_guard(
            config.regression_guard_path,
            cycle_dir / "tool_runs" / hyp_id / "result.json"
        )

        results.append(HypothesisResult(
            hypothesis_id=hyp_id,
            hypothesis_type=hyp_plan.hypothesis_type,
            primary_metric=hyp_plan.primary_metric,
            metric_value=metric_value,
            baseline_value=baseline.value,
            delta=metric_value - baseline.value,
            delta_pct=((metric_value - baseline.value) / baseline.value) * 100,
            regression_guard_passed=guard_passed,
            eval_method=hyp_plan.eval_method,
            skill_used=code_agent_result.skill_used,
            artifact_paths=code_agent_result.artifact_paths,
            raw_output_path=str(cycle_dir / "tool_runs" / hyp_id),
            duration_seconds=code_agent_result.duration,
            error=code_agent_result.error,
        ))

    save_results(results, cycle_dir / "results.json")
    return StageResult(status=DONE, artifacts=["results.json", "tool_runs/"])
```

**`_execute_report_and_memory`**
1. Load `results.json`, `context_bundle.json`, `hypotheses.md`
2. Load `ahvs_report` prompt from `PromptManager`
3. Build report context: baseline, results, deltas, best hypothesis
4. Call LLM → write `report.md`
5. Write `friction_log.md` (template + any errors captured during execution)
6. Extract lessons from results and archive to `EvolutionStore`:
   - Winning hypotheses → `EXPERIMENT` category, `info` severity
   - Failed hypotheses → `EXPERIMENT` category, `warning` severity
   - Rejected approaches → `EXPERIMENT` category, tagged for future recall
7. Trigger MetaClaw bridge (non-blocking, same pattern as `runner.py`)
8. Return `StageResult(status=DONE, artifacts=["report.md", "friction_log.md"])`

**`_execute_cycle_verify`**
1. Load contract for each completed stage
2. Verify all `output_files` exist in `cycle_dir`
3. Validate `results.json` is parseable as `list[HypothesisResult]`
4. Verify every selected hypothesis has a result entry
5. Compute `cycle_summary.json` (best hypothesis, recommendation, next cycle suggestion)
6. Return `StageResult(status=DONE, artifacts=["cycle_summary.json"])`

---

### Phase 5 — Runner + CLI (~0.5 day)

#### 5.5.1 `researchclaw/ahvs/runner.py`

```python
def execute_ahvs_cycle(
    *,
    config: AHVSConfig,
    auto_approve_gates: bool = False,
) -> list[StageResult]:
    """Execute one AHVS hypothesis-validation cycle."""
    cycle_dir = config.run_dir
    cycle_dir.mkdir(parents=True, exist_ok=True)
    run_id = _generate_cycle_id(config.question)

    skill_library = SkillLibrary(config.skill_registry_path)
    results = []

    for stage in AHVS_STAGE_SEQUENCE:
        print(f"[{run_id}] AHVS Stage {int(stage):02d}/{len(AHVS_STAGE_SEQUENCE)} "
              f"{stage.name} — running...")
        t0 = time.monotonic()

        result = execute_ahvs_stage(
            stage,
            cycle_dir=cycle_dir,
            config=config,
            skill_library=skill_library,
        )
        elapsed = time.monotonic() - t0

        # Gate handling: AHVS_HUMAN_SELECTION pauses for operator input
        # (handled inside _execute_human_selection via stdin)
        # auto_approve_gates bypasses the wait and selects all hypotheses

        _write_ahvs_checkpoint(cycle_dir, stage, run_id)
        results.append(result)

        if result.status == StageStatus.FAILED:
            break

    return results
```

#### 5.5.2 `researchclaw/cli.py` — add `ahvs` subcommand

```python
# Add to existing argparse setup:

ahvs_parser = subparsers.add_parser("ahvs", help="Run an AHVS hypothesis-validation cycle")
ahvs_parser.add_argument("--repo", required=True, help="Path to target repo root")
ahvs_parser.add_argument("--question", required=True, help="The cycle question")
ahvs_parser.add_argument("--config", default=None, help="ARC config path (for LLM settings)")
ahvs_parser.add_argument("--max-hypotheses", type=int, default=3)
ahvs_parser.add_argument("--regression-guard", default=None)
ahvs_parser.add_argument("--auto-approve", action="store_true")
ahvs_parser.add_argument("--select-file", default=None, help="JSON file with hypothesis selection (non-interactive)")
ahvs_parser.add_argument("--skill-registry", default=None, help="Custom skill registry YAML")

def cmd_ahvs(args):
    config = AHVSConfig.from_cli_args(args)
    results = execute_ahvs_cycle(config=config, auto_approve_gates=args.auto_approve)
    _print_ahvs_summary(results)
    return 0 if all(r.status == StageStatus.DONE for r in results) else 1
```

---

### Phase 6 — Prompt Blocks (~0.5 day)

Four new blocks in `prompts.default.yaml`:

#### `ahvs_hypothesis_gen`

Instructs the LLM to generate typed hypotheses. Key constraints to include in the prompt:
- Must output each hypothesis with: id, type, description, rationale, estimated_cost, required_tools
- Type must be one of the defined taxonomy
- Hard cap: maximum 5 hypotheses
- Must avoid approaches listed in `rejected_approaches` from context_bundle
- Rationale must reference the baseline metric and explain why this hypothesis might improve it

#### `ahvs_validation_plan`

Per selected hypothesis, generates:
- `implementation_approach`: narrative of what CodeAgent should build
- `eval_method`: which skill/tool to use and why
- `success_criterion`: concrete metric threshold (absolute or relative)
- `estimated_artifacts`: list of files to produce

#### `ahvs_context_load`

Generates the domain context section of `context_bundle.json`:
- Infers repo purpose from README/pyproject.toml
- Identifies LLM surface points (which files contain prompts, models, retrievers)
- Suggests hypothesis domains relevant to this codebase

#### `ahvs_report`

Answers the 7 AHVS reporting questions:
1. What was the question this cycle?
2. What hypotheses were run?
3. What were the results vs baseline?
4. Which hypothesis (if any) should be kept?
5. What was learned (regardless of outcome)?
6. What approaches were ruled out?
7. What should the next cycle explore?

---

## 6. File Change Summary

| File | Type | Phase | Description |
|---|---|---|---|
| `researchclaw/ahvs/__init__.py` | New | 1 | Package entry; exports `execute_ahvs_cycle`, `AHVSConfig` |
| `researchclaw/ahvs/stages.py` | New | 1 | `AHVSStage` enum, `AHVS_STAGE_SEQUENCE`, gate/rollback dicts |
| `researchclaw/ahvs/contracts.py` | New | 1 | 8 `StageContract` instances for AHVS stages |
| `researchclaw/ahvs/result.py` | New | 1 | `HypothesisResult` dataclass, load/save helpers |
| `researchclaw/ahvs/config.py` | New | 1 | `AHVSConfig` dataclass with validation |
| `researchclaw/ahvs/context_loader.py` | New | 2 | `load_context_bundle()` — EvolutionStore + baseline |
| `researchclaw/ahvs/health.py` | New | 2 | `HYPOTHESIS_TOOL_REQUIREMENTS`, `check_tool()`, `run_ahvs_preflight()` |
| `researchclaw/ahvs/skills.py` | New | 3 | `SkillSpec`, `SkillLibrary`, built-in skill registry |
| `researchclaw/ahvs/executor.py` | New | 4 | `execute_ahvs_stage()` + 8 handler functions |
| `researchclaw/ahvs/runner.py` | New | 5 | `execute_ahvs_cycle()` — cycle orchestrator |
| `researchclaw/cli.py` | Modify | 5 | Add `ahvs` subcommand (additive only) |
| `prompts.default.yaml` | Modify | 6 | 4 new prompt blocks (additive only) |

**Existing ARC files modified: 2** (`cli.py`, `prompts.default.yaml` — both additive only).
**New files: 10** (entirely within `researchclaw/ahvs/`).

---

## 7. Testing Strategy

### Unit tests (per-file, fast)

| Test file | Tests |
|---|---|
| `tests/ahvs/test_stages.py` | AHVSStage ordering, gate detection, rollback mapping |
| `tests/ahvs/test_contracts.py` | All 8 contracts exist, input/output files non-empty |
| `tests/ahvs/test_result.py` | `HypothesisResult` serialization round-trip, delta calculation |
| `tests/ahvs/test_health.py` | `check_tool()` with mock shutil.which, baseline validation |
| `tests/ahvs/test_skills.py` | Skill filtering by type and available tools, context block rendering |
| `tests/ahvs/test_context_loader.py` | Mock EvolutionStore, verify context_bundle structure |

### Integration tests (slower, require LLM mock)

| Test | Description |
|---|---|
| `test_hypothesis_gen_prompt` | Full stage 3 with mocked LLM — verify output parses to typed hypotheses |
| `test_validation_plan_prompt` | Full stage 5 with mocked LLM — verify plan has implementation spec |
| `test_execution_with_mock_code_agent` | Stage 6 with mocked CodeAgent — verify HypothesisResult written |
| `test_full_cycle_dry_run` | All 8 stages with mocked LLM + CodeAgent + `auto_approve_gates=True` |

### Smoke test (manual, first run)

```bash
# Prerequisites: install promptfoo, set .ahvs/baseline_metric.json in test repo
researchclaw ahvs \
  --repo /path/to/test-llm-repo \
  --question "Does adding 2 examples improve answer relevance?" \
  --max-hypotheses 2 \
  --auto-approve \
  --config researchclaw.yaml
```

Expected: cycle runs end-to-end, `cycle_summary.json` written, EvolutionStore populated.

---

## 8. Estimated Line Counts

| File | Estimated Lines |
|---|---|
| `ahvs/stages.py` | ~60 |
| `ahvs/contracts.py` | ~80 |
| `ahvs/result.py` | ~50 |
| `ahvs/config.py` | ~60 |
| `ahvs/context_loader.py` | ~80 |
| `ahvs/health.py` | ~100 |
| `ahvs/skills.py` | ~120 |
| `ahvs/executor.py` | ~350 |
| `ahvs/runner.py` | ~80 |
| `cli.py` additions | ~40 |
| `prompts.default.yaml` additions | ~200 |
| **Total** | **~1,220 lines** |

This is lean. The bulk (~350 lines) is `executor.py` — 8 handler functions averaging 40 lines each. Everything else is data definitions, configuration, and prompts.

---

## 9. What Comes Out of the Box for Free (Zero Lines)

These ARC components are used directly, unchanged:

- `EvolutionStore` — memory layer (context loading, lesson archival)
- `CodeAgent` — hypothesis implementation engine
- `DockerSandbox` / `LocalSandbox` — execution isolation
- `LLMClient` — LLM calls with fallback chain
- `PromptManager` — prompt loading from `prompts.default.yaml`
- `StageStatus` / `TransitionEvent` / `advance()` — stage state machine
- `StageContract` — I/O contract type
- `CheckResult` / `DoctorReport` — health check pattern
- MetaClaw bridge — lesson-to-skill promotion (already wired in `runner.py`)

---

## 10. Open Questions (Decide Before Implementation)

| Question | Options | Recommendation |
|---|---|---|
| Where does the `evolution/` store live for AHVS? | A) `<repo>/.ahvs/evolution/` B) `~/.ahvs/evolution/<repo_hash>/` | **A** — keeps everything repo-local, consistent with `.ahvs/` convention |
| How does `AHVS_HUMAN_SELECTION` handle non-interactive mode? | A) `--auto-approve` selects all B) `--select-file <json>` provides selection | **Both** — implement both; `--auto-approve` for CI, `--select-file` for scripted workflows |
| Should skills be YAML-only or also Python-registered? | A) YAML only B) YAML + Python plugin API | **A for V1** — YAML is sufficient; Python plugin API is a V2 concern |
| How does CodeAgent signal which skill it used? | A) Parse plan output B) CodeAgent writes `skill_used.json` | **B** — more reliable; add `skill_used.json` to CodeAgent's output contract for AHVS runs |

---

## 11. Implementation Order (Day-by-Day)

```
Day 1 AM:  Phase 1 — Foundation (stages, contracts, result, config)
Day 1 PM:  Phase 2 — Context loader + health checks
Day 2 AM:  Phase 3 — Skill library
Day 2 PM:  Phase 4 — Executor (stages 1-5: setup through validation plan)
Day 3 AM:  Phase 4 — Executor (stages 6-8: execution through verify)
Day 3 PM:  Phase 5 — Runner + CLI
Day 4 AM:  Phase 6 — Prompt blocks
Day 4 PM:  Unit tests + smoke test
```

4 days total for a working V1.
