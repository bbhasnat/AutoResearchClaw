# AHVS Automatic Plan (V7) — AutoResearchClaw Adaptation Analysis

**Date:** 2026-03-17
**Branch:** avhs_man_llm
**Purpose:** Map the AHVS Automatic Plan V7 onto AutoResearchClaw and determine what ARC provides, what it cannot provide, and the most honest path forward.

---

## 1. Executive Summary

The AHVS Automatic Plan and AutoResearchClaw serve different but complementary purposes.

**AutoResearchClaw** is an autonomous *execution pipeline* — it takes a research idea and produces a paper. It excels at execution: literature search, code generation, experiment running, and report writing. It has no awareness of *strategy*, *autonomy level*, or *cross-cycle improvement*.

**AHVS Automatic** is an autonomous *improvement engine* — it takes a target system (any pipeline with a measurable metric) and systematically finds better configurations through hypothesis-driven experimentation. It excels at coordination, knowledge accumulation, progressive autonomy, and budget discipline. It has no execution infrastructure of its own.

The relationship is: **AHVS is the brain, ARC is the hands.**

ARC covers approximately **35% of the AHVS Automatic Plan** — specifically the execution infrastructure (experiment backends, agent framework, LLM client, knowledge storage) that plugs into AHVS's `PipelineAdapter` interface. The remaining 65% — the progressive autonomy ladder, confidence class system, Claude Agent SDK coordinator loop, hook system, MLflow/Optuna integration, and shadow scoring — does not exist in ARC and cannot be approximated by it.

This is a fundamentally different alignment situation from the manual LLM plan. The manual plan was largely solvable by repurposing ARC's internals. The automatic plan requires ARC to be a *component inside a larger system*, not the system itself.

---

## 2. What AHVS Automatic Needs vs. What ARC Provides

### 2.1 The AHVS Automatic Core Components

The AHVS plan has two clearly separated layers (§2 of the plan):

**Generic framework** (domain-agnostic, always required):
- Coordinator Agent (Claude Agent SDK loop, subagent spawning)
- Progressive Autonomy Ladder (L0–L3, promotion/demotion criteria)
- Discrete Confidence Class System (5-class, calibration tracking, decision routing)
- Hook System (GateEnforcer, BudgetGuard, SafetyChecker, ResultLogger, ReviewCadenceEnforcer)
- Knowledge Store (ClawVault with BM25+semantic search, entity graph, trust scoring, rejection learning)
- MLflow integration (always-on experiment tracking)
- Optuna integration (numeric parameter optimization)
- DSPy + Promptfoo execution backends (LLM/prompt hypothesis evaluation)
- AIDE tree-search (configuration variation exploration)
- Shadow scoring / agreement rate tracking (L2+ audit)
- Reporting (gate reports, final reports, log-to-report mapping)

**Adapter-specific** (changes per domain):
- `PipelineAdapter` implementation (7-method ABC)
- Bootstrap strategy taxonomy
- Domain hypothesis space
- Cost estimation formula
- Constraint definitions
- Pipeline entry point

### 2.2 Direct Mapping Table

