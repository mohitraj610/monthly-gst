from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .demo import demo_files
from .imports import FIELDS, MAX_BYTES, inspect_table
from .reports import csv_report, evidence_bundle, workbook
from .store import Conflict, Store

ROOT = Path(__file__).resolve().parents[2]


class WorkspaceInput(BaseModel):
    name: str = Field(max_length=100)
    gstin: str = Field(max_length=15)
    period: str = Field(max_length=7)


class CommitInput(BaseModel):
    coverage_confirmed: bool = False


class ReviewInput(BaseModel):
    actor: str = Field(max_length=80)
    note: str = Field(max_length=2000)


Amount = Annotated[str, Field(max_length=40)]
AmountGrid = dict[str, Annotated[dict[str, Amount], Field(max_length=4)]]


class FilingInput(BaseModel):
    revision: int = Field(ge=0)
    portal: AmountGrid = Field(max_length=9)
    reviewed: AmountGrid = Field(max_length=9)
    notes: dict[str, Annotated[str, Field(max_length=500)]] = Field(max_length=9)
    reviewer: str = Field(max_length=80)
    checks: list[str] = Field(max_length=4)


def create_app(data_dir: Path | None = None, *, test_mode=False):
    store = Store((data_dir or Path(os.getenv("MONTHLY_GST_DATA", str(ROOT / ".local")))) / "workspace.sqlite")
    app = FastAPI(title="Monthly GST", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store
    token = secrets.token_urlsafe(32)

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        allowed = {"127.0.0.1", "localhost"} | ({"testserver"} if test_mode else set())
        if request.url.hostname not in allowed:
            return Response("Local connections only", status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            return Response("Cross-origin request blocked", status_code=403)
        if request.url.path.startswith("/api/") and request.url.path not in {"/api/bootstrap", "/api/health"}:
            if not secrets.compare_digest(request.headers.get("x-session", ""), token):
                return Response("Session expired. Reload the application.", status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(ValueError)
    async def bad_input(request, exc):
        return Response(json.dumps({"detail": str(exc)}), media_type="application/json", status_code=409 if isinstance(exc, Conflict) else 422)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return Response(json.dumps({"detail": str(exc)}), media_type="application/json", status_code=404)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "scope": "filing-preparation"}

    @app.get("/api/bootstrap")
    def bootstrap():
        return {"token": token, "version": __version__, "fields": list(FIELDS)}

    @app.get("/api/workspaces")
    def workspaces():
        return store.list_workspaces()

    @app.post("/api/workspaces")
    def create_workspace(body: WorkspaceInput):
        return store.create_workspace(body.name, body.gstin, body.period)

    @app.get("/api/workspaces/{wid}")
    def workspace(wid: str):
        return store.workspace(wid) | {"sources": store.sources(wid), "history": store.history(wid)}

    @app.post("/api/inspect")
    async def inspect(file: UploadFile = File(), sheet: str = Form(""), header_row: int = Form(1)):
        content = await file.read(MAX_BYTES+1)
        table = inspect_table(content, file.filename or "", sheet or None, header_row)
        return {k: table[k] for k in ("headers", "sheets", "sheet", "mapping", "header_row", "input_rows")} | {"sample": table["rows"][:5]}

    @app.post("/api/workspaces/{wid}/imports/preview")
    async def preview(wid: str, file: UploadFile = File(), role: str = Form(), options: str = Form("{}")):
        content = await file.read(MAX_BYTES+1)
        try:
            opts = json.loads(options)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid mapping options") from exc
        if not isinstance(opts, dict):
            raise ValueError("Mapping options must be an object")
        return store.preview(wid, role, file.filename or "source", content, opts)

    @app.post("/api/workspaces/{wid}/imports/{sid}/commit")
    def commit(wid: str, sid: str, body: CommitInput):
        return store.commit(wid, sid, body.coverage_confirmed)

    @app.post("/api/workspaces/{wid}/reconcile")
    def run(wid: str):
        result = store.run(wid)
        return {k: v for k, v in result.items() if k != "rows"}

    @app.post("/api/workspaces/{wid}/imports/{sid}/exclude")
    def exclude(wid: str, sid: str):
        return store.exclude(wid, sid)

    @app.get("/api/runs/{rid}")
    def results(rid: str, offset: int = 0, limit: int = 100, status: str = "all", q: str = ""):
        result = store.get_run(rid)
        rows = result.pop("rows")
        if status == "attention":
            rows = [r for r in rows if r.get("needs_attention", r["status"] != "exact")]
        elif status != "all":
            rows = [r for r in rows if r["status"] == status]
        if q:
            query = q.casefold()[:200]
            rows = [r for r in rows if any(query in f"{d['supplier_gstin']} {d['number']} {d['source_name']}".casefold() for side in ("books", "portal") for d in r[side])]
        result["filtered_count"] = len(rows)
        result["row_count"] = sum(result["counts"].values())
        result["rows"] = rows[max(0, offset):max(0, offset)+min(200, max(1, limit))]
        return result

    @app.post("/api/runs/{rid}/rows/{row_id}/review")
    def review(rid: str, row_id: str, body: ReviewInput):
        store.review(rid, row_id, body.actor, body.note)
        return {"saved": True}

    @app.get("/api/runs/{rid}/download/{kind}")
    def download(rid: str, kind: str):
        result = store.get_run(rid)
        if kind == "xlsx":
            content, mime, ext = workbook(result), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
        elif kind == "csv":
            content, mime, ext = csv_report(result), "text/csv", "csv"
        elif kind == "zip":
            content, mime, ext = evidence_bundle(result, store.export_sources(result["source_ids"])), "application/zip", "zip"
        else:
            raise ValueError("Choose xlsx, csv or zip")
        return Response(content, media_type=mime, headers={"Content-Disposition": f'attachment; filename="Monthly-GST-{result["workspace"]["period"]}-diagnostic.{ext}"'})

    @app.get("/api/runs/{rid}/filing")
    def get_filing(rid: str):
        return store.filing_review(rid)

    @app.put("/api/runs/{rid}/filing")
    def save_filing(rid: str, body: FilingInput):
        return store.save_filing_review(rid, body.revision, body.model_dump(exclude={"revision"}))

    @app.get("/api/runs/{rid}/filing/download")
    def download_filing(rid: str, revision: int | None = None):
        filing = store.filing_review(rid)
        if not filing["revision"]:
            raise Conflict("Save the filing worksheet before exporting it")
        if revision is not None and revision != filing["revision"]:
            raise Conflict("The saved worksheet changed. Reopen it before exporting.")
        result = store.get_run(rid)
        content = evidence_bundle(result, store.export_sources(result["source_ids"]), filing=filing)
        filename = f'Monthly-GST-{result["workspace"]["period"]}-filing-review.zip'
        return Response(content, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.get("/api/demo/files/{kind}")
    def sample_file(kind: str):
        _, books, portal = demo_files()
        if kind not in {"books", "portal"}:
            raise ValueError("Unknown demo file")
        ext = "csv" if kind == "books" else "json"
        return Response(books if kind == "books" else portal, media_type="text/csv" if kind == "books" else "application/json",
                        headers={"Content-Disposition": f'attachment; filename="synthetic-{kind}.{ext}"'})

    @app.post("/api/demo")
    def demo():
        gstin, books, portal = demo_files()
        w = store.create_workspace("Demo · fictional business", gstin, "2026-10")
        for role, name, content in (("books", "synthetic-purchases.csv", books), ("portal", "synthetic-2b.json", portal)):
            src = store.preview(w["id"], role, name, content, {})
            store.commit(w["id"], src["id"], True)
        result = store.run(w["id"])
        return {"workspace": w, "run_id": result["id"]}

    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:
        @app.get("/")
        def missing_build():
            return Response("Build the interface: npm --prefix frontend install && npm --prefix frontend run build", media_type="text/plain")
    return app
