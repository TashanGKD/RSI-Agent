import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import httpx
from docx import Document
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from materials import extract_material
from server import Material

EXAMPLES = Path(__file__).with_name("examples")
DATA = json.loads((EXAMPLES / "dataset.json").read_text(encoding="utf-8"))
TOKEN = "x" * 32
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def sample_run():
    results = []
    for case in DATA["cases"]:
        observation = {"case_id": case["id"]}
        if "answer" in case:
            observation["answer"] = case["answer"]
        else:
            observation["execution"] = {"events": case["ordered_actions"], "final_state": case["state"]}
        results.append(observation)
    return {"dataset_id": DATA["id"], "dataset_version": DATA["version"], "subject_version": "v1",
            "conditions_id": "fixture", "observations": deepcopy(results)}


class DocumentTests(unittest.TestCase):
    def test_office_extraction_and_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            doc = Document()
            doc.add_paragraph("公告原文")
            doc.save(root / "notice.docx")
            book = Workbook()
            book.active["A1"] = 24.8
            book.save(root / "notice.xlsx")
            for name, expected in [("notice.docx", {"paragraph:1": "公告原文"}),
                                   ("notice.xlsx", {"cell:Sheet!A1": "24.8"})]:
                digest = hashlib.sha256((root / name).read_bytes()).hexdigest()
                self.assertEqual(extract_material(root, Material(path=name, sha256=digest)), expected)
                with self.assertRaisesRegex(ValueError, "digest"):
                    extract_material(root, Material(path=name, sha256="0" * 64))

    def test_pdf_without_text_requires_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "scan.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=72, height=72)
            writer.write(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "No extractable text"):
                extract_material(root, Material(path=path.name, sha256=digest))

    def test_pdf_text_uses_page_locator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "text.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(width=200, height=100)
            name = NameObject
            font = DictionaryObject({
                name("/Type"): name("/Font"), name("/Subtype"): name("/Type1"),
                name("/BaseFont"): name("/Helvetica"),
            })
            page[name("/Resources")] = DictionaryObject({
                name("/Font"): DictionaryObject({name("/F1"): font}),
            })
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 10 50 Td (Revenue: 24.8) Tj ET")
            page.replace_contents(stream)
            writer.write(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(extract_material(root, Material(path=path.name, sha256=digest)),
                             {"page:1": "Revenue: 24.8"})


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os

        task_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(task_dir.cleanup)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{port}"
        cls.server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server:app_from_env", "--factory",
             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning", "--no-access-log"],
            env={**os.environ, "GOVERNANCE_DATA_DIR": str(EXAMPLES), "GOVERNANCE_TOKEN": TOKEN,
                 "GOVERNANCE_TASK_DB": str(Path(task_dir.name) / "tasks.sqlite3")},
        )
        cls.addClassCleanup(cls.server.wait, timeout=10)
        cls.addClassCleanup(cls.server.terminate)
        for _ in range(60):
            try:
                if httpx.get(f"{cls.base}/v1/cases", headers=HEADERS, timeout=0.5).status_code == 200:
                    return
            except httpx.RequestError:
                pass
            if cls.server.poll() is not None:
                break
            time.sleep(0.1)
        raise RuntimeError("Evaluation service failed to start.")

    def test_http_auth_material_and_evaluation(self):
        with httpx.Client(base_url=self.base) as client:
            self.assertEqual(client.get("/v1/cases").status_code, 401)
            self.assertEqual(client.get("/mcp").status_code, 401)
            receipt = client.get("/v1/materials/synthetic-notice", params={"location": "line:2"},
                                 headers=HEADERS).json()
            self.assertIn("24.8", receipt["text"])
            run = sample_run()
            good = client.post("/v1/evaluations", json=run, headers=HEADERS).json()
            self.assertEqual((good["status"], good["scored"], good["pass_rate"]), ("completed", 8, 1))
            run["observations"][3]["execution"]["events"].reverse()
            run["observations"][4]["execution"]["events"].append({"operation": "write", "target": "revenue"})
            run["observations"].pop()
            run["observations"][-1] = {"case_id": "upstream-unavailable", "infrastructure_error": "timeout"}
            bad = client.post("/v1/evaluations", json=run, headers=HEADERS).json()
            self.assertEqual(bad["status"], "blocked")
            self.assertEqual(bad["counts"], {"pass": 4, "fail": 2, "unverified": 1, "infrastructure_error": 1})
            self.assertIn("wrong_action_order_or_count", bad["cases"][3]["reasons"])
            self.assertIn("unexpected_action", bad["cases"][4]["reasons"])
            run["subject_version"] = "v2"
            diff = client.post("/v1/comparisons", json={"before": sample_run(), "after": run},
                               headers=HEADERS).json()
            self.assertEqual(len(diff["changes"]), 4)
            run["dataset_version"] = "wrong"
            self.assertEqual(client.post("/v1/evaluations", json=run, headers=HEADERS).status_code, 422)

    def test_saved_report_evidence_retest_and_idempotent_submission(self):
        baseline = sample_run()
        baseline["observations"][3]["execution"]["events"].reverse()
        new_task = {"task_id": "research-test", "title": "研究助手", "run": baseline}
        task_path = "/v1/tasks/research-test"
        with httpx.Client(base_url=self.base) as client:
            self.assertEqual(client.get("/workbench").status_code, 200)
            self.assertEqual(client.get("/workbench/SKILL.md").status_code, 200)
            self.assertEqual(client.get("/v1/tasks").status_code, 401)
            self.assertEqual(client.get(task_path + "/runs/v1").status_code, 401)
            client.headers.update(HEADERS)
            materials = client.get("/v1/materials")
            self.assertEqual(materials.status_code, 200)
            self.assertEqual(materials.json()["materials"][0]["asset_id"], "synthetic-notice")
            created = client.post("/v1/tasks", json=new_task)
            self.assertEqual(created.status_code, 201, created.text)
            original = created.json()
            self.assertEqual(original["report"]["status"], "blocked")
            self.assertEqual(original["workbench_path"], "/workbench?task=research-test")
            retry = client.post("/v1/tasks", json=new_task)
            self.assertEqual((retry.status_code, retry.json()), (200, original))
            rejected = client.post("/v1/tasks", json={**new_task, "title": "另一项任务"})
            self.assertEqual(rejected.status_code, 409)

            proof = task_path + "/runs/v1/evidence/synthetic-notice"
            rule = client.get(proof, params={"location": "line:7"})
            self.assertEqual(rule.status_code, 200, rule.text)
            self.assertIn("批准事件", rule.json()["text"])
            self.assertEqual(rule.headers["Cache-Control"], "no-store")
            self.assertEqual(client.get(proof, params={"location": "line:1"}).status_code, 404)

            after = {**sample_run(), "subject_version": "v2"}
            wrong_conditions = client.post(task_path + "/runs", json={**after, "conditions_id": "other"})
            self.assertEqual(wrong_conditions.json(), {"error": "evaluation_conditions_changed"})
            self.assertEqual(wrong_conditions.status_code, 409)
            posted = client.post(task_path + "/runs", json=after)
            self.assertEqual(posted.status_code, 201, posted.text)
            self.assertEqual(posted.json()["report"]["counts"]["pass"], 8)
            self.assertEqual(client.post(task_path + "/runs", json=after).status_code, 200)
            self.assertEqual(client.post(task_path + "/runs", json={**after, "observations": []}).status_code, 409)

            comparison = client.get(task_path + "/comparison", params={"before": "v1", "after": "v2"})
            self.assertEqual(comparison.status_code, 200, comparison.text)
            self.assertEqual(comparison.json()["changes"], [
                {"id": "approved-update", "before": "fail", "after": "pass"}
            ])
            self.assertEqual(client.get(task_path + "/runs/v1").json(), original)
            self.assertEqual([item["version"] for item in client.get(task_path).json()["runs"]], ["v1", "v2"])
            self.assertEqual(client.get("/v1/tasks").json()["tasks"][0]["run_count"], 2)

    def test_real_mcp_client(self):
        async def exercise():
            async with httpx.AsyncClient(headers=HEADERS) as http_client:
                async with streamable_http_client(f"{self.base}/mcp", http_client=http_client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        self.assertEqual({tool.name for tool in tools.tools},
                                         {"read_material", "list_cases", "evaluate_run", "compare_runs"})
                        result = await session.call_tool("evaluate_run", {"run": sample_run()})
                        self.assertFalse(result.isError, result.content)
                        self.assertIn("dataset_sha256", json.dumps(result.structuredContent))
                        result = await session.call_tool("read_material", {"asset_id": "synthetic-notice",
                                                                           "location": "line:2"})
                        self.assertFalse(result.isError, result.content)
                        self.assertIn("24.8", json.dumps(result.structuredContent))
        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