| AHVS Component | ARC Equivalent | Coverage | Notes |
|---|---|---|---|
| **Multi-agent subagent framework** | `agents/base.py` — `BaseAgent` + `AgentOrchestrator` | **Direct** | AHVS's 5 subagents (Onboarding, Hypothesis, Experiment, Review, Promotion) map cleanly to ARC's BaseAgent subclasses |
| **Experiment execution backend** | `experiment/sandbox.py`, `docker_sandbox.py`, `ssh_sandbox.py`, `colab_sandbox.py` | **Direct** | These implement `PipelineAdapter.run_experiment()` for any Python-based pipeline |
| **Code generation / structural mutation** | `pipeline/code_agent.py` — Phase 4 tree search | **Direct** | ARC's CodeAgent AIDE-style tree search directly implements AHVS's `structural` hypothesis type |
| **LLM client with fallback chain** | `llm/client.py` | **Direct** | Used by all AHVS subagents |
| **Prompt externalization** | `prompts.default.yaml` + `prompts.py` | **Direct** | Powers AHVS hypothesis generation prompts |
| **Local knowledge storage** | `evolution.py` — `EvolutionStore` | **Partial** | Time-weighted lesson storage exists; BM25+semantic search does not |
| **Gate / human checkpoint** | `pipeline/runner.py` gate stages | **Partial** | Gate pattern exists but is not tied to autonomy level or confidence class |
| **Artifact contract validation** | `pipeline/contracts.py` | **Partial** | Validates stage output files; not equivalent to AHVS's hook system |
| **Report generation** | Stage 17 `PAPER_DRAFT` + Stage 18 `PEER_REVIEW` | **Partial** | ARC generates academic paper sections; gate/final reports need different prompts |
| **Literature discovery (for onboarding)** | Stages 3–6 (search, collect, screen, extract) | **Partial** | Can implement `PipelineAdapter.discover_contract()` for research-domain adapters |
| **Cross-run knowledge** | `metaclaw_bridge/` | **Partial** | Lesson extraction exists; no global vault, no BM25+semantic search |
| **Progressive Autonomy Ladder** | — | **None** | L0–L3 with promotion/demotion criteria does not exist in ARC |
| **Discrete Confidence Classes** | — | **None** | 5-class system + decision routing + calibration tracking is not in ARC |
| **Claude Agent SDK coordinator loop** | — | **None** | ARC uses its own `pipeline/runner.py` sequential executor, not Claude Agent SDK |
| **Hook system** | — | **None** | GateEnforcer, BudgetGuard, SafetyChecker, ResultLogger, ReviewCadenceEnforcer are not in ARC |
| **MLflow integration** | — | **None** | ARC uses run directories and JSON files; no MLflow |
| **Optuna integration** | — | **None** | No Bayesian hyperparameter search in ARC |
| **ClawVault BM25+semantic search** | — | **None** | ARC's `EvolutionStore` uses time-weighted recall, not hybrid search |
| **Shadow scoring / agreement rate** | — | **None** | No autonomy audit mechanism in ARC |
| **Budget tracking per hypothesis** | — | **None** | ARC has no per-call cost tracking or per-hypothesis budget accumulation |
| **Rejection learning** | — | **None** | No structured rejection reason system (`REJECTION_REASONS` categories) |
| **PipelineAdapter ABC** | — | **None** | ARC's pipeline is hardcoded to academic research; no adapter abstraction |
| **Global cross-repo knowledge vault** | `metaclaw_bridge/` (partial) | **Partial** | MetaClaw bridges exist but serve a different purpose; no `blackbird-ahvs-knowledge` global vault |

---

## 3. The Correct Mental Model

ARC is not a near-complete implementation of AHVS Automatic that just needs a few additions. The two systems operate at different architectural levels.

```
AHVS Automatic Plan
├── Coordinator Agent (Claude Agent SDK)        ← NOT in ARC
│   ├── Autonomy Ladder (L0-L3)                 ← NOT in ARC
│   ├── Confidence Class System                 ← NOT in ARC
│   ├── Hook System (5 hooks)                   ← NOT in ARC
│   └── 5 Subagents:
│       ├── Onboarding Subagent
│       │   └── discover_contract() ←─────────────── ARC: Stages 3-6 (literature, extract)
│       ├── Hypothesis Subagent
│       │   └── generate macros ←────────────────── ARC: BaseAgent + Stage 8 prompts
│       ├── Experiment Subagent
│       │   └── run_experiment() ←───────────────── ARC: sandbox/docker/ssh/CodeAgent
│       ├── Review Subagent
│       │   └── gate reports ←───────────────────── ARC: Stage 18 peer_review (adapted)
│       └── Promotion Subagent
│           └── knowledge update ←───────────────── ARC: evolution.py (partial)
├── Infrastructure Layer
│   ├── MLflow ←──────────────────────────────────── NOT in ARC
│   ├── Optuna ←──────────────────────────────────── NOT in ARC
│   ├── Promptfoo ←───────────────────────────────── NOT in ARC
│   ├── DSPy ←────────────────────────────────────── NOT in ARC
│   └── ClawVault (BM25+semantic) ←───────────────── ARC: evolution.py (partial, no search)
└── PipelineAdapter ABC ←─────────────────────────── NOT in ARC
    └── Concrete adapters per domain
```

