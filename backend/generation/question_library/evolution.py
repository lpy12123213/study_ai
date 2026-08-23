from __future__ import annotations

import contextvars
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

GENERATOR_ROLE = "question_library_generator"
SUPERVISOR_ROLE = "question_library_supervisor"
ARBITER_ROLE = "question_library_arbiter"

GENERATOR_MODEL = "muse-spark-1.2-contributor"
SUPERVISOR_MODEL = "deepseek-v4-flash"
OPENCODE_GO_PROVIDER = "opencode_go"
GENERATOR_CALL_OUTPUT_TOKEN_LIMIT = 6_000
SUPERVISOR_CALL_OUTPUT_TOKEN_LIMIT = 4_000

ALLOWED_GENERATION_STRATEGIES = {"adaptive_evolution", "legacy_beam"}
ALLOWED_SUPERVISION_MODES = {"tiered_consensus", "single"}
ALLOWED_POLICY_MODES = {"champion", "shadow_compare", "fixed"}

PROMPT_MODULES: Dict[str, Dict[str, str]] = {
    "structure-core.v1": {
        "status": "champion",
        "text": "Make the core answer depend on a discoverable relation, invariant, boundary, or representation change.",
    },
    "condition-economy.v1": {
        "status": "champion",
        "text": "Every condition must be necessary or provide a deliberate boundary contrast; remove decorative redundancy.",
    },
    "misconception-transfer.v1": {
        "status": "champion",
        "text": "Target one plausible misconception and mutate a relation, constraint, boundary, or representation for transfer.",
    },
    "staged-demand.v1": {
        "status": "candidate",
        "text": "Order sub-demands from prediction to structural explanation to a compact formal check.",
    },
    "counterexample-shadow.v1": {
        "status": "shadow",
        "text": "When suitable, use a boundary case or counterexample to make the hidden condition visible.",
    },
}


@dataclass(frozen=True)
class PolicyIndividual:
    version: str
    status: str
    modules: tuple[str, ...]
    temperature: float
    spec_population: int
    branch_factor: int
    mutation_rate: float
    drafts_per_spec: int
    repair_rounds: int
    confidence_threshold: float

    def generation_config(self) -> dict:
        return {
            "beam_width": self.spec_population,
            "brainstorm_seed_count": self.spec_population,
            "skill_branch_factor": self.branch_factor,
            "reasoning_branch_factor": self.branch_factor,
            "trap_branch_factor": self.branch_factor,
            "surface_branch_factor": self.branch_factor,
            "drafts_per_spec": self.drafts_per_spec,
            "max_repair_rounds": self.repair_rounds,
        }

    def prompt_block(self) -> str:
        enabled_modules = [
            (module_id, str(PROMPT_MODULES[module_id]["text"] or "").strip())
            for module_id in self.modules
            if module_id in PROMPT_MODULES and str(PROMPT_MODULES[module_id].get("status") or "") != "shadow"
        ]
        if not enabled_modules:
            return ""
        body = "\n".join(
            f"  <module id=\"{module_id}\">{text}</module>" for module_id, text in enabled_modules
        )
        return f"<evolution_policy version=\"{self.version}\">\n{body}\n</evolution_policy>"


