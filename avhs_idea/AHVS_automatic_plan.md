# Plan V7: Agentic Hypothesis Validation System
## Generic Framework, MCP-First, Orchestration-Agnostic, Progressive Autonomy
### First instantiation: AutoQA LLM Classification Pipelines

---

## 1. Vision

**[Generic]** An agent that systematically improves any measurable R&D pipeline by generating, testing, and learning from hypotheses. It starts heavily human-guided and progressively earns autonomy through demonstrated competence — much like a junior researcher becoming senior.

The system is domain-agnostic by design. It operates on any target system that exposes:
1. A measurable objective (metric + eval dataset).
2. A mutable configuration space (what the agent can change).
3. An execution interface (how to run experiments and read results).

These three requirements are encapsulated in a **Pipeline Adapter** — the only component that changes per domain.

**First validation target:** AutoQA cohort classification (prompt strategies, pipeline architectures, judge configurations, score thresholds, model selection). This domain is chosen because it has clear metrics, fast feedback loops, and low cost per experiment — ideal for validating the framework's core mechanics before generalizing.

**Design principles:**
1. **Build on existing tools** — don't reinvent what exists.
2. **MCP-first, orchestration-agnostic** — Claude Agent SDK is the current orchestration backbone and the right choice today given its pioneering role in the MCP ecosystem. However, AHVS's core value — the knowledge store, domain adapters, and autonomy logic — lives in MCP tools and domain-agnostic constructs, not in SDK-specific internals. Swapping the orchestration layer in the future must be a contained infrastructure change, not a framework rebuild.
3. **Progressive autonomy** — earn trust through evidence, not configuration.
4. **Generic core, specific adapters** — the coordinator, knowledge store, autonomy system, hooks, and reporting are domain-agnostic. Only the adapter is domain-specific.
5. **Shadow company alignment** — AHVS is the R&D agent family within Blackbird's broader agentic shadow company. It uses the same primitives the shadow company will rely on: MCP tools, the Context Graph as the knowledge layer, and agent authority boundaries aligned with the shadow company's identity model. When the shadow company is built, AHVS plugs in cleanly rather than requiring retrofitting.

---

## 2. Abstraction Architecture

The system has two clearly separated layers. Understanding this separation is essential — it is the key design constraint that enables generalization.

### 2.1 What is Generic (the Framework)

These components work identically regardless of domain:

| Component | Responsibility |
|-----------|---------------|
| **Coordinator Agent** | Lifecycle orchestration, subagent spawning, session management |
| **Autonomy Ladder** | L0–L3 progression, promotion/demotion criteria, decision routing |
| **Confidence System** | Discrete 5-class assessment, calibration tracking, routing table |
| **Knowledge Store** | Strategy taxonomy, priors, trust scoring, rejection learning, autonomy records |
| **Hook System** | Gate enforcement, budget guards, safety checks, result logging, review cadence |
| **Experiment Lifecycle** | Phase 0→1→2→3→4 pipeline (onboarding, generation, screening, deepening, promotion) |
| **Reporting** | Gate reports, final reports, log-to-report mapping |
| **Logging & Artifacts** | Structured run directories, JSONL logs, thought traces |
| **MLflow Integration** | Experiment tracking, metric logging, artifact storage — always-on across all domains |
| **Optuna Integration** | Numeric parameter optimization (when the adapter exposes numeric params) |
| **Tree-Search Pattern** | AIDE-inspired exploration of variation trees |
| **Promptfoo Eval** | LLM/prompt hypothesis evaluation engine — multi-provider, structured JSON output, CI/CD-compatible |
| **DSPy Optimization** | Prompt/few-shot compilation for `prompt_optimization` hypothesis type — BootstrapFewShot / MIPRO |
| **ClawVault Knowledge Store** | Persistent agent memory with hybrid BM25+semantic search, entity graph, session lifecycle (wake/checkpoint/sleep), Python SDK |

### 2.2 What is Adapter-Specific (changes per domain)

| Component | Responsibility | Example (AutoQA) |
|-----------|---------------|-----------------|
| **PipelineAdapter** implementation | The 7-method interface connecting the framework to a target system | `AutoQAPipelineAdapter` |
| **Bootstrap Strategy Taxonomy** | Initial set of strategies seeded into the knowledge store | 12 LLM-classification strategies (CoT, few-shot, model selection, etc.) |
| **Hypothesis Space** | What the agent can mutate | Prompts, judge architecture, numeric params, model selection |
| **Cost Estimation Formula** | How to predict experiment cost before running | `samples × fraction × tokens × price × judges` |
| **Constraint Definitions** | Domain-specific guardrails | `max_cost_per_sample_usd`, `max_latency_ms` |
| **Pipeline Entry Point** | How to execute the target system | `python run_pipeline.py --config {path}` |

### 2.3 The Rule

> If you're modifying the coordinator, hooks, autonomy system, knowledge store, or reporting to support a new domain — **you're doing it wrong.** Write a new adapter instead.

---

## 3. What Changed from V3 → V4 → V4.1 → V5

| Area | V3 | V4 | V4.1 | V5 (this doc) |
|------|----|----|------|---------------|
| Orchestration | Custom state machine | Claude Agent SDK | Same, + all hooks fully defined | Same |
| Experiment execution | Custom `RepositoryAdapter` | AIDE tree-search pattern | Same, + adapter methods complete | Same, + generic adapter ABC defined |
| Memory | "similarity + trust" | Knowledge graph with structured priors | Same, + bootstrap strategy, rejection learning | Same |
| Autonomy | "Conservative default" | 4-level ladder with promotion/demotion | Same, + discrete confidence classes, decision matrix, shadow scoring | Same |
| Scope | "General repos" | AutoQA-first | Same, + design decisions resolved | **Generic-first framing. AutoQA as first instantiation.** |
| Confidence | Continuous 0-1 | Continuous 0-1 | Discrete 5-class (very_low → very_high) | Same |
| Concurrency | Unspecified | Unspecified | Sequential ≤L2, parallel at L3 | Same |
| Cost tracking | Unspecified | Per-trial | Per-hypothesis (aggregated from per-call logging) | Same |
| Cohort scope | Unspecified | Unspecified | Shared hypotheses across entire cohort set | Same |
| **Abstraction** | Implicit | Principle 4 stated but not practiced | §15 (13 lines) as afterthought | **§2 Abstraction Architecture as first-class section. Generic adapter ABC. [Generic]/[Adapter-Specific] annotations throughout.** |

---

## 4. Landscape: What Exists and What We Reuse

**[Generic]** — all tool choices apply regardless of domain.

### 4.1 Direct Reuse (integrate, don't rebuild)

| Tool                 | What we take from it                                            | How we use it                                                                                                                                                                                                                                                                                                          |
| -------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Claude Agent SDK** | Agent loop, subagents, tool use, hooks, session resumption, MCP | Current orchestration backbone. Each phase is a subagent with scoped tools and budget. Hooks enforce gates. Treated as replaceable infrastructure — no proprietary AHVS logic is embedded in SDK-specific internals. Core assets (knowledge store, adapters, autonomy logic) are exposed as MCP tools for portability. |
| **AIDE** (Weco AI)   | Tree-search over code variations                                | Adapt the "solution tree" pattern for configuration variation search. Instead of code edits, our nodes are pipeline config mutations.                                                                                                                                                                                  |
| **MLflow**           | Experiment tracking, metric logging, artifact storage           | Default tracking backend. Every trial logged as an MLflow run with parent-child hierarchy (macro → micro → trial).                                                                                                                                                                                                     |
| **Optuna**           | Bayesian hyperparameter search                                  | Numeric parameter optimization (thresholds, temperatures, top-k). Not used for prompt/architecture search (LLM handles that).                                                                                                                                                                                          |
| **DSPy**             | Compiled, self-improving LLM modules                            | Two roles: (1) The Hypothesis Engine is a DSPy-style module — signature (evidence → hypotheses), compiles against past performance. (2) Actual DSPy execution backend for `prompt_optimization` hypothesis type — BootstrapFewShot / MIPRO optimizers compile the best few-shot program, then Promptfoo formally evaluates the compiled output. |
| **Promptfoo**        | LLM eval engine — multi-provider, YAML-driven, structured JSON output | Execution backend for `llm_*` and `rag_*` domain hypotheses. Agent generates `promptfoo.yaml` config, fires `promptfoo eval` (subprocess or programmatic API), parses JSON results. Handles multi-provider comparison, provider-agnostic eval, CI/CD integration. The DSPy→Promptfoo two-step handles `prompt_optimization` hypotheses. |
| **ClawVault**        | Markdown-based persistent agent memory with hybrid BM25+semantic search | Replaces flat JSONL knowledge store. Vault layout: `decisions/` (promoted strategies), `lessons/` (cycle insights), `tasks/` (active hypotheses), `backlog/` (pending), `handoffs/` (next-cycle context). Python SDK (`clawvault-py`) enables programmatic `vault.wake()` / `vault.remember()` / `vault.sleep()` within the agent loop. Session lifecycle maps to cycle start/end. |

### 4.2 Architectural Inspiration (adapt patterns, not code)

| System | Pattern we borrow |
|--------|-------------------|
| **Karpathy's autoresearch** | Fixed-budget experiment cycles. Each trial has a wall-clock cap. Agent iterates fast. |
| **Sakana AI Scientist** | Idea → Experiment → Review loop. Our macro hypothesis generation mirrors their idea generation + novelty check. |
| **Confidence-Based Autonomy (CBA)** | Agent self-assesses confidence per decision. Discrete class determines routing. Calibration tracked over time. |
| **ReAct pattern** | Interleaved reasoning + action. Every agent step produces a thought trace before acting, enabling human audit. |
| **Agency-Agents** (msitarzewski) | 100+ specialized agent role templates across 14 divisions. Testing division (Performance Benchmarker, API Tester, Load Tester) informs experiment subagent role definitions. Multi-agent Orchestrator template informs L3 parallel-cycle architecture — at L3, domain-specialized sub-agents (one per hypothesis type) are spawned rather than a single monolithic coordinator. |


---

## 5. System Architecture

**[Generic]** — the architecture below is domain-agnostic. The only domain-specific component is the Pipeline Adapter at the bottom.