ARC's components slot into specific positions *inside* the AHVS framework but they do not replace the framework itself.

---

## 4. What ARC Provides as AHVS Components

### 4.1 ARC's Execution Layer → `PipelineAdapter.run_experiment()`

This is ARC's strongest contribution. The AHVS plan requires every domain adapter to implement:

```python
def run_experiment(self, trial_spec: TrialSpec) -> TrialResult
```

ARC provides four production-grade implementations of this concept:
- `sandbox.py` — subprocess with metric parsing, resource limits, NaN/Inf fast-fail
- `docker_sandbox.py` — containerized with GPU passthrough and network policy
- `ssh_sandbox.py` — remote GPU server execution
- `colab_sandbox.py` — Google Colab execution

For any domain where the hypothesis is tested by running a Python script (ML training, data processing, RAG evaluation with custom scripts), ARC's sandbox layer directly implements `run_experiment()`. The `TrialSpec` fields (`pipeline_config`, `eval_fraction`, `seed`) map to environment variables or config file injections that ARC's sandbox system already handles.

**How to wire:** Wrap each ARC sandbox in a thin `PipelineAdapter` subclass that:
1. Translates `TrialSpec.pipeline_config` → a config file or environment override
2. Calls the relevant ARC sandbox
3. Translates ARC's metric output → `TrialResult.metrics`

### 4.2 ARC's CodeAgent Phase 4 → AIDE Tree Search for `structural` Hypotheses

AHVS's `structural` hypothesis type uses AIDE-inspired tree search over code variations. ARC's `CodeAgent` already implements this pattern in Phase 4 (`solution_tree_search`):

- Root node = current implementation
- Child nodes = LLM-generated variations
- Selection = metric-ranked best branch
- Continuation = spawn children from best node

The difference is domain: ARC searches over *experimental Python code*, AHVS searches over *pipeline configs and architecture variants*. The tree-search logic (parent-child lineage, branch selection, `parent_trial_id` tracking) is already built in ARC's `CodeAgent`.

**How to wire:** Extract ARC's tree-search logic from `code_agent.py` Phase 4 into a standalone `TreeSearchEngine` class. The AHVS `structural` hypothesis path calls `TreeSearchEngine.explore(root_config, mutation_fn, score_fn)` where `mutation_fn` and `score_fn` come from the adapter.

### 4.3 ARC's `BaseAgent` + `AgentOrchestrator` → AHVS Subagents

AHVS defines 5 subagent roles (Onboarding, Hypothesis, Experiment, Review, Promotion). Each has a specific tool set and responsibility boundary. ARC's `BaseAgent` class is the right base for implementing each:

```python
# AHVS Hypothesis Subagent → ARC BaseAgent subclass
class HypothesisSubagent(BaseAgent):
    def __init__(self, llm, vault: Vault, adapter: PipelineAdapter):
        super().__init__(llm)
        self._vault = vault
        self._adapter = adapter

    def generate_macros(self, baseline_report: dict, context: dict) -> list[MacroHypothesis]:
        # 1. vault.search() for priors
        # 2. adapter.get_hypothesis_space() for valid mutations
        # 3. LLM call via self._chat() to generate macros
        # 4. Score and rank
        ...
```

ARC's `AgentOrchestrator` handles multi-agent coordination and LLM usage accumulation — the same role as AHVS's Coordinator in routing between subagents.

### 4.4 ARC's `evolution.py` → Local Knowledge Storage (Partial)

ARC's `EvolutionStore` covers the write side of ClawVault:
- `append_many(lessons)` → `vault.remember()`
- `build_overlay(stage)` → approximate `vault.search()` (time-weighted, no BM25)
- Per-stage overlay injection → lesson injection into subagent prompts

It does **not** cover:
- BM25+semantic hybrid search (AHVS needs retrieval-quality search, not just recency-weighted recall)
- Entity graph for strategy trust tracking
- Structured `decisions/`, `tasks/`, `backlog/`, `handoffs/` vault layout
- `vault.wake()` / `vault.sleep()` session lifecycle
- Python SDK interface (`clawvault-py`)

