# AHVS Local-Agent LLM Use Instruction

## Goal

Enable `researchclaw ahvs` to use a local ACP-compatible agent such as `Claude Code` or `Codex` for AHVS's own orchestration-time LLM calls, without forcing an external provider API key for those AHVS stages.

Keep a clear boundary:

- `AHVS orchestration/control-plane LLM calls` can use ACP (`Claude Code`, `Codex`, etc.).
- `Runtime inference inside the target repo / evaluated experiment code` should continue to use whatever that codebase already uses, which may still be an API key + model + base URL, unless separately rewired.

That distinction is the core design intent.

## Current State

AHVS currently assumes API-key-based LLM access and does not reuse ARC's existing ACP path.

Relevant files:

- [README_AHVS.md](/home/ubuntu/vision/AutoResearchClaw/README_AHVS.md)
- [researchclaw/ahvs/config.py](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/config.py)
- [researchclaw/ahvs/executor.py](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py)
- [researchclaw/ahvs/health.py](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/health.py)
- [researchclaw/cli.py](/home/ubuntu/vision/AutoResearchClaw/researchclaw/cli.py)
- [researchclaw/llm/__init__.py](/home/ubuntu/vision/AutoResearchClaw/researchclaw/llm/__init__.py)
- [researchclaw/llm/acp_client.py](/home/ubuntu/vision/AutoResearchClaw/researchclaw/llm/acp_client.py)
- [researchclaw/config.py](/home/ubuntu/vision/AutoResearchClaw/researchclaw/config.py)

### What already exists

The main ARC pipeline already supports local-agent execution through ACP:

- `create_llm_client()` returns `ACPClient` when `config.llm.provider == "acp"`.
- `ACPClient` is designed for local agent CLIs such as Claude/Codex/Gemini CLI.
- `researchclaw init` already exposes `acp` as a "no API key needed" option.

### What AHVS does today

AHVS bypasses the shared LLM factory and creates its own direct `LLMClient`:

- `_make_llm_client()` in [researchclaw/ahvs/executor.py](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py)
- `check_llm_connectivity()` in [researchclaw/ahvs/health.py](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/health.py)

This means AHVS:

- requires an API key today
- cannot use ACP today
- treats "no API key" as a hard preflight failure

## Desired Behavior

AHVS should support two modes for its own LLM steps:

1. `provider != acp`
   Use today's provider/API-key flow.

2. `provider == acp`
   Use local ACP agent sessions for AHVS orchestration prompts and skip API-key-based preflight requirements.

The local-agent support only applies to AHVS's own LLM usage:

- hypothesis generation
- validation planning
- reporting / memory write-up
- any other direct `llm.chat(...)` inside AHVS

It should not silently rewrite the target repo's own inference stack.

## Recommended Implementation

Use the shared ARC LLM factory instead of maintaining a second AHVS-only client path.

This is the cleanest option because:

- the ACP code already exists and is working
- CLI/config semantics stay consistent across ARC and AHVS
- future provider behavior stays centralized

## Code Changes

### 1. Extend `AHVSConfig` to carry provider and ACP settings

File:

- [researchclaw/ahvs/config.py](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/config.py)

Add fields analogous to ARC config:

- `llm_provider: str = "anthropic"` or `"openai-compatible"` depending on preferred default
- `llm_acp_agent: str = "claude"`
- `llm_acp_cwd: str = "."`
- `llm_acpx_command: str = ""`
- `llm_acp_session_name: str = "researchclaw-ahvs"`
- `llm_acp_timeout_sec: int = 1800`

Notes:

- Keep existing fields:
  - `llm_base_url`
  - `llm_api_key`
  - `llm_model`
  - `llm_api_key_env`
- AHVS should remain backward compatible for existing API-key-based usage.

### 2. Add CLI flags for AHVS provider selection

File:

- [researchclaw/cli.py](/home/ubuntu/vision/AutoResearchClaw/researchclaw/cli.py)

Add AHVS CLI args such as:

- `--provider`
- `--base-url`
- `--api-key`
- `--api-key-env`
- `--acp-agent`
- `--acpx-command`
- `--acp-session-name`
- `--acp-timeout-sec`

Suggested semantics:

- `--provider acp` means "use local Claude Code / Codex / other ACP agent"
- in ACP mode, `--model` is accepted for compatibility but not operationally required
- in non-ACP mode, current behavior should remain unchanged

At minimum, wire these values into `AHVSConfig`.

### 3. Replace AHVS's custom `_make_llm_client()` path with the shared factory

File:

- [researchclaw/ahvs/executor.py](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py)

Current problem:

- `_make_llm_client()` manually constructs `LLMClient`
- it special-cases Claude models, but has no concept of `provider == acp`

Recommended fix:

Build a lightweight temporary `RCConfig`-compatible object and pass it to:

- `researchclaw.llm.create_llm_client()`

Implementation options:

1. Best long-term:
   Add a small helper that converts `AHVSConfig` into an `RCConfig`-compatible structure.