```
┌─────────────────────────────────────────────────────────────────┐
│                    HUMAN (Operator / Team)                       │
│  Reviews gate reports, approves macros, adjusts autonomy level  │
│  Provides structured rejection reasons when rejecting macros    │
│  Periodically shadow-scores autonomous decisions (L2+ audit)    │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│               COORDINATOR AGENT (Claude Agent SDK)              │
│                          [Generic]                              │
│                                                                 │
│  - Runs the hypothesis lifecycle                                │
│  - Manages autonomy level and gate enforcement                  │
│  - Spawns subagents for each phase                              │
│  - Reads/writes knowledge store                                 │
│  - Session resumption for multi-day runs                        │
│  - Routes decisions via discrete confidence classes              │
│                                                                 │
│  Tools: Read, Write, Bash, AskUserQuestion, Subagents           │
│  Hooks: GateEnforcer, BudgetGuard, SafetyChecker,               │
│         ResultLogger, ReviewCadenceEnforcer                     │
│                                                                 │
│  ┌───────────────┐ ┌───────────────┐ ┌────────────────────┐     │
│  │  Onboarding   │ │  Hypothesis   │ │  Experiment        │     │
│  │  Subagent     │ │  Subagent     │ │  Subagent          │     │
│  │               │ │               │ │                    │     │
│  │  - Parse repo │ │  - Generate   │ │  - Execute trials  │     │
│  │  - Run base-  │ │    macros     │ │  - Track in MLflow │     │
│  │    line eval  │ │  - Generate   │ │  - Report results  │     │
│  │  - Build task │ │    micros     │ │  - Tree-search     │     │
│  │    contract   │ │  - Score &    │ │    (AIDE pattern)  │     │
│  │               │ │    rank       │ │  - Validate &      │     │
│  │               │ │  - Learn from │ │    estimate cost    │     │
│  │               │ │    rejections │ │    before running   │     │
│  └───────────────┘ └───────────────┘ └────────────────────┘     │
│                                                                 │
│  ┌───────────────┐ ┌───────────────┐                            │
│  │  Review       │ │  Promotion    │                            │
│  │  Subagent     │ │  Subagent     │                            │
│  │               │ │               │                            │
│  │  - Gate       │ │  - CI check   │                            │
│  │    reports    │ │  - Holdout    │                            │
│  │  - Stop       │ │    eval      │                            │
│  │    checks     │ │  - Change    │                            │
│  │  - Autonomy   │ │    bundle    │                            │
│  │    assessment │ │  - Memory    │                            │
│  │  - Shadow     │ │    update    │                            │
│  │    score prep │ │  - Autonomy  │                            │
│  │               │ │    update    │                            │
│  └───────────────┘ └───────────────┘                            │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    INFRASTRUCTURE LAYER                          │
│                          [Generic]                              │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  MLflow   │  │  Optuna  │  │Promptfoo │  │   DSPy   │       │
│  │  Tracking │  │  Search  │  │   Eval   │  │ Optimizer│       │
│  │  (always) │  │          │  │          │  │          │       │
│  │  Trials,  │  │  Numeric │  │ LLM/RAG  │  │  Prompt  │       │
│  │  metrics, │  │  param   │  │ hypothe- │  │  optim-  │       │
│  │  artifacts│  │  optim   │  │  sis     │  │  ization │       │
│  │  per-call │  │          │  │  eval    │  │  → feeds │       │
│  │  costs    │  │          │  │          │  │Promptfoo │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  ClawVault Knowledge Store (always-on)                   │   │
│  │                                                          │   │
│  │  vault/decisions/  — promoted strategies & trust scores  │   │
│  │  vault/lessons/    — cycle insights & rejection patterns │   │
│  │  vault/tasks/      — active hypotheses                   │   │
│  │  vault/backlog/    — pending hypotheses                  │   │
│  │  vault/handoffs/   — next-cycle context                  │   │
│  │                                                          │   │
│  │  BM25+semantic search · entity graph · Python SDK        │   │
│  │  wake() at cycle start · sleep() at cycle end            │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PIPELINE ADAPTER LAYER                        │
│                      [Adapter-Specific]                         │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  PipelineAdapter (Abstract Base Class — §7)              │    │
│  │  7 methods: discover_contract, run_baseline,             │    │
│  │  run_experiment, validate_mutation, estimate_cost,       │    │
│  │  get_constraints, get_hypothesis_space                   │    │
│  └──────────────────────┬──────────────────────────────────┘    │
│                         │                                       │
│  ┌──────────────────────┴──────────────────────────────────┐    │
│  │  Concrete Adapters:                                      │    │
│  │                                                          │    │
│  │  ✅ AutoQAPipelineAdapter (V5 — implemented)             │    │
│  │  ○  MLTrainingAdapter (future)                           │    │
│  │  ○  RAGPipelineAdapter (future)                          │    │
│  │  ○  DataProcessingAdapter (future)                       │    │
│  └──────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Progressive Autonomy Ladder

**[Generic]** — autonomy mechanics are domain-agnostic. The agent earns trust on any target system through the same criteria.

### 6.1 The Four Levels

| Level | Name | What Agent Decides Alone | What Requires Human |
|-------|------|-------------------------|---------------------|
| **L0** | Apprentice | Nothing. Agent proposes, human approves every action. | Macro selection, micro generation, trial execution, promotion |
| **L1** | Junior | Execute micro hypotheses and trials within approved macros. | Macro approval, review gates, promotion decisions |
| **L2** | Senior | Generate and screen macros autonomously. Execute full experiment cycles. | Final promotion decisions, budget increases, novel strategy types |
| **L3** | Principal | Full cycle including promotion. Human reviews summary reports. Parallel cycles allowed. | Budget cap increases, domain expansion, architecture-level changes |

### 6.2 Decision-to-Autonomy-Level Matrix

Explicit mapping of every decision type to the minimum autonomy level required for autonomous execution:

| Decision | L0 | L1 | L2 | L3 |
|----------|----|----|----|----|
| Generate macro candidates | Agent proposes, human selects | Same | Agent selects, human reviews batch | Agent selects |
| Reject a weak macro | Human | Human | Agent (if confidence ≥ HIGH) | Agent |
| Execute trial within approved macro | Human approves | Agent | Agent | Agent |
| Stop a failing macro branch | Human | Human | Agent | Agent |
| Trigger review gate | Always human | Always human | Agent self-reviews, escalates anomalies | Agent self-reviews |
| Promote winning config | Human | Human | Human | Agent promotes, human reviews post-hoc |
| Increase budget mid-run | Human | Human | Human | **Human (always — hard safety boundary)** |
| Add new strategy type to knowledge | Human | Human | Human | Agent proposes, human confirms |
| Run parallel hypothesis cycles | N/A | N/A | N/A | Agent (L3 only) |

### 6.3 Promotion Criteria (Level N → Level N+1)

Promotion is **per task-family**, not global. Being L2 on "cohort prompt tuning" doesn't make you L2 on "RAG retrieval optimization."

```python
@dataclass
class AutonomyPromotion:
    min_successful_cycles: int = 5
    min_human_agreement_rate: float = 0.85   # measured via shadow scoring (see §6.7)
    max_regression_rate: float = 0.05
    min_confidence_calibration: float = 0.80  # see §6.6 for how this is computed

    def should_promote(self, record: AutonomyRecord) -> tuple[bool, str]:
        if record.completed_cycles < self.min_successful_cycles:
            return False, f"Need {self.min_successful_cycles} cycles, have {record.completed_cycles}"
        if record.agreement_rate < self.min_human_agreement_rate:
            return False, f"Agreement rate {record.agreement_rate:.0%} < {self.min_human_agreement_rate:.0%}"
        if record.regression_rate > self.max_regression_rate:
            return False, f"Regression rate {record.regression_rate:.0%} > {self.max_regression_rate:.0%}"
        if record.calibration_score < self.min_confidence_calibration:
            return False, f"Calibration {record.calibration_score:.0%} < {self.min_confidence_calibration:.0%}"
        return True, "All criteria met"
```

### 6.4 Demotion Triggers (Level N → Level N-1)

```python
@dataclass
class AutonomyDemotion:
    consecutive_regressions: int = 2
    confidence_miscalibration: float = 0.30
    novel_domain_detected: bool = True
    budget_overrun_rate: float = 0.20
```

### 6.5 Discrete Confidence Classes

**[Generic]** — confidence assessment works the same on any domain.

Confidence is expressed as five discrete classes, not continuous scores. This avoids false precision — the agent doesn't actually know the difference between 0.73 and 0.76.

```python
from enum import Enum

class Confidence(Enum):
    VERY_LOW  = "very_low"    # "I'm guessing"
    LOW       = "low"         # "Weak evidence, could go either way"
    MEDIUM    = "medium"      # "Reasonable evidence, but not certain"
    HIGH      = "high"        # "Strong evidence from priors + reasoning"
    VERY_HIGH = "very_high"   # "Overwhelming evidence, near-certain"
```

**How the agent assigns a confidence class:**

The agent evaluates three signals and produces a discrete class (not a weighted float):

1. **Prior evidence strength:** Does the knowledge store have a high-trust prior for this strategy on a similar task?
2. **Reasoning coherence:** The agent self-rates its reasoning chain — "Given the evidence I see, how strong is my case?"
3. **Historical calibration:** How often has the agent's stated confidence class matched actual outcomes in the past?

The agent produces a class by reasoning over these signals in its thought trace:

```
Thought: Prior evidence for [strategy] on [task_family]: trust_score 0.72, used 3 times with avg +4% improvement.
         My reasoning: [strategy] should help because current errors show [pattern].
         Historical calibration: Last 5 HIGH-confidence decisions had 4/5 positive outcomes (80%).
         Assessment: Strong prior + coherent reasoning + good calibration → HIGH confidence.
```

**Confidence-to-action routing:**

| Confidence | Agent Behavior |
|------------|---------------|
| VERY_LOW | Always escalate to human, regardless of autonomy level |
| LOW | Ask human for guidance with rationale |
| MEDIUM | At L0-L1: ask human. At L2+: act but flag in gate report |
| HIGH | At L0: ask human. At L1+: act autonomously |
| VERY_HIGH | At L0: propose with strong recommendation. At L1+: act autonomously |

```python
class DecisionRouter:
    """[Generic] Maps (confidence, autonomy_level) → action."""
    ROUTING_TABLE = {
        Confidence.VERY_LOW:  {0: "escalate", 1: "escalate", 2: "escalate", 3: "escalate"},
        Confidence.LOW:       {0: "escalate", 1: "escalate", 2: "escalate", 3: "escalate"},
        Confidence.MEDIUM:    {0: "escalate", 1: "escalate", 2: "act_and_flag", 3: "act_and_flag"},
        Confidence.HIGH:      {0: "escalate", 1: "act",      2: "act",          3: "act"},
        Confidence.VERY_HIGH: {0: "recommend",1: "act",      2: "act",          3: "act"},
    }

    def route(self, decision: Decision, confidence: Confidence, autonomy_level: int) -> str:
        base_action = self.ROUTING_TABLE[confidence][autonomy_level]

        # Override: decision type requires higher level than current
        if autonomy_level < DECISION_REQUIREMENTS[decision.decision_type]:
            return "escalate"

        return base_action
