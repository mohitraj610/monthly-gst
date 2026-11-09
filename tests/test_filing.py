import hashlib
import io
import json
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from monthly_gst.api import create_app
from monthly_gst.filing import normalize_filing, worksheet
from monthly_gst.store import Conflict, Store


def draft(**changes):
    return {"portal": {}, "reviewed": {}, "notes": {}, "reviewer": "", "checks": [], **changes}


def test_net_respects_head_separation_sign_and_disclosures():
    amounts = {
        "4A1": {"igst": "0"}, "4A2": {"igst": "-5.25"},
        "4A3": {"igst": "0"}, "4A4": {"igst": "0"},
        "4A5": {"igst": "100.01", "cgst": "55.00"},
        "4B1": {"igst": "110.00"}, "4B2": {"igst": "0"},
        "4D1": {"igst": "2500.00"}, "4D2": {"igst": "500.00"},
    }
    result = worksheet(normalize_filing(draft(reviewed=amounts)))
    assert result["net"]["reviewed"] == {"igst": "-15.24", "cgst": None, "sgst": None, "cess": None}


def test_partial_input_is_distinct_from_zero_and_delta_is_signed():
    normalized = normalize_filing(draft(
        portal={"4A5": {"igst": "100.00", "cgst": "0"}},
        reviewed={"4A5": {"igst": "99.99", "cgst": "  "}},
    ))
    row = next(row for row in worksheet(normalized)["rows"] if row["id"] == "4A5")
    assert row["difference"]["igst"] == "-0.01"
    assert row["difference"]["cgst"] is None
    assert normalized["portal"]["4A5"]["cgst"] == "0.00"
    assert "cgst" not in normalized["reviewed"]["4A5"]


@pytest.mark.parametrize("values", [
    {"4C": {"igst": "0"}}, {"4A5": {"gross": "1"}},
    {"4A5": {"igst": "0.001"}}, {"4A5": {"igst": "1.000000000000000000000000001"}},
    {"4A5": {"igst": "-"}},
])
def test_reject_invalid_rows_and_amounts(values):
    with pytest.raises(ValueError):
        normalize_filing(draft(reviewed=values))


def test_worksheet_is_persisted_and_optimistically_versioned(loaded):
    store, w = loaded
    run = store.run(w["id"])
    rid = run["id"]
    assert store.filing_review(rid)["reviewed"] == {}
    data = draft(reviewed={"4A5": {"igst": "120.5"}}, reviewer="Reviewer")
    first = store.save_filing_review(rid, 0, data)
    assert first["revision"] == 1
    assert Store(store.path).filing_review(rid) == first
    assert store.save_filing_review(rid, 0, data) == first
    with pytest.raises(Conflict, match="another tab"):
        store.save_filing_review(rid, 0, draft(reviewer="Different reviewer"))
    assert store.save_filing_review(rid, 1, draft())["revision"] == 2
    assert store.get_run(rid)["rows"] == run["rows"]


def test_old_run_keeps_worksheet_after_source_change(loaded):
    store, w = loaded
    rid = store.run(w["id"])["id"]
    store.save_filing_review(rid, 0, draft())
    src = next(s for s in store.sources(w["id"]) if s["role"] == "portal")
    store.exclude(w["id"], src["id"])
    with pytest.raises(Conflict, match="inputs changed"):
        store.save_filing_review(rid, 1, draft(reviewer="Reviewer"))
    assert store.filing_review(rid)["revision"] == 1
    new_run = store.run(w["id"])["id"]
    with pytest.raises(ValueError, match="Reconcile both"):
        store.save_filing_review(new_run, 0, draft())


def test_download_contains_review_revision_and_bound_evidence(tmp_path):
    client = TestClient(create_app(tmp_path, test_mode=True))
    client.headers["X-Session"] = client.get("/api/bootstrap").json()["token"]
    rid = client.post("/api/demo").json()["run_id"]
    endpoint = f"/api/runs/{rid}/filing"
    assert client.get(endpoint + "/download").status_code == 409
    result = client.put(endpoint, json={"revision": 0, **draft(
        portal={"4A5": {"igst": "180.00"}}, reviewed={"4A5": {"igst": "175.00"}},
        notes={"4A5": "=UNTRUSTED()\x01"}, checks=["sales"],
    )})
    assert result.status_code == 200, result.text
    assert client.get(endpoint + "/download?revision=0").status_code == 409
    exported = client.get(endpoint + "/download?revision=1")
    assert exported.status_code == 200
    with ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["run_id"] == rid and manifest["worksheet_revision"] == 1
        for name, digest in manifest["sha256"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
        book = load_workbook(io.BytesIO(archive.read("filing-review.xlsx")))
        rows = list(book["Table 4 review"].values)
        assert any(r[0] == "4(A)(5)" and r[2] == "Difference" and r[3] == -5 for r in rows)
        assert any(r[0] == "4(A)(5)" and r[2] == "Reviewed" and r[7].startswith("'=") for r in rows)
        assert book["Filing checklist"]["B2"].value == "Checked"
