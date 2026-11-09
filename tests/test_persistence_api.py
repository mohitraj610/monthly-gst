import hashlib
import io
import json
import time
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from monthly_gst.api import create_app
from monthly_gst.reports import evidence_bundle, workbook, csv_report
from monthly_gst.store import Conflict
from conftest import changed_books


def test_idempotent_import_and_restart(loaded, files):
    store, w = loaded
    sources = store.sources(w["id"])
    preview = store.preview(w["id"], "books", "renamed.csv", files[1], {})
    assert preview["already_imported"]
    store.commit(w["id"], preview["id"], True)
    assert len(store.sources(w["id"])) == len(sources) == 2
    run = store.run(w["id"])
    restarted = type(store)(store.path)
    assert restarted.get_run(run["id"])["rows"] == run["rows"]
    with store.connect() as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_confirm_required_and_cross_workspace_commit_blocked(loaded, files):
    store, w = loaded
    w2 = store.create_workspace("Second", files[0], "2026-10")
    src = store.sources(w["id"])[0]
    with pytest.raises(ValueError, match="Confirm"):
        store.commit(w["id"], src["id"], False)
    with pytest.raises(KeyError):
        store.commit(w2["id"], src["id"], True)


def test_replacement_stales_old_run_but_preserves_originals_and_reviews(loaded, files):
    store, w = loaded
    old = store.run(w["id"])
    row = old["rows"][0]
    store.review(old["id"], row["id"], "Tester", "Compared with original invoice")
    store.review(old["id"], row["id"], "Tester", "Second independent inspection")
    assert len(store.get_run(old["id"])["review_events"]) == 2
    root = json.loads(files[2])
    root["docdata"]["b2b"][0]["inv"][0]["val"] = "1181"
    src = store.preview(w["id"], "portal", "corrected.json", json.dumps(root).encode(), {})
    store.commit(w["id"], src["id"], True)
    assert len(store.sources(w["id"])) == 2
    saved = store.get_run(old["id"])
    assert saved["stale"]
    assert saved["totals"] == old["totals"]
    assert len(store.export_sources(old["source_ids"])) == 2
    assert any(data == files[2] for meta, data in store.export_sources(old["source_ids"]))
    with pytest.raises(Conflict):
        store.review(old["id"], row["id"], "Tester", "No review on obsolete inputs")
    assert not store.run(w["id"])["stale"]


def test_failed_parse_leaves_no_partial_evidence(loaded):
    store, w = loaded
    with store.connect() as db:
        before = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    with pytest.raises(ValueError):
        store.preview(w["id"], "portal", "bad.json", b"{}", {})
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM files").fetchone()[0] == before


def test_exclusion_is_reversible_and_preserves_old_evidence(loaded, files):
    store, w = loaded
    old = store.run(w["id"])
    src = next(s for s in store.sources(w["id"]) if s["role"] == "books")
    store.exclude(w["id"], src["id"])
    assert store.get_run(old["id"])["stale"]
    assert len(store.export_sources(old["source_ids"])) == 2
    preview = store.preview(w["id"], "books", src["name"], files[1], {})
    store.commit(w["id"], preview["id"], True)
    assert not store.get_run(old["id"])["stale"]


def test_export_manifest_checksums_original_bytes_and_repeatability(loaded):
    store, w = loaded
    run = store.run(w["id"])
    sources = store.export_sources(run["source_ids"])
    a = evidence_bundle(run, sources)
    time.sleep(1.1)  # Detect hidden workbook wall-clock metadata.
    b = evidence_bundle(run, sources)
    assert a == b
    with ZipFile(io.BytesIO(a)) as z:
        manifest = json.loads(z.read("manifest.json"))
        for path, digest in manifest["sha256"].items():
            assert hashlib.sha256(z.read(path)).hexdigest() == digest
        for source in manifest["sources"]:
            assert hashlib.sha256(z.read(source["path"])).hexdigest() == source["hash"]
        wb = load_workbook(io.BytesIO(z.read("reconciliation.xlsx")), data_only=False)
        assert len(wb.sheetnames) == 6
        assert wb["Source documents"].max_row == run["coverage"]["assigned_documents"]+1


def test_formula_injection_escaped(loaded):
    store, w = loaded
    run = store.run(w["id"])
    run["rows"][0]["books"][0]["number"] = "=WEBSERVICE(\"https://example.com\")"
    wb = load_workbook(io.BytesIO(workbook(run)), data_only=False)
    assert all(cell.data_type != "f" for ws in wb for row in ws for cell in row)
    assert b"'=WEBSERVICE" in csv_report(run)


def test_excel_large_aggregate_is_exact_text():
    from monthly_gst.reports import amount_cell
    assert amount_cell(100000000000000001) == "1000000000000000.01"


def test_parser_upgrade_creates_new_revision(loaded, files, monkeypatch):
    store, w = loaded
    old = next(s for s in store.sources(w["id"]) if s["role"] == "books")
    monkeypatch.setattr("monthly_gst.store.PARSER_VERSION", "imports-future-test")
    revised = store.preview(w["id"], "books", "purchases.csv", files[1], {})
    assert revised["id"] != old["id"]
    store.commit(w["id"], revised["id"], True)
    assert len(store.sources(w["id"])) == 2
    assert next(s for s in store.sources(w["id"]) if s["role"] == "books")["parser_version"] == "imports-future-test"


def test_corrupt_source_bytes_block_evidence_export(loaded):
    store, w = loaded
    run = store.run(w["id"])
    with store.connect() as db:
        db.execute("UPDATE files SET content=?", (b"corrupt bytes",))
    with pytest.raises(ValueError, match="checksum"):
        store.export_sources(run["source_ids"])


def test_api_session_origin_pagination_and_download(tmp_path):
    client = TestClient(create_app(tmp_path, test_mode=True))
    assert client.get("/api/workspaces").status_code == 403
    assert client.get("/api/bootstrap", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/bootstrap", headers={"Host": "evil.example"}).status_code == 403
    client.headers["X-Session"] = client.get("/api/bootstrap").json()["token"]
    demo = client.post("/api/demo")
    assert demo.status_code == 200, demo.text
    rid = demo.json()["run_id"]
    result = client.get(f"/api/runs/{rid}?limit=1").json()
    assert len(result["rows"]) == 1
    assert result["row_count"] > 1
    exact = client.get(f"/api/runs/{rid}?status=exact").json()
    assert all(r["status"] == "exact" for r in exact["rows"])
    attention = client.get(f"/api/runs/{rid}?status=attention").json()
    assert any(r["status"] == "exact" and any(d["itc"] == "N" for d in r["portal"]) for r in attention["rows"])
    assert client.get(f"/api/runs/{rid}/download/zip").content[:2] == b"PK"
    assert client.post("/api/workspaces", json={"name": "B", "gstin": "invalid", "period": "2026-10"}).status_code == 422