```

### 6.6 Confidence Calibration Tracking

**[Generic]**

To measure whether the agent's confidence classes are well-calibrated:

```python
@dataclass
class CalibrationTracker:
    """Track how often each confidence class leads to positive outcomes."""
    # Counts per class: {class: {"positive": N, "negative": N}}
    outcome_counts: dict[Confidence, dict[str, int]]

    def calibration_score(self) -> float:
        """
        Measures alignment between confidence ordering and success rate.
        A well-calibrated agent has: success_rate(VERY_HIGH) > success_rate(HIGH) > ... > success_rate(VERY_LOW)
        Returns 0-1 where 1.0 = perfect calibration (ordering fully preserved).
        """
        rates = {}
        for conf in Confidence:
            counts = self.outcome_counts.get(conf, {"positive": 0, "negative": 0})
            total = counts["positive"] + counts["negative"]
            rates[conf] = counts["positive"] / total if total > 0 else 0.5

        # Check ordering: each level should have >= success rate than the level below
        ordered = [Confidence.VERY_LOW, Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH, Confidence.VERY_HIGH]
        violations = 0
        comparisons = 0
        for i in range(len(ordered) - 1):
            comparisons += 1
            if rates[ordered[i]] > rates[ordered[i + 1]]:
                violations += 1

        return 1.0 - (violations / comparisons) if comparisons > 0 else 0.5
```

### 6.7 Shadow Scoring for Agreement Rate (L2+ Audit)

**[Generic]**

When the agent acts autonomously (L2+), it logs what it *would have asked the human* in `autonomy_decisions.jsonl`. Periodically (every 5th cycle), the human reviews a sample of these shadow decisions.

```python
@dataclass
class ShadowDecision:
    decision_id: str
    cycle_id: str
    decision_type: str           # e.g., "macro_selection", "macro_rejection", "branch_stop"
    agent_action: str            # what the agent did
    agent_confidence: Confidence
    agent_rationale: str         # thought trace excerpt
    outcome: str | None          # filled after trial completes: "positive" | "negative" | "neutral"

    # Filled during human audit:
    human_would_agree: bool | None      # would the human have made the same decision?
    human_feedback: str | None          # optional free-text note
```

**Agreement rate** = count(human_would_agree=True) / count(audited decisions)

This is measured only on escalated decisions at L0-L1. At L2+, it's measured via periodic shadow audits. The rate feeds directly into promotion/demotion criteria.

**TODO (deferred):** Full shadow scoring UX at L2+ — the detailed human audit workflow, sampling strategy, and integration with gate reports. This will be designed when the system first reaches L2.

---

## 7. Pipeline Adapter Interface

**[Generic]** — this is the abstraction boundary between the framework and any target domain.

Every domain the system operates on must implement this interface. The framework never calls the target system directly — it always goes through the adapter.

```python
from abc import ABC, abstractmethod

class PipelineAdapter(ABC):
    """
    Abstract base class for connecting the hypothesis validation framework
    to a specific target system.

    To add a new domain:
    1. Subclass PipelineAdapter.
    2. Implement all 7 abstract methods.
    3. Create a domain-specific bootstrap strategy taxonomy (see §9.5).
    4. Provide a labeled eval dataset.
    5. No changes to the coordinator, knowledge store, autonomy system, or hooks.
    """

    @abstractmethod
    def discover_contract(self, workspace_path: str) -> TaskContract:
        """Parse the target repo to extract pipeline config, eval sets, and metrics.
        Returns a TaskContract that defines what success looks like."""

    @abstractmethod
    def run_baseline(self, contract: TaskContract) -> TrialResult:
        """Execute the current (unmodified) pipeline config on dev split.
        Establishes the baseline that all hypotheses are measured against."""

    @abstractmethod
    def run_experiment(self, trial_spec: TrialSpec) -> TrialResult:
        """Execute a single trial with a modified config.
        Must respect trial_spec.eval_fraction for subsampling and trial_spec.seed for reproducibility."""

    @abstractmethod
    def validate_mutation(self, mutation: dict, current_config: dict) -> tuple[bool, str]:
        """Check if a proposed mutation produces a valid config.
        Returns (is_valid, reason_if_invalid). Called in Stage A (free, no LLM calls)."""

    @abstractmethod
    def estimate_cost(self, trial_spec: TrialSpec, contract: TaskContract) -> float:
        """Estimate the cost (USD) of running a trial before executing it.
        Used by BudgetGuard to prevent cost overruns."""

    @abstractmethod
    def get_constraints(self, contract: TaskContract) -> dict:
        """Return domain-specific constraint bounds (e.g., max latency, max cost per sample).
        Used by Stage A static checks to reject infeasible configs."""

    @abstractmethod
    def get_hypothesis_space(self) -> dict:
        """Define what the agent can mutate in this domain.
        Returns a structured dict of parameter names, types, and ranges.
        Used by the Hypothesis Subagent to generate valid mutations."""
```

### Why 7 Methods?

| Method | Purpose | When Called |
|--------|---------|------------|
| `discover_contract` | Understand the target system | Phase 0 (once) |
| `run_baseline` | Establish the bar to beat | Phase 0 (once per cycle) |
| `run_experiment` | Execute a hypothesis | Phase 2 & 3 (many times) |
| `validate_mutation` | Catch invalid configs for free | Phase 2 Stage A (many times, zero cost) |
| `estimate_cost` | Predict before spending | Phase 2 Stage A (many times, zero cost) |
| `get_constraints` | Know the guardrails | Phase 0 & 2 |
| `get_hypothesis_space` | Know what's mutable | Phase 1 |

---

## 8. Core Data Types

### 8.1 TaskContract

**[Generic]** — the contract is domain-agnostic. The adapter's `discover_contract()` populates it with domain-specific values.

```python
@dataclass
class TaskContract:
    task_family: str                    # e.g., "cohort_classification", "rag_retrieval", "model_training"
    objective_metric: str               # e.g., "f1_macro", "ndcg@10", "val_loss"
    secondary_metrics: list[str]        # e.g., ["precision", "recall", "cost_per_eval"]
    constraints: dict                   # domain-specific bounds, e.g., {"max_cost_per_sample_usd": 0.05}
    eval_dataset_path: str              # path to labeled eval set (human-curated, frozen per cycle)
    eval_dataset_size: int              # number of samples
    eval_dataset_checksum: str          # SHA-256 of eval set file for integrity verification
    baseline_config_path: str           # path to current pipeline config
    pipeline_entry_point: str           # how to invoke the pipeline (adapter-specific)
    adapter_type: str                   # which PipelineAdapter subclass to use
```

### 8.2 Hypothesis Types

**[Generic]** — hypothesis structure is the same regardless of domain. The `direction` and `mutation` fields contain domain-specific content, but their schema is universal.

```python
@dataclass
class MacroHypothesis:
    id: str
    direction: str                      # adapter-defined categories, e.g., "prompt_strategy", "architecture", "hyperparameter"
    description: str                    # human-readable
    rationale: str                      # evidence-backed reasoning
    evidence_links: list[str]           # pointers to prior results, papers, or baseline analysis
    estimated_cost_usd: float           # projected total cost for this hypothesis (all trials)
    estimated_trials: int               # how many micro experiments needed
    risk_score: float                   # 0-1, higher = more novel/risky
    evidence_score: float               # 0-1, higher = stronger prior evidence
    confidence: Confidence              # agent's discrete confidence class
    status: str                         # proposed | approved | screening | active | completed | rejected
    rejection_reason: str | None        # structured reason if rejected (see §9.6)
    actual_cost_usd: float = 0.0        # accumulated cost across all trials under this macro

@dataclass
class MicroHypothesis:
    id: str
    macro_id: str
    mutation: dict                      # specific change — contents defined by adapter's hypothesis space
    expected_delta: dict                # e.g., {"f1_macro": "+0.03"} or {"ndcg@10": "+0.05"}
    parent_trial_id: str | None         # which trial spawned this (AIDE tree-search lineage)
    status: str                         # proposed | running | completed | failed
```

### 8.3 Trial and Results

**[Generic]**

```python
@dataclass
class TrialSpec:
    trial_id: str
    macro_id: str
    micro_id: str
    pipeline_config: dict               # full resolved config for this trial
    eval_split: str                     # "dev" | "holdout"
    eval_fraction: float                # 1.0 = full split, 0.1 = 10% subsample (for Stage B)
    eval_sample_seed: int               # seed for reproducible subsampling
    seed: int
    api_version_pins: dict              # e.g., {"claude": "claude-sonnet-4-6"} — adapter populates relevant pins
    prompt_snapshot_hash: str           # SHA-256 hash of all prompts/configs used

@dataclass
class TrialResult:
    trial_id: str
    macro_id: str                       # for cost aggregation to hypothesis level
    metrics: dict                       # e.g., {"f1_macro": 0.82, "precision": 0.85}
    metric_delta: dict                  # computed vs baseline: {"f1_macro": +0.03}
    duration_seconds: float
    cost_usd: float                     # total cost for this trial
    cost_breakdown: list[dict]          # per-call: [{"model": "...", "tokens_in": N, "cost_usd": X}, ...]
    sample_count: int
    error: str | None
    artifacts_path: str                 # path to detailed outputs
    thought_trace: str                  # agent's reasoning for this trial's mutations
    parent_trial_id: str | None         # tree-search lineage: which trial spawned this variation
```

---

## 9. Knowledge Store

**[Generic]** — the knowledge store structure is universal. Only the *contents* (which strategies, which priors) are domain-specific.

### 9.1 Structure

**[Generic]** — the knowledge store is backed by **ClawVault** (`clawvault-py` Python SDK). Markdown files are human-auditable, git-compatible, and searchable via hybrid BM25+semantic search. The agent calls `vault.wake()` at cycle start and `vault.sleep()` at cycle end to maintain session continuity.

```
knowledge/
└── vault/                         # ClawVault root — human-readable, git-committed
    ├── decisions/                  # promoted strategies and trust records
    │   ├── strategy_taxonomy.md    # replaces strategies.json — each strategy is a markdown note
    │   └── {strategy_id}.md        # one file per strategy: trust score, success/fail counts, lineage
    ├── lessons/                    # cycle insights and rejection patterns
    │   ├── rejections.md           # replaces rejections.jsonl — structured rejection history
    │   └── cycle_{id}_{task}.md    # per-cycle lesson: what worked, what didn't, what to avoid
    ├── tasks/                      # active hypotheses (in-progress)
    │   └── {macro_id}.md           # active hypothesis with status, current trial results
    ├── backlog/                    # pending hypotheses approved but not yet started
    │   └── {macro_id}.md
    ├── handoffs/                   # next-cycle context (ClawVault session continuity)
    │   └── next_cycle_context.md   # replaces per-session memory: what to pick up next cycle
    └── autonomy_record.json        # agent's track record per task-family (unchanged schema)