2. Fastest:
   Create a minimal local shim object with a `.llm` member exposing:
   - `provider`
   - `base_url`
   - `api_key`
   - `api_key_env`
   - `primary_model`
   - `fallback_models`
   - `acp`

and then call `create_llm_client(shim_config)`.

Important:

- Do not maintain separate provider logic in AHVS if avoidable.
- The whole point is to reuse the tested shared LLM selection path.

### 4. Make AHVS preflight provider-aware

File:

- [researchclaw/ahvs/health.py](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/health.py)

Current problem:

- `check_llm_connectivity()` fails immediately if no API key exists
- that is correct for direct API providers, but wrong for ACP

Refactor `check_llm_connectivity()` so it accepts provider information, for example:

- `provider`
- `api_key`
- `model`
- `base_url`
- ACP settings

Behavior:

- If `provider == "acp"`:
  - instantiate via shared factory / `ACPClient`
  - call `.preflight()`
  - do not require API key

- Else:
  - preserve current API-key-based behavior

Then update:

- `run_ahvs_preflight()`
- Stage 1 setup in [researchclaw/ahvs/executor.py](/home/ubuntu/vision/AutoResearchClaw/researchclaw/ahvs/executor.py)

so they pass provider-aware LLM config.

### 5. Update README_AHVS.md

File:

- [README_AHVS.md](/home/ubuntu/vision/AutoResearchClaw/README_AHVS.md)

Document both supported modes:

#### API-provider mode

Example:

```bash
export ANTHROPIC_API_KEY=...
researchclaw ahvs --repo /path/to/repo --question "..." --model claude-opus-4-6
```

#### ACP local-agent mode

Example:

```bash
researchclaw ahvs \
  --repo /path/to/repo \
  --question "..." \
  --provider acp \
  --acp-agent codex
```

Also explicitly state:

- ACP removes the need for an external API key for AHVS orchestration calls
- target-repo runtime inference may still require its own credentials

## Suggested Internal Structure

To keep things simple, use one rule:

- AHVS orchestration LLM access should always come from the shared LLM factory.

That means:

- AHVS should not directly instantiate `LLMClient` unless there is a compelling reason
- AHVS should not duplicate Anthropic/OpenAI/ACP selection logic

## Minimal Patch Strategy

If the SWE wants the smallest viable change instead of a full config cleanup:

1. Add `llm_provider` and ACP fields to `AHVSConfig`
2. Add corresponding AHVS CLI flags
3. Replace `_make_llm_client()` in AHVS with a wrapper over `create_llm_client()`
4. Update `check_llm_connectivity()` to support `provider == "acp"`
5. Update README

That is enough to unlock Claude Code / Codex for AHVS itself.

## Example Behavior After Change

### Case A: AHVS uses Codex, target repo does not call external LLMs

- AHVS Stage 3/5/7 use ACP via Codex
- no external provider key needed for AHVS
- evaluation runs locally as before

### Case B: AHVS uses Claude Code, target repo hypothesis calls OpenAI

- AHVS orchestration uses ACP, no AHVS API key required
- generated or target runtime code still needs `OPENAI_API_KEY`
- this is expected and should remain explicit

### Case C: AHVS uses ACP, but target repo uses a local vLLM or Ollama endpoint

- AHVS orchestration uses ACP
- evaluated code uses local inference endpoint
- no external API key may be needed at all, depending on the target repo setup

## Testing Checklist

### Unit / integration checks

1. Existing AHVS provider mode still works
   - run with `--provider anthropic` or current default path
   - verify preflight still checks key + connectivity

2. ACP preflight works without API key
   - run AHVS with `--provider acp`
   - verify Stage 1 passes with no API key set

3. Hypothesis generation works via ACP
   - verify Stage 3 reaches `llm.chat(...)` and returns output through ACP

4. Validation/report stages work via ACP
   - verify later direct AHVS LLM stages also use the ACP client

5. Runtime inference remains unchanged
   - use a target repo whose evaluation script requires its own API key
   - confirm AHVS orchestration can run without its own key, while target eval still fails unless that repo's key is configured

### Failure-mode checks

1. `provider=acp` and `acpx` missing
   - clear, actionable preflight failure

2. `provider=acp` and agent binary missing
   - clear failure mentioning missing CLI, such as `codex` or `claude`

3. `provider!=acp` and API key missing
   - preserve today's clear failure

## Non-Goals

These should not be mixed into this patch unless intentionally planned:

- rewriting target-repo code to use ACP
- changing CodeAgent's experimental runtime inference model
- changing how evaluated code accesses provider credentials
- automatically injecting provider keys into the target repo

Those are separate concerns.

## Recommendation To SWE

Implement the shared-factory route, not a one-off AHVS ACP special case.

In short:

1. Add provider-aware config to AHVS
2. Route AHVS LLM creation through `create_llm_client()`
3. Make preflight provider-aware
4. Document the control-plane vs runtime-inference distinction clearly

That will let AHVS exploit `Claude Code` and `Codex` for its own orchestration while preserving explicit, separate handling for any real LLM inference performed by the evaluated codebase.