For V1 of AHVS Automatic on top of ARC, `EvolutionStore` is a usable approximation. For V2+, the full ClawVault SDK is needed.

### 4.5 ARC's Literature Pipeline → `discover_contract()` for Research Domains

For an AHVS adapter targeting an LLM or RAG research pipeline, `discover_contract()` needs to:
- Parse the repo structure and identify eval sets, metrics, and entry points
- Understand the current baseline

ARC's Stages 3–6 (search strategy, literature collect, screen, knowledge extract) and Stage 1 (topic decomposition) directly produce the inputs to `TaskContract`. The `TaskContract` fields (`eval_dataset_path`, `baseline_config_path`, `pipeline_entry_point`, `objective_metric`) can be populated by adapting ARC's Stage 1 and Stage 2 outputs.

This is only relevant for adapters in the research/LLM domain. ML training and data processing adapters implement `discover_contract()` differently (reading existing config files, not doing literature search).

---

## 5. What Must Be Built from Scratch

These components do not exist in ARC and cannot be approximated. They are the core of the AHVS Automatic Plan.

### 5.1 Progressive Autonomy Ladder (`autonomy.py`)

The entire L0–L3 system:
- `AutonomyRecord` dataclass per task-family
- `AutonomyPromotion` / `AutonomyDemotion` criteria
- `AutonomyRecord` persistence (per-task-family, not global)
- Integration with `DecisionRouter` so every decision routes through the autonomy check

Estimated size: ~200 lines. Zero ARC overlap.

### 5.2 Discrete Confidence Class System (`confidence.py`)

- `Confidence` enum (5 classes)
- `DecisionRouter` with `ROUTING_TABLE`
- `CalibrationTracker` with per-class outcome counting
- Integration: agent thought traces must include a confidence declaration that the system parses

Estimated size: ~150 lines. Zero ARC overlap.

### 5.3 Claude Agent SDK Coordinator Loop

The Coordinator Agent uses Claude Agent SDK (`claude_agent_sdk.query()`) to run the lifecycle, spawn subagents, and attach hooks. ARC uses its own sequential `pipeline/runner.py` which is not Claude Agent SDK.

This is a **fundamental architectural difference**. ARC's runner cannot be swapped for the Claude Agent SDK coordinator without a rewrite of the orchestration layer. The two models are:
- ARC: deterministic sequential stage executor (Python function calls, checkpoint/resume)
- AHVS: Claude Agent SDK agentic loop (LLM-driven tool selection, hooks, session resumption)

**If the choice is made to use ARC's runner instead of Claude Agent SDK**, the autonomy and confidence system must be implemented as pre/post-stage callbacks in ARC's executor rather than as SDK hooks. This is viable but means the system is no longer "MCP-first" as AHVS §2 requires. That's a deliberate trade-off, not a mistake — but it should be acknowledged.

Estimated size (SDK coordinator): ~300 lines new code. Zero ARC overlap.

Estimated size (ARC runner adaptation): ~150 lines, modifying `executor.py` and `runner.py`.

### 5.4 Hook System (5 Hooks)

`GateEnforcer`, `BudgetGuard`, `SafetyChecker`, `ResultLogger`, `ReviewCadenceEnforcer` — all domain-agnostic hooks that the coordinator attaches.

If using Claude Agent SDK, these are `PreToolUse` / `PostToolUse` hooks.

If using ARC's runner, these become stage-level validation callbacks.

ARC has no equivalent to any of these. `contracts.py` validates artifacts at stage completion but does not implement the real-time enforcement semantics (e.g., `BudgetGuard` blocks an experiment *before* it runs, not after).