```

**Search interface (used by Hypothesis Subagent):**
```python
from clawvault import Vault

vault = Vault("knowledge/vault")
vault.wake()  # restore session context at cycle start

# Query knowledge before generating hypotheses:
prior_results = vault.search("few-shot selection cohort classification improvement")
rejections = vault.search("rejected strategies temperature tuning")

# Write cycle knowledge:
vault.remember("lessons/cycle_20250313_autoqa.md", content="...")
vault.sleep(summary="Cycle completed: +4.2% F1 via CoT prompting on cohort_v3")
```

**Two-tier architecture (local + global):**
- **Local vault**: `{repo}/.ahvs/knowledge/vault/` — per-repo experiment history
- **Global vault**: `blackbird-ahvs-knowledge/vault/` — shared R&D knowledge across all repos. Hypothesis Subagent queries both vaults before generating macros, enabling cross-repo rejection prevention and strategy transfer.

### 9.2 Strategy Node

```python
@dataclass
class StrategyNode:
    strategy_id: str                    # e.g., "cot_prompting", "learning_rate_schedule", "chunk_size_tuning"
    strategy_type: str                  # adapter-defined categories
    description: str
    applicable_task_families: list[str]
    trust_score: float                  # 0-1, updated after each cycle
    success_count: int
    failure_count: int
    avg_improvement: float              # average metric delta when this strategy worked
    last_used: str                      # ISO timestamp
    decay_rate: float                   # trust decays by this factor per unused cycle
    evidence_trail: list[str]           # trial IDs that contributed to this score
```

### 9.3 Prior Record

```python
@dataclass
class PriorRecord:
    prior_id: str
    task_family: str
    strategy_id: str
    context_fingerprint: dict           # adapter-defined context, e.g., {"dataset_size": "medium", "num_classes": 5}
    recommended_config: dict            # what worked
    metric_delta: float                 # how much it improved
    trust_score: float
    source_trials: list[str]
    negative_transfer_flag: bool        # was this prior harmful when applied in a different context?
```

### 9.4 Trust Update Rules

**[Generic]**

```python
def update_trust(strategy: StrategyNode, trial_result: TrialResult, baseline_metrics: dict,
                 config: KnowledgeConfig):
    delta = trial_result.metrics[objective] - baseline_metrics[objective]

    if delta > 0:
        strategy.trust_score = min(1.0, strategy.trust_score + config.success_increment * (delta / baseline_metrics[objective]))
        strategy.success_count += 1
    else:
        penalty = config.failure_penalty_high_trust if strategy.trust_score > 0.7 else config.failure_penalty_low_trust
        strategy.trust_score = max(0.0, strategy.trust_score - penalty)
        strategy.failure_count += 1

    # Time decay for unused strategies (applied per cycle, not per trial)
    strategy.trust_score *= (1 - config.trust_decay_rate)
```

### 9.5 Bootstrap Strategy Taxonomy

**[Adapter-Specific]** — each adapter seeds its own initial strategies. All start at `trust_score: 0.5` (neutral). Trust is earned through experimental evidence. The agent can propose new strategies over time (human-approved at L0-L2, agent-proposed at L3 with human confirmation).

**Example: AutoQA LLM Classification** (first instantiation)

```json
[
  {"strategy_id": "cot_prompting", "strategy_type": "prompt_strategy", "description": "Add chain-of-thought reasoning to classification prompt", "trust_score": 0.5},
  {"strategy_id": "few_shot_selection", "strategy_type": "prompt_strategy", "description": "Optimize few-shot example selection for target cohort", "trust_score": 0.5},
  {"strategy_id": "structured_output", "strategy_type": "prompt_strategy", "description": "Force structured JSON output to reduce parsing errors", "trust_score": 0.5},
  {"strategy_id": "majority_vote_judging", "strategy_type": "architecture", "description": "Use N judges with majority vote instead of single LLM", "trust_score": 0.5},
  {"strategy_id": "weighted_ensemble", "strategy_type": "architecture", "description": "Weighted combination of multiple judge scores", "trust_score": 0.5},
  {"strategy_id": "meta_judge", "strategy_type": "architecture", "description": "A meta-judge LLM that reviews individual judge outputs", "trust_score": 0.5},
  {"strategy_id": "model_upgrade", "strategy_type": "model_selection", "description": "Switch to a more capable model for the primary classifier", "trust_score": 0.5},
  {"strategy_id": "model_downgrade_fallback", "strategy_type": "model_selection", "description": "Use cheaper model as fallback for high-confidence cases", "trust_score": 0.5},
  {"strategy_id": "temperature_reduction", "strategy_type": "threshold", "description": "Lower temperature for more deterministic classification", "trust_score": 0.5},
  {"strategy_id": "confidence_threshold_tuning", "strategy_type": "threshold", "description": "Optimize decision threshold for precision/recall tradeoff", "trust_score": 0.5},
  {"strategy_id": "prompt_decomposition", "strategy_type": "prompt_strategy", "description": "Break complex classification into sub-questions", "trust_score": 0.5},
  {"strategy_id": "negative_example_augmentation", "strategy_type": "prompt_strategy", "description": "Add carefully selected negative examples to few-shot set", "trust_score": 0.5}
]
```

**Example: RAG Pipeline** (hypothetical future adapter — not in scope)

```json
[
  {"strategy_id": "chunk_size_tuning", "strategy_type": "retrieval", "description": "Optimize document chunk size for retrieval relevance", "trust_score": 0.5},
  {"strategy_id": "hybrid_search", "strategy_type": "retrieval", "description": "Combine dense and sparse retrieval methods", "trust_score": 0.5},
  {"strategy_id": "reranking", "strategy_type": "architecture", "description": "Add a cross-encoder reranker after initial retrieval", "trust_score": 0.5},
  {"strategy_id": "query_expansion", "strategy_type": "prompt_strategy", "description": "Expand user query with synonyms and related terms", "trust_score": 0.5}
]
```

### 9.6 Human Rejection Learning

**[Generic]** — the rejection mechanism works on any domain.

When a human rejects a macro hypothesis, they provide a structured reason. This is stored and used to improve future proposals.

```python
@dataclass
class RejectionRecord:
    rejection_id: str
    macro_id: str
    strategy_id: str
    rejection_reason: str               # structured: one of the categories below
    rejection_note: str | None          # optional free-text from human
    cycle_id: str
    timestamp: str

