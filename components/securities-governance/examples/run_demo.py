"""Run a portable HTTP walkthrough using the component's synthetic examples."""

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def observations(dataset):
    for case in dataset["cases"]:
        if "answer" in case:
            yield {"case_id": case["id"], "answer": case["answer"]}
        else:
            yield {"case_id": case["id"], "execution": {
                "events": case["ordered_actions"], "final_state": case["state"],
            }}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("GOVERNANCE_BASE_URL"))
    parser.add_argument("--task-id", default=f"securities-demo-{uuid4().hex[:10]}")
    args = parser.parse_args()
    token = os.environ.get("GOVERNANCE_TOKEN")
    if not args.base_url or not token:
        parser.error("Set GOVERNANCE_BASE_URL and GOVERNANCE_TOKEN.")
    opener = build_opener(NoRedirect())

    def request(path, body=None):
        headers = {"Authorization": f"Bearer {token}"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        with opener.open(Request(args.base_url.rstrip("/") + path, data, headers), timeout=10) as response:
            return response.status, json.load(response)

    _, manifest = request("/v1/cases")
    dataset = json.loads(Path(__file__).with_name("dataset.json").read_text(encoding="utf-8"))
    if (dataset["id"], dataset["version"]) != (manifest["id"], manifest["version"]):
        parser.error("This walkthrough requires the bundled synthetic dataset.")
    _, materials = request("/v1/materials")
    if "synthetic-notice" not in {item["asset_id"] for item in materials["materials"]}:
        parser.error("The synthetic material is missing from the service.")
    _, source = request("/v1/materials/synthetic-notice?location=line%3A2")
    after = {
        "dataset_id": dataset["id"], "dataset_version": dataset["version"],
        "subject_version": "v0.3", "conditions_id": "synthetic-sandbox-01",
        "observations": list(observations(dataset)),
    }
    before = deepcopy(after)
    before["subject_version"] = "v0.2"
    for row in before["observations"]:
        if row["case_id"] == "approved-update":
            row["execution"]["events"].reverse()
        elif row["case_id"] == "corrected-filing":
            row["answer"]["values"]["revenue"] = 25.1
            row["answer"]["citations"][0]["location"] = "line:3"
    before["observations"] = [row for row in before["observations"] if row["case_id"] != "read-only-role"]

    new_task = {"task_id": args.task_id, "title": "证券研究资料助手", "run": before}
    _, baseline = request("/v1/tasks", new_task)
    task = "/v1/tasks/" + baseline["task_id"]
    _, retest = request(task + "/runs", after)
    retry_code, retry = request(task + "/runs", after)
    if retry_code != 200 or retest != retry:
        raise RuntimeError("The retry did not return the original retest.")
    _, metadata = request(task)
    _, persisted = request(task + "/runs/v0.2")
    _, passage = request(task + "/runs/v0.2/evidence/synthetic-notice?location=line%3A7")
    _, diff = request(task + "/comparison?" + urlencode({"before": "v0.2", "after": "v0.3"}))
    print(json.dumps({
        "task": metadata, "workbench_url": args.base_url.rstrip("/") + baseline["workbench_path"],
        "source": source["text"], "rule_evidence": passage["text"],
        "baseline": persisted["report"]["counts"], "retest": retest["report"]["counts"],
        "changes": diff["changes"], "identical_retry_status": retry_code,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