Estimated size: ~300 lines. Minimal ARC overlap (ARC's `health.py` preflight is a loose analog to `SafetyChecker`).

### 5.5 MLflow Integration (`tracking/mlflow_backend.py`)

ARC uses flat JSON files and run directories. AHVS requires MLflow as the always-on tracking backend:
- Every trial logged as an MLflow run
- Parent-child hierarchy (macro → micro → trial)
- Per-call cost breakdown artifacts
- Metric history for significance testing

Estimated size: ~100 lines. Zero ARC overlap.

### 5.6 Optuna Integration (`search/optuna_backend.py`)

ARC has no hyperparameter search. AHVS requires Optuna for the `hyperparameter` hypothesis type:
- Study creation per macro
- Trial suggestion (Bayesian, not random)
- Trial result logging back to study
- Study artifact persistence

Estimated size: ~120 lines. Zero ARC overlap.

### 5.7 ClawVault BM25+Semantic Search

ARC's `EvolutionStore` uses time-weighted recency as the retrieval signal. AHVS requires hybrid BM25+semantic search over the vault to find relevant priors across task families and cycles.

For V1, ARC's `EvolutionStore` is a usable approximation. For production AHVS, the `clawvault-py` SDK should be used directly:

```python
from clawvault import Vault
vault = Vault(".ahvs/knowledge/vault")
vault.wake()
results = vault.search("few-shot classification improvement cohort")
```

### 5.8 Shadow Scoring / Agreement Rate Tracking

`ShadowDecision` dataclass, `autonomy_decisions.jsonl` append, periodic audit sampling, `human_would_agree` capture workflow. None of this exists in ARC.

Estimated size: ~100 lines + human audit UX (deferred to when system first reaches L2, per §6.7 of the plan).

### 5.9 `PipelineAdapter` Abstract Base Class

```python
from abc import ABC, abstractmethod

class PipelineAdapter(ABC):
    @abstractmethod
    def discover_contract(self, workspace_path: str) -> TaskContract: ...
    @abstractmethod
    def run_baseline(self, contract: TaskContract) -> TrialResult: ...
    @abstractmethod
    def run_experiment(self, trial_spec: TrialSpec) -> TrialResult: ...
    @abstractmethod
    def validate_mutation(self, mutation: dict, current_config: dict) -> tuple[bool, str]: ...
    @abstractmethod
    def estimate_cost(self, trial_spec: TrialSpec, contract: TaskContract) -> float: ...
    @abstractmethod
    def get_constraints(self, contract: TaskContract) -> dict: ...
    @abstractmethod
    def get_hypothesis_space(self) -> dict: ...
```

This is a new file (`adapters/pipeline_adapter.py`). ARC's existing `adapters.py` contains protocol interfaces for ARC-specific things (Cron, Message, Memory, Sessions) — not the same concept.

Estimated size: ~50 lines for the ABC, then ~200 lines per concrete adapter.

---

## 6. Implementation Path

Unlike the manual plan (where ARC was ~70% complete), the AHVS Automatic Plan is better understood as a new system that **uses ARC components** rather than a system built *on top of* ARC.

Two viable paths:

---

### Path A — ARC as an Adapter Component (Recommended)

Build AHVS Automatic as a standalone system. Wire ARC's execution infrastructure into it as components via the `PipelineAdapter` interface and `BaseAgent` subclasses.

```
ahvs_automatic/
├── coordinator/
│   ├── runner.py           ← NEW: Claude Agent SDK loop or ARC runner adaptation
│   ├── autonomy.py         ← NEW: L0-L3 ladder, promotion/demotion, shadow scoring
│   ├── confidence.py       ← NEW: 5-class system, calibration, decision routing
│   └── hooks.py            ← NEW: 5 hooks
├── subagents/
│   ├── onboarding.py       ← NEW: wraps ARC's BaseAgent + literature stages
│   ├── hypothesis.py       ← NEW: wraps ARC's BaseAgent + Stage 8 prompts
│   ├── experiment.py       ← NEW: wraps ARC's BaseAgent + sandbox backends
│   ├── review.py           ← NEW: wraps ARC's BaseAgent + Stage 18 prompts
│   └── promotion.py        ← NEW: wraps ARC's BaseAgent + evolution.py
├── adapters/
│   ├── pipeline_adapter.py ← NEW: PipelineAdapter ABC (7-method interface)
│   ├── autoqa_adapter.py   ← NEW: first concrete adapter
│   └── arc_adapter.py      ← NEW: adapter that wraps ARC's sandbox layer
├── knowledge/
│   ├── vault.py            ← NEW: ClawVault wrapper (or EvolutionStore for V1)
│   └── trust.py            ← NEW: StrategyNode, trust update rules
├── tracking/
│   ├── mlflow_backend.py   ← NEW
│   └── optuna_backend.py   ← NEW
└── data_types.py           ← NEW: TaskContract, MacroHypothesis, TrialSpec, TrialResult

# ARC is imported as a library:
from researchclaw.agents.base import BaseAgent, AgentOrchestrator
from researchclaw.experiment.sandbox import LocalSandbox
from researchclaw.experiment.docker_sandbox import DockerSandbox
from researchclaw.llm.client import LLMClient
from researchclaw.evolution import EvolutionStore
```

This keeps AHVS Automatic independent and prevents ARC's 23-stage academic pipeline from constraining AHVS's design.

**Estimated new code:** ~2,000–2,500 lines (excluding adapter implementations).
**ARC reuse:** ~800–1,000 lines of ARC components imported and wrapped.

---

### Path B — ARC Runner as the Coordinator (Simpler, Less Faithful to Plan)

Keep ARC's `pipeline/runner.py` as the orchestration backbone. Add new AHVS stages to ARC's `STAGE` enum. Implement the autonomy and confidence system as stage-level callbacks inside ARC's executor.

Trade-offs:
- Faster to build (no new orchestration infrastructure)
- ARC's sequential runner is not Claude Agent SDK — the system is no longer "MCP-first"
- The hook system becomes pre/post-stage callbacks, not SDK hooks
- Session resumption uses ARC's existing checkpoint system (which is production-grade)
- Parallel cycles at L3 would require significant ARC runner changes

New stages for Path B:
```
AHVS_ONBOARDING
AHVS_HYPOTHESIS_GEN        ← gate (L0-L1)
AHVS_SCREENING_FUNNEL      ← loop stage (Stage A + B + C)
AHVS_DEEPENING             ← loop stage
AHVS_REVIEW_GATE           ← periodic gate
AHVS_PROMOTION             ← gate (L0-L2)
AHVS_KNOWLEDGE_UPDATE
```

The autonomy ladder and confidence system become a new `autonomy.py` module called at gate stages in `executor.py`.

**Estimated new code:** ~1,500 lines.
**ARC reuse:** Higher — entire `pipeline/`, `experiment/`, `agents/`, `llm/`, `evolution/` used directly.

---

## 7. Comparison: Manual Plan vs. Automatic Plan Alignment with ARC

| Dimension | Manual LLM Plan | Automatic Plan |
|---|---|---|
| ARC coverage | ~70% | ~35% |
| Orchestration model | ARC's runner (direct fit) | Claude Agent SDK or ARC runner (adaptation required) |
| Knowledge store | ARC's evolution.py (direct fit) | Needs ClawVault BM25+semantic |
| New code required | ~450 lines | ~2,000–2,500 lines |
| New infrastructure | Promptfoo backend only | MLflow + Optuna + hooks + autonomy system |
| Relationship to ARC | Repurpose ARC as the system | Use ARC components inside a new system |
| Recommended approach | Extend ARC | Build AHVS, import ARC |

The manual plan is "ARC adapted to run AHVS." The automatic plan is "AHVS built with ARC's execution components inside it."

---

## 8. What ARC Uniquely Contributes to AHVS That Would Be Expensive to Rebuild

Even though ARC is not a near-complete AHVS implementation, these ARC components save significant work:

| ARC Component | What it saves | Estimated rebuild cost without ARC |
|---|---|---|
| `experiment/sandbox.py` + `docker_sandbox.py` | Production experiment execution with GPU, network policy, metric parsing, NaN/Inf fast-fail | ~800 lines |
| `pipeline/code_agent.py` Phase 4 tree search | AIDE-style tree search for `structural` hypotheses | ~400 lines |
| `agents/base.py` `BaseAgent` | Multi-agent framework, JSON extraction, LLM protocol | ~200 lines |
| `llm/client.py` | OpenAI-compatible client with fallback chain, retry, JSON mode | ~300 lines |
| `literature/` pipeline | `discover_contract()` for research-domain adapters | ~500 lines |
| `evolution.py` `EvolutionStore` | Local knowledge storage with time-weighted recall | ~200 lines |
| `templates/` LaTeX/report compiler | Final report generation | ~300 lines |
| **Total savings** | | ~2,700 lines |

Without ARC, AHVS Automatic's implementation cost would approximately double.

---

## 9. First Concrete Step

The lowest-risk, highest-value starting point is to implement the `PipelineAdapter` ABC and the first concrete adapter that wraps ARC's sandbox layer:

**File:** `ahvs_automatic/adapters/arc_sandbox_adapter.py`

This adapter makes any Python script that outputs JSON metrics into an AHVS-compatible experiment target:

```python
class ARCSandboxAdapter(PipelineAdapter):
    def __init__(self, config: dict):
        self._sandbox = LocalSandbox(config)

    def run_experiment(self, trial_spec: TrialSpec) -> TrialResult:
        # Translate TrialSpec → ARC sandbox invocation
        result = self._sandbox.run(
            script=trial_spec.pipeline_config["entry_point"],
            env=trial_spec.pipeline_config,
            timeout=trial_spec.timeout_seconds,
        )
        # Translate ARC sandbox output → TrialResult
        return TrialResult(
            trial_id=trial_spec.trial_id,
            metrics=result.metrics,
            cost_usd=0.0,  # local execution
            ...
        )
```

This single file proves the adapter interface is workable and gives AHVS Automatic its first running experiment backend — entirely powered by ARC's production sandbox infrastructure.

From there, the autonomy ladder and confidence system can be built incrementally, starting with L0 (all decisions go to human) and promoting to L1 after the first 5 successful cycles.

---

## 10. Risks and Architectural Constraints

### Orchestration model lock-in
AHVS §11 explicitly requires Claude Agent SDK as the current backbone but emphasizes that AHVS's core value must remain decoupled from SDK internals. If Path B (ARC runner) is chosen, this constraint is violated in the short term. The mitigation is to keep all AHVS logic (autonomy, knowledge, adapters) in SDK-agnostic Python modules, with ARC's runner as a thin outer shell that can be replaced later.

### ClawVault dependency
AHVS §9 requires ClawVault as the knowledge backend. ClawVault (`clawvault-py`) is listed as an external dependency that must be installed. ARC's `EvolutionStore` is a usable V1 approximation, but AHVS cycles will accumulate strategy priors that require proper BM25+semantic retrieval. Plan to migrate to ClawVault after the first 3–5 cycles, not before.

### MLflow as always-on requirement
ARC has no MLflow. Adding MLflow to ARC's runner (Path B) means every ARC experiment run would log to MLflow — this may be desirable but it's a behavioral change to ARC's existing pipeline that affects all 23 stages, not just the AHVS stages.

### Budget tracking granularity
ARC's sandbox captures total execution time and terminal output but does not capture per-API-call token costs. AHVS's `BudgetGuard` and `cost_breakdown` require per-call cost tracking. For the first adapter (AutoQA or similar), the pipeline itself must emit cost logs that ARC's sandbox parses. This is an adapter responsibility, not an ARC core change.

---

## 11. Conclusion

AutoResearchClaw is a valuable component library for AHVS Automatic, not a near-complete implementation. The most honest framing:

- ARC provides the **execution infrastructure** (experiment backends, code generation, literature search, agent framework, LLM client) that plugs into AHVS's `PipelineAdapter` interface.
- AHVS Automatic provides the **coordination and intelligence layer** (autonomy progression, confidence routing, knowledge store, budget discipline, cross-cycle learning) that ARC entirely lacks.

The correct implementation path is **Path A**: build AHVS Automatic as a new system, import ARC's execution components into it via the adapter interface. This saves ~2,700 lines of otherwise-from-scratch work while keeping AHVS Automatic architecturally clean.

The first milestone is the `PipelineAdapter` ABC + `ARCSandboxAdapter` implementation, which proves the interface works and gives AHVS its first production experiment backend in ~250 lines of new code.