# Structured rejection categories (domain-agnostic):
REJECTION_REASONS = [
    "too_risky",                        # strategy is too novel/unproven for current state
    "already_tried",                    # we've tried this before (agent missed it in priors)
    "wrong_direction",                  # doesn't address the actual problem
    "too_expensive",                    # cost estimate exceeds acceptable ROI
    "not_relevant",                     # not applicable to current task
    "premature",                        # right idea but wrong timing (e.g., need more baseline data first)
]
```

**How rejections improve future proposals:**

The Hypothesis Subagent reads `rejections.jsonl` before generating new macros. Patterns are used as negative constraints:
- "already_tried" → agent cross-checks knowledge store more carefully
- "too_expensive" → agent applies stricter cost filters
- "wrong_direction" → negative evidence applied to that strategy's trust score for this task-family
- Repeated "too_risky" rejections for a strategy type → agent learns to avoid novel strategies until L2+

---

## 10. Execution Lifecycle

**[Generic]** — the 5-phase lifecycle is universal. The adapter is called at specific points (marked below).

### Domain Routing Rule

**[Generic]** — before Phase 2 execution begins, the Coordinator routes each hypothesis to the correct execution backend based on `domain_tags` and `hypothesis_type`:

```
domain_tags contains "llm_*" or "rag_*"     →  Promptfoo execution backend
hypothesis_type = "prompt_optimization"      →  DSPy compile → Promptfoo eval (two-step)
domain_tags contains "ml_*" or "algorithm_*" →  MLflow + Optuna backend
hypothesis_type = "structural"               →  AIDE tree-search + git-worktrees
all hypotheses                               →  MLflow logging (always-on)
all hypotheses                               →  ClawVault knowledge store (always-on)
```

This routing is determined at Phase 1 when hypotheses are generated. The `MacroHypothesis.direction` field must be one of: `"prompt_strategy"`, `"prompt_optimization"`, `"architecture"`, `"hyperparameter"`, `"structural"`. The Experiment Subagent reads this field to select the execution path in Phase 2 and 3.

---

### Phase 0: Onboarding (Onboarding Subagent)

**Always human-guided regardless of autonomy level. Runs once per new repo or when eval set/pipeline changes (detected via checksums). Subsequent cycles on same repo skip to Phase 1.**

1. **→ ClawVault:** `vault.wake()` — restore session context from previous cycle (if any).
2. Read repo structure: entry points, config files, eval scripts, existing results.
3. **→ Adapter:** `discover_contract()` — build `TaskContract`. Propose to human, get confirmation.
4. Verify eval dataset integrity (checksum). Eval set is **human-curated and frozen per cycle**. Agent may flag ambiguous samples or coverage gaps in its report, but cannot modify the eval set.
5. **→ Adapter:** `run_baseline()` — execute current config on dev split. Log to MLflow.
6. Analyze baseline results: error distribution, failure slices, confidence calibration.
7. **→ ClawVault:** `vault.search()` — load relevant priors from both local and global vaults.
8. Output: `baseline_report.md` with contract, metrics, prior matches, and eval set observations.

### Phase 1: Macro Hypothesis Generation (Hypothesis Subagent)

**L0-L1:** Human approves shortlist.
**L2-L3:** Agent generates and screens autonomously; human reviews summary.

1. **→ ClawVault:** `vault.search()` — query both local and global vaults for priors before generating. Cross-repo rejection prevention: check global vault for strategies already rejected on similar tasks.
2. Generate macro pool:
   - From baseline failure analysis (what's broken?).
   - From ClawVault search results (what's worked before on similar tasks?).
   - From rejection history in ClawVault lessons/ (avoid patterns the human has repeatedly rejected).
   - From LLM reasoning over the pipeline (what could theoretically help?).
   - From user hints (if provided).
   - **→ Adapter:** `get_hypothesis_space()` — constrain mutations to what's valid in this domain.
3. Assign `direction` to each macro (required for domain routing in Phase 2):
   - `"prompt_optimization"` → DSPy→Promptfoo path. Use when the goal is finding the *best* prompt systematically.
   - `"prompt_strategy"` → Promptfoo path. Use when testing specific prompt variants.
   - `"hyperparameter"` → Optuna path. Use when the mutation space is continuous/numeric.
   - `"structural"` → AIDE path. Use when the mutation involves architecture changes or code variants.
4. Score each macro: `evidence_score × (1 - risk_score) × trust_adjustment`.
   - `trust_adjustment` = ClawVault strategy trust score from decisions/ vault.
   - Macros below `scoring.macro_screening_threshold` are auto-rejected (logged with reason).
5. **→ Adapter:** `estimate_cost()` — estimate cost per macro.
6. At L0-L1: present ranked list to human via gate report. Human selects/rejects with structured reasons.
7. At L2+: agent selects top-K macros where confidence ≥ HIGH and score ≥ threshold, logs reasoning.

### Phase 2: Screening Funnel (Experiment Subagent, 30% budget)

**AIDE-inspired tree search adapted for any measurable pipeline:**

1. **Root nodes:** Each approved macro becomes a root in the search tree.
2. **Stage A — Static checks (free):**
   - **→ Adapter:** `validate_mutation()` — check config validity.
   - **→ Adapter:** `estimate_cost()` — verify within budget.
   - **→ Adapter:** `get_constraints()` — check constraint feasibility.
   - No LLM calls. Rejects invalid/infeasible configs before spending money.
3. **Stage B — Tiny-slice trials (execution path selected by `direction`):**
   - `prompt_strategy` / `llm_*` / `rag_*` → generate `promptfoo.yaml`, run `promptfoo eval --output results.json`, parse structured JSON output. Log to MLflow.
   - `prompt_optimization` → run DSPy compilation script (BootstrapFewShot or MIPRO), save optimized program artifact, then pass compiled output to `promptfoo eval` for formal scoring. Log both DSPy compile metrics and Promptfoo eval metrics to MLflow.
   - `hyperparameter` / `ml_*` → **→ Adapter:** `run_experiment()` with Optuna trial suggestion. Log to MLflow.
   - `structural` → AIDE tree-search variant. **→ Adapter:** `run_experiment()` on AIDE best_solution. Log to MLflow.
   - All paths: `eval_fraction: 0.10` for Stage B. ~5-10 minutes per trial.
4. **Stage C — Dev trials:** Promising macros get full dev-set evaluation (`eval_fraction: 1.0`). Same execution path selection. ~15-30 minutes per trial.
5. **Selection:** Rank by `metric_delta / cost_usd` (computed per hypothesis, not per trial). Freeze macro set for deepening.
6. **Tree branching:** Each trial result spawns child nodes (variations). Agent decides which branches to explore based on the result pattern.

### Phase 3: Deepening (Experiment Subagent, 70% budget)

1. For each surviving macro, generate micro hypotheses (bounded set).
2. **→ Adapter:** `run_experiment()` — execute trials with Optuna for numeric params + LLM-guided search for other mutations.
3. **Review cadence** (enforced by ReviewCadenceEnforcer hook):
   - At L0-L1: human reviews gate report.
   - At L2+: agent self-reviews, escalates only anomalies.
4. Stop conditions (enforced by BudgetGuard hook):
   - Budget exhausted.
   - Consecutive failures exceed threshold.
   - Holdout regression detected (hard stop).
5. Best configurations evaluated on holdout split (`eval_fraction: 1.0`, `eval_split: "holdout"`).

### Phase 4: Promotion (Promotion Subagent)

**Always requires human approval at L0-L2. At L3, agent promotes and human reviews post-hoc.**

1. Statistical significance check on holdout results (3x replicated eval, mean ± std).
2. Test suite pass (if repo has tests).
3. Cost-benefit analysis: improvement delta vs. per-hypothesis cost increase.
4. Generate change bundle: config diff, prompt diff, architecture diff.
5. Human approves promotion.
6. **→ ClawVault:** Update knowledge store:
   - `vault.remember("decisions/{strategy_id}.md", ...)` — update trust score, add this cycle's evidence.
   - `vault.remember("lessons/cycle_{id}_{task}.md", ...)` — record what worked, what failed, rejection patterns learned.
   - `vault.remember("handoffs/next_cycle_context.md", ...)` — set up continuity for next cycle.
   - Push local vault changes to global `blackbird-ahvs-knowledge` repo for cross-repo knowledge sharing.
7. Update autonomy record with cycle outcome.
8. Autonomy assessment: check promotion/demotion criteria, recommend level change.
9. **→ ClawVault:** `vault.sleep(summary="[one-line cycle outcome]")` — close session, write final checkpoint.

---

## 11. Claude Agent SDK Integration Details

**[Generic]** — the SDK integration is domain-agnostic. The adapter is invoked through the subagents' tool calls.

> **Architectural constraint (Principle 2):** The Claude Agent SDK is the current orchestration backbone, chosen for its MCP-native design and pioneer role in the agentic ecosystem. However, all AHVS core value — the knowledge store, domain adapters, autonomy logic, and hook implementations — must remain decoupled from SDK-specific internals. Key interfaces (knowledge store queries, hypothesis generation, adapter invocation) are exposed as MCP tools. If the orchestration layer is replaced in the future, these components migrate without restructuring. This section describes the current implementation; the interface contracts in §7, §9, and §6 are the durable specification.

### 11.1 Coordinator Agent

```python
from claude_agent_sdk import query, ClaudeAgentOptions, HookMatcher, AgentDefinition

async def run_hypothesis_cycle(workspace_path: str, run_id: str, adapter_type: str):
    async for message in query(
        prompt=f"""You are the Hypothesis Validation Coordinator.

        Workspace: {workspace_path}
        Run ID: {run_id}
        Adapter: {adapter_type}
        Knowledge Store: {workspace_path}/knowledge/

        Execute the hypothesis validation lifecycle:
        Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4

        All interactions with the target system go through the PipelineAdapter.
        At each gate, check your autonomy level in knowledge/autonomy_record.json
        and either proceed autonomously or ask the human via AskUserQuestion.

        Express confidence as one of: very_low, low, medium, high, very_high.
        Log all decisions with thought traces to runs/{run_id}/thought_traces.jsonl.
        Write gate reports to runs/{run_id}/.
        """,
        options=ClaudeAgentOptions(
            allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep",
                          "AskUserQuestion", "Agent"],
            max_turns=200,
            max_budget_usd=50.00,
            hooks={
                "PreToolUse": [
                    HookMatcher(matcher="Bash", hooks=[budget_guard, safety_checker]),
                    HookMatcher(matcher="Agent", hooks=[gate_enforcer]),
                ],
                "PostToolUse": [
                    HookMatcher(matcher="Bash", hooks=[result_logger, review_cadence_enforcer]),
                ]
            },
            agents={
                "onboarding": AgentDefinition(
                    description="Parse repo, build task contract via adapter, run baseline",
                    tools=["Read", "Bash", "Glob", "Grep", "Write"]
                ),
                "hypothesis-generator": AgentDefinition(
                    description="Generate and score macro/micro hypotheses using knowledge store, rejection history, and adapter hypothesis space",
                    tools=["Read", "Write", "Bash", "Grep"]
                ),
                "experiment-runner": AgentDefinition(
                    description="Execute trial specs via adapter, validate before running, log results and per-call costs",
                    tools=["Read", "Write", "Bash", "Edit"]
                ),
                "reviewer": AgentDefinition(
                    description="Generate gate reports, check stop conditions, prepare shadow score batches",
                    tools=["Read", "Write", "Bash"]
                ),
                "promoter": AgentDefinition(
                    description="Evaluate promotion candidates, generate change bundles, update knowledge store",
                    tools=["Read", "Write", "Bash", "Edit", "AskUserQuestion"]
                ),
            }
        )
    )
```

### 11.2 Hook: Gate Enforcer

**[Generic]**

```python
# Decision requirements mapping (from §6.2 matrix)
DECISION_REQUIREMENTS = {
    "generate_macros":       0,   # agent can always generate; approval is separate
    "approve_macro":         2,   # L2+ can approve autonomously (if HIGH+ confidence)
    "reject_macro":          2,   # L2+ can reject autonomously (if HIGH+ confidence)
    "execute_trial":         1,   # L1+ can execute within approved macros
    "stop_macro_branch":     2,   # L2+ can stop failing branches
    "trigger_review":        2,   # L0-L1 always human; L2+ self-review
    "promote_config":        3,   # L3 only for autonomous promotion
    "increase_budget":       99,  # always human (effectively unreachable)
    "add_strategy_type":     3,   # L3 can propose (still needs human confirm)
    "run_parallel_cycles":   3,   # L3 only
}

async def gate_enforcer(input_data, tool_use_id, context):
    """Enforce human approval at gates based on autonomy level and confidence."""
    autonomy = load_autonomy_record()
    decision_type = classify_decision(input_data)
    confidence = extract_confidence(context)  # parse from agent's thought trace

    required_level = DECISION_REQUIREMENTS.get(decision_type, 0)

    # Check autonomy level
    if autonomy.current_level < required_level:
        return deny(f"Autonomy L{autonomy.current_level} < required L{required_level} for {decision_type}. Ask human.")

    # Check confidence routing (even if level is sufficient)
    action = DecisionRouter().route(decision_type, confidence, autonomy.current_level)
    if action == "escalate":
        return deny(f"Confidence {confidence.value} too low for autonomous {decision_type}. Ask human.")

    # Log autonomous decision for shadow scoring
    log_shadow_decision(decision_type, confidence, context)

    return None  # allow
```

### 11.3 Hook: Budget Guard

**[Generic]**

```python
async def budget_guard(input_data, tool_use_id, context):
    """Enforce budget limits and stop conditions before experiment execution."""
    budget_state = load_budget_state()

    if budget_state.total_cost_usd >= budget_state.max_cost_usd:
        return hard_stop("Budget exhausted")

    if budget_state.consecutive_failures >= budget_state.max_consecutive_failures:
        return hard_stop("Too many consecutive failures")

    if budget_state.wallclock_hours >= budget_state.max_wallclock_hours:
        return hard_stop("Wall-clock time limit reached")

    # Check per-hypothesis cost against estimate (warn at 80%, stop at budget_overshoot)
    current_macro = detect_current_macro(context)
    if current_macro:
        macro_cost = budget_state.cost_by_macro.get(current_macro.id, 0.0)
        if macro_cost > current_macro.estimated_cost_usd * (1 + budget_state.budget_overshoot_hard_stop):
            return hard_stop(f"Macro {current_macro.id} exceeded cost estimate by >{budget_state.budget_overshoot_hard_stop:.0%}")

    return None  # allow
```

### 11.4 Hook: Safety Checker

**[Generic]** — protected paths come from config, not hardcoded.

```python
async def safety_checker(input_data, tool_use_id, context):
    """Pre-flight validation before any Bash execution."""
    command = input_data.get("command", "")

    # 1. Protected path check: don't modify eval sets, core code, knowledge store during experiments
    protected_patterns = load_protected_paths()  # from config: sandbox_policy.protected_paths
    for pattern in protected_patterns:
        if pattern in command:
            return deny(f"Command touches protected path: {pattern}")

    # 2. Untracked API call check: all external calls must go through the pipeline entry point
    api_call_patterns = load_api_patterns()  # from config: sandbox_policy.api_call_patterns
    pipeline_entry = load_pipeline_entry_point()  # from TaskContract
    for pattern in api_call_patterns:
        if pattern in command and pipeline_entry not in command:
            return deny(f"Direct API call detected outside pipeline. Use pipeline entry point.")

    # 3. Cost estimate check: if this looks like an experiment run, verify it was pre-estimated
    if pipeline_entry in command:
        trial_id = extract_trial_id(command)
        if trial_id and not has_cost_estimate(trial_id):
            return deny(f"Trial {trial_id} has no cost estimate. Run adapter.estimate_cost() first.")

    return None  # allow
