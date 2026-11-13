import hashlib
import json

from schemas import Run


def check_answer(expected, actual):
    reasons = []
    if actual.decision != expected.decision:
        reasons.append("wrong_decision")
    if actual.values.keys() != expected.values.keys() or any(
        type(actual.values.get(key)) is not type(value) or actual.values.get(key) != value
        for key, value in expected.values.items()
    ):
        reasons.append("wrong_values")
    actual_citations = {(item.asset_id, item.location) for item in actual.citations}
    expected_citations = {(item.asset_id, item.location) for item in expected.citations}
    if actual_citations != expected_citations:
        reasons.append("wrong_citations")
    return reasons


def check_execution(case, execution):
    reasons = []
    if json.dumps(execution.final_state, sort_keys=True) != json.dumps(case.state, sort_keys=True):
        reasons.append("wrong_final_state")
    allowed = case.ordered_actions + case.allowed_actions
    if any(action not in allowed for action in execution.events):
        reasons.append("unexpected_action")
    mandatory = [action for action in execution.events if action in case.ordered_actions]
    if mandatory != case.ordered_actions:
        reasons.append("wrong_action_order_or_count")
    return reasons


def evaluate(dataset, run: Run):
    if (run.dataset_id, run.dataset_version) != (dataset.id, dataset.version):
        raise ValueError("Run does not name this frozen dataset version.")
    observations = {item.case_id: item for item in run.observations}
    if len(observations) != len(run.observations) or observations.keys() - {case.id for case in dataset.cases}:
        raise ValueError("Run contains duplicate or unknown case IDs.")
    rows = []
    for case in dataset.cases:
        observation = observations.get(case.id)
        if observation is None:
            status, reasons = "unverified", ["missing_observation"]
        elif observation.infrastructure_error:
            status, reasons = "infrastructure_error", [observation.infrastructure_error]
        elif case.answer is not None and observation.answer is not None:
            reasons = check_answer(case.answer, observation.answer)
            status = "fail" if reasons else "pass"
        elif case.state is not None and observation.execution is not None:
            reasons = check_execution(case, observation.execution)
            status = "fail" if reasons else "pass"
        else:
            status, reasons = "unverified", ["wrong_evidence_type"]
        rows.append({
            "id": case.id, "kind": "qa" if case.answer is not None else "execution",
            "rule": case.rule, "critical": case.critical, "status": status, "reasons": reasons,
            "remediation": case.remediation if status == "fail" else None,
            "expected_citations": [item.model_dump() for item in case.answer.citations] if case.answer else [],
            "evidence": observation.model_dump(exclude_none=True) if observation else None,
        })
    counts = {state: sum(row["status"] == state for row in rows)
              for state in ("pass", "fail", "unverified", "infrastructure_error")}
    scored = counts["pass"] + counts["fail"]
    if any(row["critical"] and row["status"] == "fail" for row in rows):
        decision = "blocked"
    elif scored != len(rows):
        decision = "incomplete"
    else:
        decision = "completed"
    return {
        "dataset_id": dataset.id, "dataset_version": dataset.version,
        "dataset_sha256": hashlib.sha256(dataset.model_dump_json().encode()).hexdigest(),
        "conditions_id": run.conditions_id, "subject_version": run.subject_version,
        "status": decision, "counts": counts, "scored": scored, "total": len(rows),
        "pass_rate": counts["pass"] / scored if scored else None, "cases": rows,
    }


def compare(dataset, before: Run, after: Run):
    if before.conditions_id != after.conditions_id:
        raise ValueError("Comparison requires the same frozen evaluation conditions.")
    previous, current = evaluate(dataset, before), evaluate(dataset, after)
    return {
        "before": previous, "after": current,
        "changes": [
            {"id": old["id"], "before": old["status"], "after": new["status"]}
            for old, new in zip(previous["cases"], current["cases"]) if old["status"] != new["status"]
        ],
    }
