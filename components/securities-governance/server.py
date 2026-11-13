"""Authenticated single-workspace API and WorkBuddy MCP adapter."""

from contextlib import asynccontextmanager
import hashlib
import hmac
import os
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field, StringConstraints, ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route

from evaluate import compare, evaluate
from materials import extract_material
from schemas import BoundText, Citation, Dataset, Key, Record, Reference, Run
from tasks import TaskConflict, TaskStore, encode

MAX_REQUEST = 2 * 1024 * 1024
# Bump when the scoring rules change so stored runs remain comparable.
SCORING_VERSION = "1"
WEB = Path(__file__).with_name("web")
SKILL = Path(__file__).with_name("connector") / "skills" / "securities-governance" / "SKILL.md"
WEB_ASSETS = {
    "/workbench": (WEB / "index.html", "text/html"),
    "/workbench/app.js": (WEB / "app.js", "text/javascript"),
    "/workbench/styles.css": (WEB / "styles.css", "text/css"),
    "/workbench/SKILL.md": (SKILL, "text/markdown"),
}
PRIVATE_RESPONSE = {"Cache-Control": "no-store"}


class Material(Record):
    path: Annotated[str, StringConstraints(max_length=512)]
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class Registry(Record):
    materials: dict[Key, Material] = Field(max_length=100)
    rule_sources: dict[BoundText, list[Citation]] = Field(default_factory=dict, max_length=250)


class Comparison(Record):
    before: Run
    after: Run


class NewTask(Record):
    task_id: Key
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    run: Run