```

### 11.5 Hook: Result Logger

**[Generic]**

```python
async def result_logger(input_data, tool_use_id, context, result):
    """After every Bash execution that runs an experiment, parse and log results."""
    command = input_data.get("command", "")
    pipeline_entry = load_pipeline_entry_point()

    if pipeline_entry not in command:
        return None  # not an experiment, skip

    # Parse trial output from Bash result
    trial_id = extract_trial_id(command)
    metrics = parse_metrics_from_output(result)
    cost_breakdown = parse_cost_from_output(result)

    if trial_id and metrics:
        # Write to trials.jsonl
        append_jsonl("trials.jsonl", {
            "trial_id": trial_id,
            "metrics": metrics,
            "cost_breakdown": cost_breakdown,
            "cost_usd": sum(c["cost_usd"] for c in cost_breakdown),
            "timestamp": now_iso(),
        })

        # Log to MLflow
        mlflow_log_trial(trial_id, metrics, cost_breakdown)

        # Update per-hypothesis cost accumulator
        macro_id = get_macro_for_trial(trial_id)
        update_hypothesis_cost(macro_id, sum(c["cost_usd"] for c in cost_breakdown))

    return None  # don't modify the result
```

### 11.6 Hook: Review Cadence Enforcer

**[Generic]**

```python
async def review_cadence_enforcer(input_data, tool_use_id, context, result):
    """After experiment execution, check if a review gate is due."""
    command = input_data.get("command", "")
    pipeline_entry = load_pipeline_entry_point()

    if pipeline_entry not in command:
        return None

    review_state = load_review_state()
    review_state.trials_since_last_gate += 1

    config = load_review_config()

    gate_due = False
    if config.mode == "trial_count" and review_state.trials_since_last_gate >= config.every_n_trials:
        gate_due = True
    elif config.mode == "time" and minutes_since(review_state.last_gate_time) >= config.every_minutes:
        gate_due = True

    if config.on_risk_event and detect_anomaly(result):
        gate_due = True

    if gate_due:
        review_state.trials_since_last_gate = 0
        review_state.last_gate_time = now_iso()
        save_review_state(review_state)

        # Signal to coordinator that a gate report is needed
        write_gate_trigger(review_state.gate_number)

    return None
```

---

## 12. Experiment Reproducibility

**[Generic]**

### 12.1 What We Pin

| Element | How |
|---------|-----|
| LLM model versions | Exact model strings in `api_version_pins` (adapter populates relevant pins) |
| Prompts/configs | SHA-256 hash stored in `prompt_snapshot_hash` |
| Eval dataset | Frozen per cycle, integrity verified via `eval_dataset_checksum` |
| Pipeline config | Full JSON config stored per trial |
| Random seeds | Fixed `seed` + `eval_sample_seed` per trial |
| Package versions | `requirements.txt` / `pyproject.toml` pinned |

### 12.2 What We Accept as Non-Deterministic

LLM API calls are inherently non-deterministic (even with temperature=0). We handle this by:
- Running critical evaluations `eval_replications` times (default 3) and reporting mean ± std.
- Flagging results where std > threshold as "noisy — needs more samples."
- Using statistical significance tests (paired t-test or bootstrap) before promotion.

---

## 13. Configuration

**[Generic skeleton]** with adapter-specific values shown as examples.

```yaml
# hypothesis_config.yaml

workspace_path: /path/to/target-repo
adapter_type: autoqa                    # which PipelineAdapter to load
task_family: cohort_classification      # [Adapter-Specific] — set per domain

autonomy:                               # [Generic]
  initial_level: 0                      # start as Apprentice
  promotion_min_cycles: 5
  promotion_min_agreement_rate: 0.85
  promotion_max_regression_rate: 0.05
  promotion_min_calibration: 0.80
  demotion_consecutive_regressions: 2
  demotion_miscalibration_threshold: 0.30
  demotion_budget_overrun_rate: 0.20
  shadow_audit_every_n_cycles: 5

confidence:                             # [Generic]
  calibration_min_samples_per_class: 10

scoring:                                # [Generic]
  macro_rank_formula: "evidence_score * (1 - risk_score) * trust_adjustment"
  macro_screening_threshold: 0.40
  holdout_split_ratio: 0.20

budget:                                 # [Generic structure, values tuned per domain]
  max_trials: 100
  max_cost_usd: 200.00
  max_wallclock_hours: 24
  screening_budget_ratio: 0.30
  deepening_budget_ratio: 0.70

experiment:                             # [Generic]
  eval_replications: 3
  tiny_slice_fraction: 0.10
  max_concurrent_trials: 1             # sequential ≤L2, parallel at L3
  trial_timeout_minutes: 30

review:                                 # [Generic]
  mode: trial_count
  every_n_trials: 10
  every_minutes: 60
  on_risk_event: true

stop:                                   # [Generic]
  holdout_regression_threshold: 0.01
  consecutive_failures_hard_stop: 3
  budget_overshoot_hard_stop: 0.15

search:                                 # [Generic]
  numeric_backend: optuna
  prompt_backend: promptfoo             # was llm_guided — now uses Promptfoo for structured eval
  prompt_optimization_backend: dspy    # DSPy→Promptfoo two-step for prompt_optimization hypotheses
  architecture_backend: llm_guided

tracking:                               # [Generic]
  backend: mlflow
  experiment_name: "{adapter_type}-hypothesis-{run_id}"

knowledge:                              # [Generic]
  backend: clawvault                    # replaces flat JSONL
  local_vault_path: ./.ahvs/knowledge/vault/
  global_vault_repo: blackbird-ahvs-knowledge  # cross-repo knowledge sharing
  trust_decay_rate: 0.05
  min_trust_to_apply: 0.30
  negative_transfer_penalty: 0.15
  success_increment: 0.10
  failure_penalty_high_trust: 0.15
  failure_penalty_low_trust: 0.10

promptfoo:                              # [Generic — tuned per domain]
  config_template: ./.ahvs/templates/promptfoo_base.yaml
  output_path: ./.ahvs/tool_runs/promptfoo/
  providers:                            # [Adapter-Specific] — set per domain
    - anthropic:claude-sonnet-4-6
    - anthropic:claude-haiku-4-5-20251001
  eval_timeout_seconds: 300

dspy:                                   # [Generic — used only for prompt_optimization hypotheses]
  default_optimizer: BootstrapFewShot   # or MIPRO for larger search spaces
  max_bootstrapped_demos: 4
  output_path: ./.ahvs/tool_runs/dspy/
  eval_handoff: promptfoo               # always feed compiled output to Promptfoo for formal eval

sandbox:                                # [Adapter-Specific paths]
  protected_paths:                      # — set per domain
    - "eval/"
    - "knowledge/"
    - "src/core/"
  experiment_paths:
    - "experiments/"
    - "sandbox/"
  api_call_patterns:                    # [Adapter-Specific] — what counts as an external API call
    - "curl"
    - "requests.post"
    - "openai."
    - "anthropic."

cohort:                                 # [Adapter-Specific if applicable]
  scope: shared
```

---

## 14. Logging and Artifacts

**[Generic]** — identical structure regardless of domain.

```
runs/{run_id}/
├── run_manifest.json                     # full config, repo fingerprint, git SHA, eval checksum, adapter_type
├── baseline_report.md                    # Phase 0 output
├── hypotheses.jsonl                      # all macros and micros with state transitions and rejection reasons
├── trials.jsonl                          # every trial spec and result with cost breakdowns
├── thought_traces.jsonl                  # agent reasoning per decision (ReAct traces)
├── gates.jsonl                           # all gate decisions with approver and reasoning
├── events.jsonl                          # chronological execution log
├── autonomy_decisions.jsonl              # every decision routing with confidence class + shadow decision data
├── gate_report_{k}.md                    # periodic review reports
├── final_report.md                       # end-of-cycle summary
├── executive_summary.json                # machine-readable outcomes
├── artifacts/
│   └── {trial_id}/                       # per-trial: metrics, outputs, diffs, error analysis, cost breakdown
├── search_tree.json                      # AIDE-style tree of explored variations with parent_trial_id lineage
├── knowledge_diff.json                   # what was added/updated in ClawVault this cycle
├── tool_runs/
│   ├── promptfoo/
│   │   ├── {trial_id}_config.yaml        # promptfoo eval config generated for this trial
│   │   └── {trial_id}_results.json       # structured promptfoo eval output (parsed by result_logger hook)
│   ├── dspy/
│   │   ├── {macro_id}_optimizer.py       # DSPy compilation script generated for prompt_optimization macro
│   │   └── {macro_id}_optimized.json     # compiled DSPy program artifact (logged to MLflow)
│   └── optuna/
│       └── {macro_id}_study.py           # Optuna study script for hyperparameter macros
└── .ahvs/knowledge/vault/               # ClawVault symlink — human-auditable knowledge store for this cycle
```

**Log-to-report mapping** (which files feed which reports):

| Report Section | Source Log Files |
|----------------|-----------------|
| Gate: Budget status | `trials.jsonl` (aggregate cost_usd per macro_id) |
| Gate: Autonomy decisions | `autonomy_decisions.jsonl` (count by confidence class) |
| Gate: Progress | `hypotheses.jsonl` + `trials.jsonl` (macro status, best metric_delta) |
| Gate: Risks | `events.jsonl` (anomaly events) + `trials.jsonl` (regression detection) |
| Final: Baseline vs Best | `trials.jsonl` (baseline trial vs best trial, with significance from replications) |
| Final: Lineage | `hypotheses.jsonl` (macro→micro) + `search_tree.json` (parent_trial_id chain) |
| Final: What Didn't Work | `hypotheses.jsonl` (rejected/failed macros) + `thought_traces.jsonl` (reasoning) |
| Final: Knowledge Updates | `knowledge_diff.json` |
| Final: Autonomy Assessment | `autonomy_decisions.jsonl` (agreement_rate, regression_rate, calibration_score) |
| Final: Cost Summary | `trials.jsonl` (aggregate by macro_id = per-hypothesis cost) |

---

## 15. Reporting

**[Generic]** — report templates are domain-agnostic. The adapter's metric names appear in the tables but the structure is universal.

### Gate Report (every N trials)

```markdown
# Gate Report #{k} — Run {run_id}
## Adapter: {adapter_type}
## Status: {screening | deepening}
## Budget: {used}/{total} trials, ${cost_used}/${cost_total}
## Autonomy Level: L{level} ({name})