@dataclass
class EvolutionTrace:
    generation_strategy: str
    supervision_mode: str
    policy_mode: str
    policies: list[PolicyIndividual]
    muse_call_limit: int = 40
    deepseek_call_limit: int = 20
    muse_output_token_limit: int = 120_000
    deepseek_output_token_limit: int = 60_000
    # Explicit test-only escape hatch for models whose reasoning duration and
    # output size are not predictable. Call-count budgets remain enforced.
    unbounded_live_test: bool = False
    calls: list[dict] = field(default_factory=list)
    policy_fitness_values: Dict[str, list[float]] = field(default_factory=dict)
    arbitration_count: int = 0
    stop_reason: str = "completed"

    def reserve_call(self, role: str) -> None:
        generator = str(role or "") == GENERATOR_ROLE
        if not self.unbounded_live_test and self.stop_reason in {
            "muse_output_token_limit",
            "deepseek_output_token_limit",
        }:
            raise RuntimeError(f"question_generation_budget_exhausted:{self.stop_reason}")
        current = sum(1 for item in self.calls if bool(item.get("generator")) == generator)
        limit = self.muse_call_limit if generator else self.deepseek_call_limit
        if current >= limit:
            self.stop_reason = "muse_call_limit" if generator else "deepseek_call_limit"
            raise RuntimeError(f"question_generation_budget_exhausted:{self.stop_reason}")
        self.calls.append(
            {
                "role": str(role or ""),
                "generator": generator,
                "model": GENERATOR_MODEL if generator else SUPERVISOR_MODEL,
                "protocol": "responses" if generator else "chat_completions",
                "started_at_s": time.time(),
                "elapsed_s": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
            }
        )

    def record_call(self, *, role: str, model: str, protocol: str, usage: dict, elapsed_s: float) -> None:
        target = next(
            (
                item
                for item in reversed(self.calls)
                if item.get("role") == role and float(item.get("elapsed_s") or 0.0) <= 0.0
            ),
            None,
        )
        if target is None:
            return
        target.update(
            {
                "model": str(model or ""),
                "protocol": str(protocol or ""),
                "elapsed_s": max(0.0, float(elapsed_s or 0.0)),
                "input_tokens": _usage_int(usage, "input_tokens", "prompt_tokens"),
                "output_tokens": _usage_int(usage, "output_tokens", "completion_tokens"),
            }
        )
        if role == ARBITER_ROLE:
            self.arbitration_count += 1
        generator = role == GENERATOR_ROLE
        output_total = sum(
            int(item.get("output_tokens") or 0)
            for item in self.calls
            if bool(item.get("generator")) == generator
        )
        limit = self.muse_output_token_limit if generator else self.deepseek_output_token_limit
        if not self.unbounded_live_test and output_total > limit:
            self.stop_reason = "muse_output_token_limit" if generator else "deepseek_output_token_limit"

    def record_failure(self, *, role: str, error: str, fatal: bool) -> None:
        target = next(
            (
                item
                for item in reversed(self.calls)
                if item.get("role") == role and float(item.get("elapsed_s") or 0.0) <= 0.0
            ),
            None,
        )
        if target is not None:
            target["elapsed_s"] = max(0.0, time.time() - float(target.get("started_at_s") or time.time()))
            target["error_code"] = str(error or "provider_error").strip()[:160]
        if fatal:
            self.stop_reason = "provider_error"

    def record_fitness(self, *, strategy_version: str, fitness: float) -> None:
        version = str(strategy_version or "").strip()
        if not version:
            return
        self.policy_fitness_values.setdefault(version, []).append(max(0.0, min(1.0, float(fitness or 0.0))))

    def summary(self) -> dict:
        return {
            "generation_strategy": self.generation_strategy,
            "supervision_mode": self.supervision_mode,
            "policy_mode": self.policy_mode,
            "unbounded_live_test": self.unbounded_live_test,
            "strategy_versions": [policy.version for policy in self.policies],
            "generation_count": 2 if self.generation_strategy == "adaptive_evolution" else 1,
            "calls": len(self.calls),
            "muse_call_limit": self.muse_call_limit,
            "deepseek_call_limit": self.deepseek_call_limit,
            "muse_calls": sum(1 for item in self.calls if item.get("generator")),
            "deepseek_calls": sum(1 for item in self.calls if not item.get("generator")),
            "input_tokens": sum(int(item.get("input_tokens") or 0) for item in self.calls),
            "output_tokens": sum(int(item.get("output_tokens") or 0) for item in self.calls),
            "latency_s": round(sum(float(item.get("elapsed_s") or 0.0) for item in self.calls), 3),
            "arbitration_count": self.arbitration_count,
            "failed_calls": sum(1 for item in self.calls if str(item.get("error_code") or "").strip()),
            "policy_fitness": {
                version: round(sum(values) / max(1, len(values)), 4)
                for version, values in self.policy_fitness_values.items()
            },
            "stop_reason": self.stop_reason,
            "models": {
                "generator": GENERATOR_MODEL,
                "supervisor": SUPERVISOR_MODEL,
                "arbiter": SUPERVISOR_MODEL,
            },
            "protocols": {"generator": "responses", "supervisor": "chat_completions", "arbiter": "chat_completions"},
        }