def create_app(root: Path, token: str, task_path: Path | None = None):
    if len(token) < 32 or not token.isascii():
        raise ValueError("Set GOVERNANCE_TOKEN to an ASCII secret of at least 32 characters.")
    root = root.resolve(strict=True)
    registry = Registry.model_validate_json((root / "materials.json").read_bytes())
    dataset = Dataset.model_validate_json((root / "dataset.json").read_bytes())
    sources = {key: extract_material(root, spec) for key, spec in registry.materials.items()}
    material_hashes = {key: material.sha256 for key, material in registry.materials.items()}
    registry_hash = hashlib.sha256(encode(registry.model_dump()).encode("utf-8")).hexdigest()
    for references in registry.rule_sources.values():
        for citation in references:
            if citation.location not in sources.get(citation.asset_id, {}):
                raise ValueError(f"Rule source {citation.asset_id}/{citation.location} is missing.")
    for case in dataset.cases:
        if case.answer:
            for citation in case.answer.citations:
                if citation.location not in sources.get(citation.asset_id, {}):
                    raise ValueError(f"Case {case.id} refers to missing evidence.")

    mcp = FastMCP("Securities Governance Evaluation", stateless_http=True, json_response=True)

    @mcp.tool()
    def read_material(asset_id: Key, location: Reference = "",
                      offset: Annotated[int, Field(ge=0)] = 0) -> dict[str, Any]:
        """List a registered asset's source locations or read one passage with its SHA-256."""
        if asset_id not in sources:
            raise ValueError("Unknown material ID.")
        passages = sources[asset_id]
        result = {"asset_id": asset_id, "sha256": registry.materials[asset_id].sha256}
        if location:
            if location not in passages:
                raise ValueError("Unknown source location.")
            passage = passages[location]
            return {**result, "location": location, "text": passage[:16000],
                    "truncated": len(passage) > 16000}
        return {**result, "locations": list(passages)[offset:offset + 200],
                "offset": offset, "location_count": len(passages)}

    @mcp.tool()
    def list_cases() -> dict[str, Any]:
        """List the registered dataset version and prompts for the test environment."""
        return {"id": dataset.id, "version": dataset.version, "cases": [
            {"id": case.id, "scenario": case.scenario, "rule": case.rule,
             "kind": "qa" if case.answer is not None else "execution"} for case in dataset.cases
        ]}

    @mcp.tool()
    def evaluate_run(run: Run) -> dict[str, Any]:
        """Score submitted answers and trusted test-run observations against the registered dataset."""
        return evaluate(dataset, run)

    @mcp.tool()
    def compare_runs(before: Run, after: Run) -> dict[str, Any]:
        """Compare versions using the same dataset and evaluation conditions."""
        return compare(dataset, before, after)

    def score_task(run):
        report = evaluate_run(run)
        report["scoring_version"] = SCORING_VERSION
        report["material_registry_sha256"] = registry_hash
        report["material_hashes"] = material_hashes
        for case, result in zip(dataset.cases, report["cases"]):
            result["scenario"] = case.scenario
            result["rule_sources"] = [ref.model_dump() for ref in registry.rule_sources.get(case.rule, [])]
            if case.answer is not None:
                result["expected_answer"] = case.answer.model_dump()
            else:
                result["expected_execution"] = {
                    "ordered_actions": [action.model_dump() for action in case.ordered_actions],
                    "allowed_actions": [action.model_dump() for action in case.allowed_actions],
                    "final_state": case.state,
                }
        return report

    task_store = TaskStore(task_path, score_task) if task_path is not None else None

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp.session_manager.run():
            yield

    async def read_route(request: Request):
        try:
            offset = int(request.query_params.get("offset", "0"))
            if offset < 0:
                raise ValueError
        except ValueError:
            return JSONResponse({"error": "invalid_offset"}, status_code=422)
        try:
            return JSONResponse(read_material(request.path_params["asset_id"],
                                              request.query_params.get("location", ""), offset))
        except ValueError:
            return JSONResponse({"error": "material_or_location_not_found"}, status_code=404)

    async def materials_route(_request: Request):
        return JSONResponse({"materials": [
            {"asset_id": key, "sha256": material_hashes[key], "location_count": len(passages)}
            for key, passages in sources.items()
        ]}, headers=PRIVATE_RESPONSE)

    async def cases_route(_request: Request):
        return JSONResponse(list_cases())

    async def evaluation_route(request: Request):
        try:
            content = await request.body()
            if request.url.path == "/v1/evaluations":
                result = await run_in_threadpool(evaluate_run, Run.model_validate_json(content))
            else:
                data = Comparison.model_validate_json(content)
                result = await run_in_threadpool(compare_runs, data.before, data.after)
        except (ValidationError, ValueError):
            return JSONResponse({"error": "invalid_evaluation_input"}, status_code=422)
        return JSONResponse(result)

    def task_evidence(task_id: str, version: str, asset_id: str, location: str):
        report = task_store.report(task_id, version)["report"]
        for case in report["cases"]:
            citations = case["expected_citations"] + case["rule_sources"]
            citations += ((case["evidence"] or {}).get("answer") or {}).get("citations", [])
            if any(ref["asset_id"] == asset_id and ref["location"] == location for ref in citations):
                original_hash = report["material_hashes"].get(asset_id)
                if original_hash is None:
                    raise KeyError("material_or_location_not_found")
                if material_hashes.get(asset_id) != original_hash:
                    raise TaskConflict("material_snapshot_changed")
                try:
                    return read_material(asset_id, location)
                except ValueError as exc:
                    raise KeyError("material_or_location_not_found") from exc
        raise KeyError("material_or_location_not_found")

    async def task_route(request: Request):
        if task_store is None:
            return JSONResponse({"error": "task_storage_disabled"}, status_code=503)
        params = request.path_params
        task_id = params.get("task_id")
        version = params.get("version")
        query = request.query_params
        try:
            if request.method == "POST":
                content = await request.body()
                if task_id is None:
                    task = NewTask.model_validate_json(content)
                    result, created = await run_in_threadpool(task_store.submit, task.task_id, task.run, task.title)
                else:
                    result, created = await run_in_threadpool(task_store.submit, task_id, Run.model_validate_json(content))
                return JSONResponse(result, status_code=201 if created else 200, headers=PRIVATE_RESPONSE)
            if task_id is None:
                offset = int(query.get("offset", "0"))
                if not 0 <= offset <= 2**31 - 1:
                    raise ValueError("invalid_offset")
                result = await run_in_threadpool(task_store.list_tasks, offset)
            elif "asset_id" in params:
                result = await run_in_threadpool(task_evidence, task_id, version, params["asset_id"],
                                                 query.get("location", ""))
            elif version is not None:
                result = await run_in_threadpool(task_store.report, task_id, version)
            elif request.url.path == request.url_for("task_comparison", task_id=task_id).path:
                if not query.get("before") or not query.get("after"):
                    raise ValueError("comparison_requires_two_versions")
                result = await run_in_threadpool(task_store.comparison, task_id, query["before"], query["after"])
            else:
                result = await run_in_threadpool(task_store.detail, task_id)
        except TaskConflict as exc:
            return JSONResponse({"error": str(exc)}, status_code=409)
        except KeyError as exc:
            return JSONResponse({"error": exc.args[0]}, status_code=404)
        except ValidationError as exc:
            return JSONResponse({
                "error": "invalid_task_input",
                "details": exc.errors(include_input=False, include_context=False, include_url=False),
            }, status_code=422)
        except ValueError:
            return JSONResponse({"error": "invalid_task_input"}, status_code=422)
        return JSONResponse(result, headers=PRIVATE_RESPONSE)

    async def web_route(request: Request):
        path, content_type = WEB_ASSETS[request.url.path]
        return FileResponse(path, media_type=content_type, headers={
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; "
                                       "connect-src 'self'; form-action 'none'; frame-ancestors 'none'; "
                                       "base-uri 'none'",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        })

    app = Starlette(lifespan=lifespan, routes=[
        Route("/v1/materials", materials_route),
        Route("/v1/materials/{asset_id}", read_route),
        Route("/v1/cases", cases_route),
        Route("/v1/evaluations", evaluation_route, methods=["POST"]),
        Route("/v1/comparisons", evaluation_route, methods=["POST"]),
        Route("/v1/tasks", task_route, methods=["GET", "POST"]),
        Route("/v1/tasks/{task_id}", task_route),
        Route("/v1/tasks/{task_id}/runs", task_route, methods=["POST"]),
        Route("/v1/tasks/{task_id}/runs/{version}", task_route),
        Route("/v1/tasks/{task_id}/runs/{version}/evidence/{asset_id}", task_route),
        Route("/v1/tasks/{task_id}/comparison", task_route, name="task_comparison"),
        *(Route(path, web_route) for path in WEB_ASSETS),
        Mount("/", mcp.streamable_http_app()),
    ])
    expected = ("Bearer " + token).encode("ascii")

    async def authenticated(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        if scope["method"] in ("GET", "HEAD") and scope["path"] in WEB_ASSETS:
            await app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        if not hmac.compare_digest(headers.get(b"authorization", b""), expected):
            response = JSONResponse({"error": "unauthorized"}, status_code=401,
                                    headers={"WWW-Authenticate": "Bearer"})
            await response(scope, receive, send)
            return
        if scope["method"] == "POST":
            content = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                content.extend(message.get("body", b""))
                if len(content) > MAX_REQUEST:
                    await JSONResponse({"error": "request_too_large"}, status_code=413)(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break

            replayed = False

            async def replay():
                nonlocal replayed
                if replayed:
                    return await receive()
                replayed = True
                return {"type": "http.request", "body": bytes(content), "more_body": False}

            await app(scope, replay, send)
        else:
            await app(scope, receive, send)

    return authenticated


def app_from_env():
    root = Path(os.environ["GOVERNANCE_DATA_DIR"])
    task_path = os.environ.get("GOVERNANCE_TASK_DB")
    return create_app(root, os.environ["GOVERNANCE_TOKEN"],
                      Path(task_path).resolve() if task_path else None)