### Progress
- Trials completed: N
- Macros active: [list with current scores and per-hypothesis costs]
- Best improvement so far: +X% on {metric} (macro: {id})

### Decisions Made Autonomously
- {count} decisions at HIGH/VERY_HIGH confidence
- {count} decisions at MEDIUM confidence (flagged)
- {count} escalated to human (LOW/VERY_LOW)

### Risks
- [any anomalies, regressions, or noisy results]
- [any macro branches approaching cost estimate limits]

### Requested Decision
- [what the agent needs from the human, if anything]
```

### Final Report

```markdown
# Final Report — Run {run_id}
## Adapter: {adapter_type}
## Outcome: {improved | no_improvement | stopped_early}

### Baseline → Best
| Metric | Baseline | Best | Delta | p-value | Replications (mean ± std) |
|--------|----------|------|-------|---------|---------------------------|

### What Worked
- [macro → micro lineage of winning configuration]
- [thought trace of why this worked]
- [per-hypothesis cost for winning path]

### What Didn't Work
- [failed macros with reasoning about why]
- [human rejection patterns applied]
- [per-hypothesis cost for failed paths]

### Knowledge Store Updates
- [new priors added, trust scores changed]
- [rejection patterns learned]

### Autonomy Assessment
- Confidence calibration score: X%
- Agreement rate (from shadow scoring): X%
- Regression rate: X%
- Recommendation: {promote | maintain | demote} to L{N}
- Reasoning: [why this recommendation]

### Cost Summary
- Total trials: N
- Total cost: $X (broken down by hypothesis)
- Cost per improvement point: $X
| Macro Hypothesis | Trials | Cost | Outcome |
|-----------------|--------|------|---------|
```

---

## 16. First Adapter: AutoQA LLM Classification Pipeline

**[Adapter-Specific]** — this section is entirely specific to the first instantiation. It serves as both the working implementation and a reference example for future adapters.

```python
class AutoQAPipelineAdapter(PipelineAdapter):
    """
    Concrete adapter for LLM-based cohort classification pipelines.
    First instantiation of the generic PipelineAdapter interface.
    """

    def discover_contract(self, workspace_path: str) -> TaskContract:
        """Parse AutoQA repo to extract pipeline config, eval sets, and metrics."""
        # Read config files (YAML/JSON)
        # Identify eval dataset location and format
        # Compute eval_dataset_checksum
        # Detect objective metric from existing eval scripts
        # Return TaskContract with:
        #   task_family="cohort_classification"
        #   objective_metric="f1_macro"
        #   pipeline_entry_point="python run_pipeline.py --config {config_path}"

    def run_baseline(self, contract: TaskContract) -> TrialResult:
        """Execute current pipeline config on dev split."""
        # Verify eval dataset checksum
        # Run: python run_pipeline.py --config {baseline_config} --split dev
        # Parse output metrics and per-call cost breakdown
        # Return TrialResult

    def run_experiment(self, trial_spec: TrialSpec) -> TrialResult:
        """Execute a trial with modified config."""
        # Write trial config to temp file
        # Apply eval_fraction subsampling with eval_sample_seed
        # Run: python run_pipeline.py --config {trial_config} --split {split} --fraction {fraction} --seed {seed}
        # Parse output metrics and per-call cost breakdown
        # Return TrialResult

    def validate_mutation(self, mutation: dict, current_config: dict) -> tuple[bool, str]:
        """Check if a mutation produces a valid pipeline config.
        Examples of invalid mutations specific to AutoQA:
        - num_judges: 3 with judge_mode: single (contradictory)
        - temperature: 2.0 (out of range)
        - model: nonexistent-model-name
        Returns (is_valid, reason_if_invalid).
        """

    def estimate_cost(self, trial_spec: TrialSpec, contract: TaskContract) -> float:
        """Estimate cost before execution.
        Formula: sample_count × eval_fraction × avg_tokens_per_sample × price_per_token × num_judges
        Uses model pricing from api_version_pins.
        """

    def get_constraints(self, contract: TaskContract) -> dict:
        """Return AutoQA-specific constraint bounds."""
        return contract.constraints
        # Typical: {"max_cost_per_sample_usd": 0.05, "max_latency_ms": 5000}

    def get_hypothesis_space(self) -> dict:
        """Define what the agent can mutate in AutoQA pipelines."""
        return {
            "prompt_strategies": {
                "system_prompt": "str",
                "few_shot_examples": "list[dict]",
                "chain_of_thought": "bool",
                "output_format": "str",
            },
            "pipeline_architecture": {
                "judge_mode": ["single", "majority_vote", "weighted_ensemble"],
                "num_judges": "int[1-5]",
                "judge_models": "list[str]",
                "aggregation": ["majority", "weighted", "meta_judge"],
            },
            "numeric_params": {
                "temperature": "float[0.0-1.0]",
                "top_k": "int[1-100]",
                "confidence_threshold": "float[0.0-1.0]",
                "max_tokens": "int[100-4000]",
            },
            "model_selection": {
                "primary_model": ["claude-sonnet-4-6", "claude-haiku-4-5", "gpt-4o", "gpt-4o-mini"],
                "fallback_model": ["claude-haiku-4-5", "gpt-4o-mini", "none"],
            }
        }