_CURRENT_TRACE: contextvars.ContextVar[Optional[EvolutionTrace]] = contextvars.ContextVar(
    "question_generation_evolution_trace",
    default=None,
)


def bind_trace(trace: EvolutionTrace) -> contextvars.Token:
    return _CURRENT_TRACE.set(trace)


def reset_trace(token: contextvars.Token) -> None:
    _CURRENT_TRACE.reset(token)


def current_trace() -> Optional[EvolutionTrace]:
    return _CURRENT_TRACE.get()


def _usage_int(usage: Any, *keys: str) -> int:
    if not isinstance(usage, dict):
        return 0
    for key in keys:
        try:
            value = int(usage.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0


def _stable_unit(seed: str) -> float:
    raw = hashlib.sha256(str(seed or "").encode("utf-8", errors="ignore")).hexdigest()
    return int(raw[:8], 16) / 0xFFFFFFFF


def _clamp_choice(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def build_policy_population(*, generation_strategy: str, policy_mode: str, seed: str) -> list[PolicyIndividual]:
    strategy = str(generation_strategy or "adaptive_evolution").strip()
    mode = str(policy_mode or "champion").strip()
    if strategy == "legacy_beam":
        return [
            PolicyIndividual(
                version="legacy-beam.v1",
                status="fixed",
                modules=(),
                temperature=0.55,
                spec_population=6,
                branch_factor=2,
                mutation_rate=0.1,
                drafts_per_spec=1,
                repair_rounds=1,
                confidence_threshold=0.75,
            )
        ]

    champion_modules = ("structure-core.v1", "condition-economy.v1", "misconception-transfer.v1")
    policies: list[PolicyIndividual] = []
    size = 4 if mode == "shadow_compare" else 1
    for index in range(size):
        unit = _stable_unit(f"{seed}:{mode}:{index}")
        modules = champion_modules
        status = "champion" if index == 0 else "candidate"
        if index > 0 and mode == "shadow_compare":
            modules = (*champion_modules, "staged-demand.v1")
            status = "shadow"
        policies.append(
            PolicyIndividual(
                version=f"adaptive-{status}.v1.{index}",
                status=status,
                modules=modules,
                temperature=round(_clamp_choice(0.42 + 0.32 * unit, 0.3, 0.8), 2),
                spec_population=max(6, min(12, 6 + int(unit * 7))),
                branch_factor=max(1, min(3, 1 + int(unit * 3))),
                mutation_rate=round(_clamp_choice(0.1 + 0.25 * unit, 0.1, 0.35), 2),
                drafts_per_spec=1 if unit < 0.7 else 2,
                repair_rounds=1 if unit >= 0.25 else 0,
                confidence_threshold=round(_clamp_choice(0.72 + 0.16 * unit, 0.7, 0.9), 2),
            )
        )
    return policies[:4]


def create_trace(
    *,
    generation_strategy: str,
    supervision_mode: str,
    policy_mode: str,
    seed: str,
    unbounded_live_test: bool = False,
) -> EvolutionTrace:
    strategy = generation_strategy if generation_strategy in ALLOWED_GENERATION_STRATEGIES else "adaptive_evolution"
    supervision = supervision_mode if supervision_mode in ALLOWED_SUPERVISION_MODES else "tiered_consensus"
    mode = policy_mode if policy_mode in ALLOWED_POLICY_MODES else "champion"
    return EvolutionTrace(
        generation_strategy=strategy,
        supervision_mode=supervision,
        policy_mode=mode,
        policies=build_policy_population(generation_strategy=strategy, policy_mode=mode, seed=seed),
        muse_call_limit=60 if unbounded_live_test else 40,
        deepseek_call_limit=40 if unbounded_live_test else 20,
        unbounded_live_test=bool(unbounded_live_test),
    )


_MUSE_PRIVATE_KEYS = {
    "study_markdown",
    "study_markdown_brief",
    "reference_examples",
    "reference_example_stems",
    "reference_questions",
    "private_material",
    "raw_source",
}


def abstract_payload_for_muse(value: Any) -> Any:
    """Remove source text that must not be sent to the training-enabled Muse endpoint."""

    if isinstance(value, list):
        return [abstract_payload_for_muse(item) for item in value]
    if not isinstance(value, dict):
        return value
    out: dict = {}
    for key, item in value.items():
        normalized = str(key or "").strip().lower()
        if normalized in _MUSE_PRIVATE_KEYS:
            continue
        out[key] = abstract_payload_for_muse(item)
    return out


def sanitize_messages_for_role(messages: Iterable[dict], *, role: str) -> list[dict]:
    if role != GENERATOR_ROLE:
        return [dict(message or {}) for message in messages]
    sanitized: list[dict] = []
    for raw in messages:
        message = dict(raw or {})
        content = message.get("content")
        if isinstance(content, str):
            try:
                parsed = json.loads(content)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, (dict, list)):
                message["content"] = json.dumps(abstract_payload_for_muse(parsed), ensure_ascii=False)
        sanitized.append(message)
    return sanitized


def policy_for_index(trace: EvolutionTrace, index: int) -> PolicyIndividual:
    return trace.policies[int(index or 0) % max(1, len(trace.policies))]


def policy_fitness(
    *,
    passed: bool,
    confidence: float,
    evidence_count: int,
    usage: dict,
    latency_s: float,
    arbitrated: bool,
    difficulty_penalty: float = 0.0,
    imitation_penalty: float = 0.0,
) -> float:
    if evidence_count <= 0:
        return 0.0
    tokens = _usage_int(usage, "output_tokens", "completion_tokens")
    score = (
        (0.55 if passed else 0.0)
        + 0.25 * max(0.0, min(1.0, float(confidence or 0.0)))
        - min(0.1, tokens / 100_000.0)
        - min(0.06, max(0.0, float(latency_s or 0.0)) / 600.0)
        - (0.04 if arbitrated else 0.0)
        - max(0.0, min(0.24, float(difficulty_penalty or 0.0)))
        - max(0.0, min(0.30, float(imitation_penalty or 0.0)))
    )
    return round(max(0.0, min(1.0, score)), 4)


def lineage_metadata(*, policy: PolicyIndividual, generation: int, parent_id: str = "") -> dict:
    return {
        "strategy_version": policy.version,
        "policy_status": policy.status,
        "generation": max(0, min(1, int(generation or 0))),
        "parent_id": str(parent_id or "").strip(),
        "prompt_modules": list(policy.modules),
        "parameters": {
            "temperature": policy.temperature,
            "spec_population": policy.spec_population,
            "branch_factor": policy.branch_factor,
            "mutation_rate": policy.mutation_rate,
            "drafts_per_spec": policy.drafts_per_spec,
            "repair_rounds": policy.repair_rounds,
            "confidence_threshold": policy.confidence_threshold,
        },
    }


def strategy_store_path() -> Path:
    return (Path(__file__).resolve().parents[3] / ".local" / "question_library" / "evolution" / "policies.json").resolve()


def record_policy_outcomes(trace: EvolutionTrace, outcomes: Iterable[dict]) -> None:
    path = strategy_store_path()
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        current = {}
    records = current.get("policies") if isinstance(current.get("policies"), dict) else {}
    for raw in outcomes:
        if not isinstance(raw, dict):
            continue
        version = str(raw.get("strategy_version") or "").strip()
        if not version:
            continue
        existing = dict(records.get(version) or {})
        valid = int(existing.get("valid_candidates") or 0) + (1 if int(raw.get("evidence_count") or 0) > 0 else 0)
        status = str(existing.get("status") or raw.get("policy_status") or "candidate")
        benchmark_passed = bool(existing.get("benchmark_passed"))
        if status in {"shadow", "candidate"} and valid >= 20 and benchmark_passed:
            status = "champion"
        existing.update(
            {
                "version": version,
                "status": status,
                "valid_candidates": valid,
                "last_fitness": float(raw.get("fitness") or 0.0),
                "updated_at_s": time.time(),
            }
        )
        records[version] = existing
    payload = {
        "schema_version": 1,
        "policies": records,
        "last_run": trace.summary(),
        "promotion_rule": {"minimum_valid_candidates": 20, "fixed_benchmark_required": True},
        "champion_version": str(current.get("champion_version") or ""),
        "previous_champion_version": str(current.get("previous_champion_version") or ""),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return


def apply_fixed_benchmark_result(*, strategy_version: str, metrics: dict, cost_over_limit: bool = False) -> dict:
    """Apply promotion/rollback gates to the durable policy registry."""

    path = strategy_store_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        payload = {}
    records = payload.get("policies") if isinstance(payload.get("policies"), dict) else {}
    version = str(strategy_version or "").strip()
    record = dict(records.get(version) or {"version": version, "status": "shadow", "valid_candidates": 0})
    fatal_recall = float((metrics or {}).get("fatal_defect_recall") or 0.0)
    false_allow = float((metrics or {}).get("false_allow_rate") or 1.0)
    ranking_accuracy = float((metrics or {}).get("ranking_accuracy") or 0.0)
    unsupported_fitness_labels = int((metrics or {}).get("unsupported_fitness_labels") or 0)
    hard_gate_regressed = bool((metrics or {}).get("hard_gate_regressed"))
    passed = (
        fatal_recall >= 0.95
        and false_allow <= 0.02
        and ranking_accuracy >= 0.85
        and unsupported_fitness_labels == 0
        and not cost_over_limit
        and not hard_gate_regressed
    )
    record["benchmark_passed"] = passed
    record["benchmark_metrics"] = dict(metrics or {})
    record["updated_at_s"] = time.time()
    current_status = str(record.get("status") or "shadow")
    champion_version = str(payload.get("champion_version") or "").strip()
    previous_champion = str(payload.get("previous_champion_version") or "").strip()
    if passed and int(record.get("valid_candidates") or 0) >= 20 and current_status in {"shadow", "candidate"}:
        if champion_version and champion_version != version and champion_version in records:
            prior = dict(records[champion_version] or {})
            prior["status"] = "retired"
            records[champion_version] = prior
            payload["previous_champion_version"] = champion_version
        record["status"] = "champion"
        payload["champion_version"] = version
    elif current_status == "champion" and not passed:
        record["status"] = "retired"
        if previous_champion and previous_champion in records:
            rollback = dict(records[previous_champion] or {})
            rollback["status"] = "champion"
            rollback["rollback_reason"] = (
                "cost_over_limit" if cost_over_limit else "hard_gate_or_supervision_regression"
            )
            records[previous_champion] = rollback
            payload["champion_version"] = previous_champion
    records[version] = record
    payload.update({"schema_version": 1, "policies": records})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
    return {
        "strategy_version": version,
        "benchmark_passed": passed,
        "status": str(record.get("status") or ""),
        "champion_version": str(payload.get("champion_version") or ""),
    }


def policy_payload(policy: PolicyIndividual) -> dict:
    return asdict(policy)
