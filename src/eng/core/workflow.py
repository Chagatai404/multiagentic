"""Deterministic workflow decisions; no execution or external state.

Classification inspects at most 16,000 description characters and the first 100
context paths (512 characters each). It uses explicit word/path cues, not model
judgement. Complexity and risk are independent; overrides can increase either
axis, but cannot remove inferred safeguards. Acceptance text is not executable
policy and is deliberately excluded.
"""

import hashlib
import json
import re

from eng.core.models import (
    Classification,
    Complexity,
    Risk,
    Task,
    TaskSpec,
    TaskType,
    VerificationResult,
    WorkflowDecision,
    WorkflowPolicy,
)
from eng.core.policy import completion_gate


def classify_task(spec: TaskSpec) -> Classification:
    description = spec.description[:16000].casefold()
    paths = " ".join(path[:512].replace("\\", "/").casefold() for path in spec.context_paths[:100])
    text = description + " " + paths
    reasons = ["Default bounded change: small complexity, low risk"]
    question = re.match(r"\s*(how|why|what|where|when|explain|describe)\b", description)
    task_type = TaskType.QUESTION if question else TaskType.CHANGE
    complexity = Complexity.SMALL
    risk = Risk.LOW
    if re.search(
        r"\b(architecture|architectural|redesign|multi[- ](?:module|service|agent)|"
        r"distributed|cross[- ]cutting|end[- ]to[- ]end|complex)\b",
        text,
    ):
        complexity = Complexity.COMPLEX
        reasons.append("Complex architecture or cross-component scope cue")
    elif len(spec.context_paths) >= 5 or re.search(
        r"\b(refactor|integration|adapter|subsystem|migration)\b", text
    ):
        complexity = Complexity.MEDIUM
        reasons.append("Multiple paths or integration/refactor scope cue")
    if re.search(
        r"\b(auth(?:entication|orization)?|credentials?|secrets?|permissions?|"
        r"payments?|billing|production|deploy(?:ment)?|destructive|security|"
        r"cryptograph\w*|encryption|drop\s+table|delete\s+(?:all|data))\b",
        text,
    ):
        risk = Risk.HIGH
        reasons.append("Security, sensitive data, deployment or destructive operation cue")
    elif re.search(
        r"\b(database|schema|migration|storage|persistence|concurrency|locking|"
        r"public\s+api|dependencies|dependency)\b|(?:^|[\s/])(?:package-lock\.json|uv\.lock)\b",
        text,
    ):
        risk = Risk.MEDIUM
        reasons.append("Persistence, concurrency, API or dependency compatibility cue")
    overrides = spec.classification_overrides
    if overrides.task_type is not None:
        task_type = overrides.task_type
        reasons.append("Explicit task type override; inferred risk retained")
    complexities = list(Complexity)
    risks = list(Risk)
    if overrides.complexity is not None:
        complexity = complexities[
            max(complexities.index(complexity), complexities.index(overrides.complexity))
        ]
        reasons.append("Complexity override applied without reducing inferred scope")
    if overrides.risk is not None:
        risk = risks[max(risks.index(risk), risks.index(overrides.risk))]
        reasons.append("Risk override applied without reducing inferred safeguards")
    return Classification(task_type=task_type, complexity=complexity, risk=risk, reasons=reasons)


def select_workflow(classification: Classification, policy: WorkflowPolicy) -> WorkflowDecision:
    # Question routing is handled before execution. Retain risk safeguards in the
    # decision so changing the task type cannot erase a sensitive change's risk.
    return WorkflowDecision(
        planner=classification.complexity == Complexity.COMPLEX,
        reviewer=(
            classification.complexity == Complexity.COMPLEX or classification.risk != Risk.LOW
        ),
        approval_required=classification.risk == Risk.HIGH,
        max_repairs=policy.max_repairs,
    )


def escalate_classification(current: Classification, observed: Classification) -> Classification:
    """Raise safeguards from observed scope while preserving the user's task type."""
    complexities = list(Complexity)
    risks = list(Risk)
    return Classification(
        task_type=current.task_type,
        complexity=complexities[
            max(complexities.index(current.complexity), complexities.index(observed.complexity))
        ],
        risk=risks[max(risks.index(current.risk), risks.index(observed.risk))],
        reasons=list(dict.fromkeys([*current.reasons, *observed.reasons])),
    )


def failure_signature(results: list[VerificationResult]) -> str:
    """Hash actual failed required checks, excluding transient artifact/timing data.

    An empty signature means repair is not actionable: absent checks, no failures,
    or any required unavailable/unconfirmed/error/skipped result. Evidence comes
    from normalized result fields, never artifact reads in this pure layer.
    """
    required = [result for result in results if result.required]
    if any(result.outcome not in {"PASS", "FAIL"} for result in required):
        return ""
    failures = [
        {
            "check_id": result.check_id,
            "command": result.command,
            "exit_code": result.exit_code,
            "reason": result.reason,
        }
        for result in required
        if result.outcome == "FAIL"
    ]
    if not failures:
        return ""
    encoded = sorted(json.dumps(item, sort_keys=True, separators=(",", ":")) for item in failures)
    return hashlib.sha256("\n".join(encoded).encode()).hexdigest()


def workflow_completion_gate(task: Task) -> tuple[bool, str]:
    passed, message = completion_gate(task.verification)
    if not passed:
        return passed, message
    if task.classification is None or task.workflow is None:
        return False, "Classification and workflow decision are required"
    if task.classification.task_type == TaskType.QUESTION:
        return False, "Read-only questions require direct use; engineering completion unsupported"
    inferred = select_workflow(classify_task(task.spec), task.config.workflow)
    classified = select_workflow(task.classification, task.config.workflow)
    decisions = (inferred, classified, task.workflow)
    if any(decision.approval_required for decision in decisions) and not task.spec.human_approved:
        return False, "High-risk work requires explicit human approval"
    if any(decision.planner for decision in decisions) and not task.planning_completed:
        return False, "Required planning has not completed"
    if any(decision.reviewer for decision in decisions):
        if not task.review_passed:
            return False, "Required independent review has not passed"
        if not task.verified_digest or not task.review_digest:
            return False, "Verification and review require nonempty workspace digests"
        if task.verified_digest != task.review_digest:
            return False, "Review does not match the verified workspace"
    return True, message