```

---

## 17. Adding a New Domain (Adapter Checklist)

**[Generic]** — the steps to add any new domain.

To bring the hypothesis validation system to a new domain, you need exactly these artifacts:

| # | Artifact | Description | Example (AutoQA) |
|---|----------|-------------|-----------------|
| 1 | `PipelineAdapter` subclass | Implement all 7 methods from §7 | `AutoQAPipelineAdapter` |
| 2 | Bootstrap strategy taxonomy | JSON array of strategies at trust 0.5 | 12 LLM-classification strategies |
| 3 | Labeled eval dataset | Ground-truth data for measuring improvement | Cohort classification labels |
| 4 | Config overlay | `hypothesis_config.yaml` with domain-specific values | AutoQA paths, API patterns, constraints |
| 5 | (Optional) Custom constraint definitions | Domain-specific guardrails | `max_cost_per_sample_usd` |

**What you do NOT need to change:**
- Coordinator agent
- Subagent definitions
- Hook implementations
- Knowledge store schema
- Autonomy ladder
- Confidence system
- Reporting templates
- Logging structure
- MLflow/Optuna integration

**Planned future adapters (not in scope for V6 — listed by R&D domain):**

| Domain | Adapter | Notes |
|--------|---------|-------|
| ML model development | `MLTrainingAdapter` | Traditional model training (GPU experiments, learning rate search, architecture search) |
| RAG / LLM-based systems | `RAGPipelineAdapter` | Retrieval-augmented generation tuning: chunk size, reranking, query expansion |
| Blackbird-specific algorithms | `BlackbirdAlgorithmAdapter` | Proprietary algorithm parameters, narrative scoring models, actor network heuristics |
| Multimodal systems | `MultimodalPipelineAdapter` | Cross-modal fusion strategies, vision-language model selection, modality weighting |
| Data processing | `DataProcessingAdapter` | ETL/data quality pipelines, feature engineering strategies |

Each future adapter requires only the 5-artifact checklist above (§17). Zero changes to the framework.

---

## 18. Implementation Roadmap

### Milestone 1: Walking Skeleton — Generic Framework + AutoQA Adapter (2-3 weeks)
- [ ] Define `PipelineAdapter` ABC with all 7 abstract methods
- [ ] AutoQA adapter: implement all 7 methods (discover_contract, run_baseline, run_experiment, validate_mutation, estimate_cost, get_constraints, get_hypothesis_space)
- [ ] Claude Agent SDK coordinator with subagent definitions and tool scoping
- [ ] Implement hooks: gate_enforcer, budget_guard, safety_checker, result_logger
- [ ] Phase 0 + Phase 1 (fully L0, human approves everything)
- [ ] Basic MLflow logging with per-call cost tracking
- [ ] Manual hypothesis generation (agent proposes, human selects with structured rejection reasons)
- [ ] **ClawVault setup**: initialize local vault at `.ahvs/knowledge/vault/`, implement `vault.wake()` / `vault.sleep()` calls at cycle boundaries, wire `vault.search()` into Hypothesis Subagent
- [ ] **Promptfoo setup**: install and configure Promptfoo, create base `promptfoo.yaml` template, verify structured JSON output parsing in result_logger hook
- [ ] **Expose core interfaces as MCP tools**: knowledge store read/write, adapter invocation, hypothesis generation — ensuring portability across orchestration frameworks and future shadow company integration
- [ ] **Verify orchestration decoupling**: no AHVS core logic in SDK-specific internals; confirm all valuable state lives in the knowledge store and adapter, not in agent session memory

### Milestone 2: Experiment Loop (2-3 weeks)
- [ ] Phase 2 screening funnel with tree-search pattern (Stage A/B/C)
- [ ] **Domain routing**: implement `direction`-based execution path selection (Promptfoo / DSPy→Promptfoo / Optuna / AIDE)
- [ ] **Promptfoo execution path**: agent generates `promptfoo.yaml` per trial, fires `promptfoo eval`, result_logger parses JSON output and logs to MLflow
- [ ] **DSPy execution path**: agent generates DSPy optimizer script for `prompt_optimization` hypotheses, runs compilation, passes compiled output to Promptfoo eval, logs both phases to MLflow
- [ ] Phase 3 deepening with Optuna for numeric params + Promptfoo for prompt mutations
- [ ] Gate reports with per-hypothesis cost reporting
- [ ] Review cadence enforcement hook
- [ ] Stop conditions (budget, failures, holdout regression)
- [ ] Eval set integrity verification (checksums)

### Milestone 3: Knowledge and Autonomy (2-3 weeks)
- [ ] Bootstrap ClawVault knowledge store with AutoQA strategy taxonomy (§9.5) — seed `decisions/` vault with initial strategies at trust 0.5
- [ ] Trust scoring and update rules with configurable coefficients — write outcomes to `decisions/{strategy_id}.md`
- [ ] Rejection learning: structured reasons → negative evidence on strategies → `lessons/rejections.md`
- [ ] **Global vault setup**: create `blackbird-ahvs-knowledge` repo, implement sync of local vault → global vault at Phase 4 step 6
- [ ] Discrete confidence classes: agent assessment + routing table
- [ ] Autonomy ladder: L0 → L1 promotion logic with calibration tracking
- [ ] Autonomy record tracking and shadow decision logging

### Milestone 4: Polish and Harden (1-2 weeks)
- [ ] Final report generation with full log-to-report mapping
- [ ] Reproducibility: prompt snapshots, API version pinning, eval checksums
- [ ] Resume after interruption (Claude Agent SDK session resumption)
- [ ] End-to-end test: full cycle on AutoQA repo at L0
- [ ] **Verify framework/adapter separation:** run with a mock adapter to confirm no AutoQA leakage in generic code

### Milestone 5: Progressive Autonomy in Practice (ongoing)
- [ ] L1 → L2 promotion after sufficient history
- [ ] Knowledge store growing across cycles
- [ ] Agent becoming better at hypothesis generation (fewer rejections over time)
- [ ] Shadow scoring UX for L2+ audit (detailed design deferred to when L2 is reached)
- [ ] L3: parallel cycle support
- [ ] Reduced human involvement per cycle (measured and tracked)

### Milestone 6: Second Domain Adapter (future — validates generality)
- [ ] Implement a second PipelineAdapter (e.g., RAGPipelineAdapter)
- [ ] Confirm zero changes to framework code
- [ ] Validate knowledge transfer: does AutoQA experience help on the new domain?
- [ ] Document lessons learned for adapter authoring

---

## 19. Design Decisions Log

All open questions from V4 have been resolved. V5 adds the abstraction clarity decisions:

| # | Question | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | Eval dataset management | Human-curated, frozen per cycle. Agent can flag issues but not modify. | Avoids "grading own homework" problem. |
| 2 | Multi-cohort coordination | Hypotheses shared across entire cohort set. Knowledge store enables cross-cohort transfer. | Maximizes learning signal. Isolation can be added later if needed. |
| 3 | Cost attribution | Per-hypothesis (aggregated from per-call logging). | Right granularity for ROI decisions on strategy directions. |
| 4 | Human rejection learning | Structured rejection reasons stored in knowledge store. Agent learns patterns to improve future proposals. | Key mechanism for agent getting smarter from human judgment, not just experiments. |
| 5 | Concurrent cycles | Sequential at L0-L2. Parallel at L3 only. | Avoids resource contention and attribution complexity until agent is proven. |
| 6 | Confidence representation | Discrete 5-class (very_low → very_high), not continuous 0-1. | Avoids false precision. More natural for LLM self-assessment. Easier to calibrate. |
| 7 | Agreement rate measurement | Shadow scoring: agent logs would-have-asked decisions; human audits sample every 5th cycle. | Enables calibration without requiring human review of every decision. |
| 8 | Phase 0 frequency | Once per new repo or eval set change. Subsequent cycles skip to Phase 1. | Avoids redundant onboarding. |
| 9 | Knowledge bootstrap | Human-seeded with domain-specific strategies at trust 0.5. Agent proposes new ones over time. | Cold-start solution. Neutral trust means no bias. |
| **10** | **Generic vs. specific framing** | **Framework is domain-agnostic. Only the PipelineAdapter is domain-specific. §2 Abstraction Architecture is a first-class section.** | **Enables future domain expansion without framework changes. The §2 rule: "If you're modifying the coordinator to support a new domain, you're doing it wrong."** |
| **11** | **Abstraction boundary** | **7-method PipelineAdapter ABC (§7).** | **Minimal surface area. Proven by first adapter (AutoQA). Future adapters validate the interface.** |
| **12** | **Annotation convention** | **[Generic] and [Adapter-Specific] tags on every section.** | **Reader always knows which layer they're looking at. Prevents accidental coupling during implementation.** |
| **13** | **Orchestration layer as replaceable infrastructure** | **Claude Agent SDK is the current backbone but must not hold proprietary AHVS logic. All core assets (knowledge store, adapters, autonomy logic) are exposed as MCP tools. Swapping the orchestration layer must be a contained infrastructure change.** | **Protects against platform obsolescence. Anthropic, Google, and OpenAI will continue improving orchestration capabilities. AHVS's durable value is in accumulated domain knowledge, not in orchestration wiring. MCP-first design ensures portability across any orchestration framework that speaks MCP.** |
| **14** | **AHVS as R&D agent family within the shadow company** | **AHVS is not a standalone system. It is the R&D layer of Blackbird's broader agentic shadow company. It uses shadow company primitives: MCP tools, Context Graph as the knowledge layer, authority boundaries (L0–L3) aligned with the shadow company's agent identity model. AHVS must be plug-in compatible when the shadow company is built.** | **Ensures AHVS investment compounds into the broader organizational strategy rather than existing as an isolated tool. The knowledge store IS the R&D slice of the Context Graph. The autonomy ladder IS the authority boundary definition for R&D agents.** |
| **15** | **Promptfoo as LLM eval execution backend** | Promptfoo replaces ad-hoc `run_pipeline.py` calls for `prompt_strategy` and `llm_*` / `rag_*` domain hypotheses. Agent generates a `promptfoo.yaml` per trial; `promptfoo eval` produces structured JSON output parsed by result_logger. | Purpose-built for LLM eval: multi-provider comparison, reproducible configs, CI/CD-compatible, output schema designed for programmatic consumption. Avoids reinventing prompt eval tooling. |
| **16** | **DSPy as prompt optimization backend (actual tool, not just inspiration)** | DSPy is used as an actual execution dependency for `prompt_optimization` hypotheses, not just as an architectural inspiration. BootstrapFewShot / MIPRO optimizers compile the best program; output is handed to Promptfoo for formal evaluation. The Hypothesis Engine's DSPy-style self-improvement metaphor from §4.1 remains, but DSPy is now also a runtime tool. | DSPy and Promptfoo are complementary: Promptfoo *tests a specific prompt*, DSPy *finds the best prompt algorithmically*. Two-step pattern avoids conflating search with evaluation. |
| **17** | **ClawVault as knowledge store backend (replaces flat JSONL)** | The flat `knowledge/` JSONL files are replaced by a ClawVault vault at `.ahvs/knowledge/vault/`. Python SDK enables programmatic `vault.wake()` / `vault.remember()` / `vault.sleep()` in the agent loop. Two-tier structure: local vault per repo + shared `blackbird-ahvs-knowledge` global vault. | Search quality improvement for hypothesis generation (BM25+semantic vs. linear scan). Session lifecycle maps cleanly to cycle start/end. Git-compatible markdown is human-auditable. Python SDK enables full automation. At Blackbird's current scale, markdown-on-disk is sufficient; migrate to vector DB if concurrent write contention becomes an issue at high automation volume. |
| **18** | **Agency-Agents role templates inform L3 parallel-cycle subagent architecture** | At L3, the single Experiment Subagent is replaced by domain-specialized sub-agents (one per hypothesis type: Promptfoo executor, DSPy optimizer, Optuna tuner, AIDE mutator). Agency-Agents Testing division role templates (Performance Benchmarker, API Tester) define the behavioral contract for these sub-agents. | Agency-Agents provides 100+ validated agent role definitions rather than designing sub-agent behaviors from scratch. Specialized sub-agents at L3 enable true parallel hypothesis cycles. |

---

## 20. Key Differences from V4.1 → V5 → V6 Summary

### V4.1 → V5
1. **Generic-first framing** — Vision leads with the universal system, not AutoQA.
2. **§2 Abstraction Architecture** — explicit separation of generic framework vs. adapter-specific components as a first-class section.
3. **PipelineAdapter ABC** (§7) — formal abstract base class defined before the AutoQA implementation.
4. **[Generic]/[Adapter-Specific] annotations** throughout every section.
5. **Architecture diagram** — shows Pipeline Adapter Layer as a separate, swappable component.
6. **§17 Adding a New Domain** — actionable checklist replacing the 13-line §15 from V4.1.
7. **Milestone 6** — explicit roadmap step to validate generality with a second adapter.
8. **Design decisions #10-#12** — formalized the abstraction decisions.

### V5 → V6
9. **MCP-first, orchestration-agnostic** — Subtitle and Principle 2 updated. Claude Agent SDK is the current backbone, not a permanent dependency. All AHVS core value lives in MCP tools and domain-agnostic constructs.
10. **Shadow company alignment** — Principle 5 added. AHVS is formally positioned as the R&D agent family within Blackbird's agentic shadow company, using the same primitives (MCP tools, Context Graph, authority boundaries).
11. **Orchestration decoupling constraint** — §11 architectural note added. Explicitly states that no AHVS core logic may live in SDK-specific internals, and that swapping the orchestration layer must be a contained infrastructure change.
12. **Expanded future adapter roadmap** — §17 now lists the full R&D scope: ML model development, RAG/LLM-based systems, Blackbird-specific algorithms, multimodal systems, data processing.
13. **MCP exposure in Milestone 1** — Roadmap now includes explicit tasks to expose core interfaces as MCP tools and verify orchestration decoupling from day one.
14. **Design decisions #13-#14** — formalized orchestration-as-replaceable-infrastructure and AHVS-as-shadow-company-component.

### V6 → V7
15. **Promptfoo as LLM eval execution backend** — Added to §2.1, §4.1, §5 diagram, §10 Phase 2 execution paths, §13 config, §14 artifacts, §17 adapter checklist unchanged, §18 Milestone 1+2, §19 decision #15.
16. **DSPy upgraded from inspiration to actual runtime tool** — §4.1 now lists DSPy as direct reuse with two roles: (1) architectural inspiration for the Hypothesis Engine, (2) actual BootstrapFewShot/MIPRO optimizer for `prompt_optimization` hypotheses. DSPy→Promptfoo two-step pattern added throughout. §13 `dspy:` config block added.
17. **ClawVault replaces flat JSONL knowledge store** — §2.1 added ClawVault component, §4.1 added ClawVault to direct reuse, §5 diagram updated with ClawVault block, §9.1 complete restructure to ClawVault vault layout (decisions/, lessons/, tasks/, backlog/, handoffs/), §10 lifecycle adds `vault.wake()` at Phase 0 and `vault.sleep()` at Phase 4, two-tier architecture (local + global vault) defined, §13 `knowledge:` block updated, §14 artifacts adds vault symlink, §18 Milestone 1+3 adds ClawVault setup tasks, §19 decision #17.
18. **Domain routing rule** — New subsection added before Phase 0 in §10. Maps `direction` + `domain_tags` to execution backend: Promptfoo / DSPy→Promptfoo / Optuna / AIDE. `direction` field on `MacroHypothesis` now has formal values: `prompt_strategy`, `prompt_optimization`, `architecture`, `hyperparameter`, `structural`.
19. **Agency-Agents informs L3 sub-agent architecture** — §4.2 adds Agency-Agents architectural inspiration row. L3 parallel cycles now use domain-specialized sub-agents (one per hypothesis type) instead of a single Experiment Subagent. §19 decision #18.
20. **`search.prompt_backend` updated** — Config changed from `llm_guided` to `promptfoo` (prompt_strategy hypotheses) with separate `prompt_optimization_backend: dspy` for compilation hypotheses.
