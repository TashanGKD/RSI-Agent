"""Authenticated single-workspace API and WorkBuddy MCP adapter."""

from contextlib import asynccontextmanager
import hmac
import os
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field, StringConstraints, ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from evaluate import compare, evaluate
from materials import extract_material
from schemas import Dataset, Key, Record, Reference, Run

MAX_REQUEST = 2 * 1024 * 1024


class Material(Record):
    path: Annotated[str, StringConstraints(max_length=512)]
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class Registry(Record):
    materials: dict[Key, Material] = Field(max_length=100)


class Comparison(Record):
    before: Run
    after: Run


def create_app(root: Path, token: str):
    if len(token) < 32 or not token.isascii():
        raise ValueError("Set GOVERNANCE_TOKEN to an ASCII secret of at least 32 characters.")
    root = root.resolve(strict=True)
    registry = Registry.model_validate_json((root / "materials.json").read_bytes())
    dataset = Dataset.model_validate_json((root / "dataset.json").read_bytes())
    sources = {key: extract_material(root, spec) for key, spec in registry.materials.items()}
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

    app = Starlette(lifespan=lifespan, routes=[
        Route("/v1/materials/{asset_id}", read_route),
        Route("/v1/cases", cases_route),
        Route("/v1/evaluations", evaluation_route, methods=["POST"]),
        Route("/v1/comparisons", evaluation_route, methods=["POST"]),
        Mount("/", mcp.streamable_http_app()),
    ])
    expected = ("Bearer " + token).encode("ascii")

    async def authenticated(scope, receive, send):
        if scope["type"] != "http":
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
    return create_app(Path(os.environ["GOVERNANCE_DATA_DIR"]), os.environ["GOVERNANCE_TOKEN"])
