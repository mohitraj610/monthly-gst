import io
import json
from copy import deepcopy
from zipfile import ZipFile

import pytest
from openpyxl import Workbook

from monthly_gst.domain import document_from_dict, reconcile
from monthly_gst.imports import inspect_table, parse_books, parse_2b
from conftest import changed_books, csv_bytes


def portal(files, mutate=None):
    gstin, _, data = files
    root = json.loads(data)
    if mutate:
        mutate(root)
    return parse_2b(json.dumps(root).encode(), "p", "2b.json", gstin, "2026-10")


def books(files, options=None, data=None):
    return parse_books(inspect_table(data or files[1], "books.csv"), "b", "books.csv", options or {})


def test_demo_failure_patterns_end_to_end(files):
    result = reconcile([document_from_dict(d) for d in books(files)["documents"]], [document_from_dict(d) for d in portal(files)["documents"]])
    by_num = {(r["books"] or r["portal"])[0]["number"]: r for r in result["rows"]}
    assert by_num["INV-1002"]["status"] == "tax_head_difference"
    assert by_num["INV-1003"]["status"] == "duplicate"
    assert by_num["INV/1004"]["status"] == "suggested"
    assert by_num["INV-1008"]["status"] == "metadata_difference"
    assert by_num["INV-1009"]["itc"] == "NOT_ASSESSED"
    assert result["coverage"]["conserved"]


@pytest.mark.parametrize("field,value", [("gstin", "27ABCDE1234F1Z0"), ("rtnprd", "092026"), ("rtnprd", "")])
def test_wrong_workspace_rejected(files, field, value):
    with pytest.raises(ValueError):
        portal(files, lambda root: root.update({field: value}))


def test_unknown_sections_preserved_as_coverage_exceptions(files):
    parsed = portal(files, lambda root: root["docdata"].update(impg=[{"txval": "500"}], b2ba=[{"ctin": "new"}]))
    assert {i["section"] for i in parsed["issues"]} == {"impg", "b2ba"}


def test_duplicate_json_keys_rejected(files):
    with pytest.raises(ValueError, match="duplicate keys"):
        parse_2b(b'{"docdata":{},"docdata":{}}', "p", "2b.json", files[0], "2026-10")


def test_explicit_null_is_unknown_not_zero(files):
    parsed = portal(files, lambda root: root["docdata"]["b2b"][0]["inv"][0]["items"][0].update(cess=None))
    assert parsed["documents"][0]["amounts"]["cess"] is None
    assert parsed["documents"][0]["issues"]


def test_empty_2b_is_valid(loaded, files):
    store, w = loaded
    data = json.dumps({"gstin": files[0], "rtnprd": "102026", "docdata": {}}).encode()
    src = store.preview(w["id"], "portal", "empty.json", data, {})
    assert src["document_count"] == 0
    store.commit(w["id"], src["id"], True)
    run = store.run(w["id"])
    assert run["coverage"]["portal_documents"] == 0
    assert run["source_coverage"]["portal_present"]


def test_header_item_disagreement_never_exact(files):
    parsed = portal(files, lambda root: root["docdata"]["b2b"][0]["inv"][0].update(igst="0"))
    assert any("disagree" in x for x in parsed["documents"][0]["issues"])


def test_direct_invoice_schema_and_wrapped_data(files):
    root = json.loads(files[2])
    inv = root["docdata"]["b2b"][0]["inv"][0]
    inv.update(inv.pop("items")[0])
    result = parse_2b(json.dumps({"data": root}).encode(), "p", "2b.json", files[0], "2026-10")
    assert result["documents"][0]["amounts"]["igst"] == 18000


def test_blank_and_negative_books_retained_incomplete(files):
    data = changed_books(files, lambda rows: rows[1].__setitem__(5, ""))
    parsed = books(files, data=data)
    assert len(parsed["documents"]) == len(books(files)["documents"])
    assert parsed["documents"][0]["amounts"]["igst"] is None
    data = changed_books(files, lambda rows: rows[1].__setitem__(5, "-180"))
    assert books(files, data=data)["documents"][0]["amounts"]["igst"] is None


def test_ambiguous_columns_need_manual_mapping(files):
    table = inspect_table(b"GSTIN,Supplier GSTIN,Invoice Number,Invoice Date\nA,B,I,2026-10-01", "p.csv")
    assert "supplier_gstin" not in table["mapping"]
    with pytest.raises(ValueError, match="Map supplier"):
        parse_books(table, "b", "p.csv", {})


def test_line_granularity_sums_heads_counts_repeated_invoice_total_once(files):
    rows = files[1].decode().splitlines()
    import csv
    matrix = list(csv.reader(rows))
    row = matrix[1]
    row[4:10] = ["500", "90", "0", "0", "0", "1180"]
    data = csv_bytes([matrix[0], row, row])
    parsed = books(files, {"granularity": "line"}, data)
    assert len(parsed["documents"]) == 1
    doc = parsed["documents"][0]
    assert doc["amounts"]["taxable"] == 100000
    assert doc["amounts"]["igst"] == 18000
    assert doc["amounts"]["total"] == 118000
    assert len(doc["refs"]) == len(doc["raw"]) == 2
    assert not doc["issues"]
    assert len(books(files, data=data)["documents"]) == 2


def test_line_conflicting_totals_unknown(files):
    import csv
    matrix = list(csv.reader(io.StringIO(files[1].decode())))
    a = matrix[1]
    b = a.copy()
    b[9] = "999"
    parsed = books(files, {"granularity": "line"}, csv_bytes([matrix[0], a, b]))
    assert parsed["documents"][0]["amounts"]["total"] is None


def test_xlsx_formulas_are_not_evaluated_and_row_refs_survive(files):
    import csv
    rows = list(csv.reader(io.StringIO(files[1].decode())))[:2]
    wb = Workbook()
    ws = wb.active
    ws.title = "Purchase"
    ws.append(["Exported register"])
    for row in rows:
        ws.append(row)
    ws.cell(3, 6, "=90+90")
    content = io.BytesIO()
    wb.save(content)
    table = inspect_table(content.getvalue(), "p.xlsx", "Purchase", 2)
    parsed = parse_books(table, "b", "p.xlsx", {})
    doc = parsed["documents"][0]
    assert doc["refs"] == ["Purchase!row 3"]
    assert doc["amounts"]["igst"] is None
    assert any("formula" in e for e in doc["issues"])


def test_native_excel_date_cells_are_supported(files):
    import csv
    from datetime import datetime
    rows = list(csv.reader(io.StringIO(files[1].decode())))[:2]
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    wb.active.cell(2, 3, datetime(2026, 10, 1))
    data = io.BytesIO()
    wb.save(data)
    parsed = parse_books(inspect_table(data.getvalue(), "p.xlsx"), "b", "p.xlsx", {})
    assert parsed["documents"][0]["date"] == "2026-10-01"
    assert not parsed["documents"][0]["issues"]


def test_nonempty_extra_cells_are_not_silently_dropped():
    with pytest.raises(ValueError, match="header"):
        inspect_table(b"A,B\n1,2,UNMAPPED", "p.csv")


@pytest.mark.parametrize("data", [b"", b"A,A\n1,2", b"A,\n1,2"])
def test_bad_headers_rejected(data):
    with pytest.raises(ValueError):
        inspect_table(data, "p.csv")


@pytest.mark.parametrize("raw,expected", [("29", "29"), (29.0, "29"), ("29-Karnataka", "29"), ("29 Karnataka", "29"), ("29.5", None), ("29x", None), ("45", None)])
def test_state_codes_are_not_guessed(raw, expected):
    from monthly_gst.imports import _pos
    assert _pos(raw) == expected


def test_optional_unmapped_field_stays_unknown(files):
    table = inspect_table(files[1], "p.csv")
    mapping = table["mapping"] | {"cess": ""}
    parsed = parse_books(table, "b", "p.csv", {"mapping": mapping})
    assert parsed["documents"][0]["amounts"]["cess"] is None


def test_malformed_csv_is_a_useful_input_error():
    with pytest.raises(ValueError, match="CSV"):
        inspect_table(b'A,B\n"unterminated,field', "p.csv")


def test_json_nan_rejected(files):
    with pytest.raises(ValueError, match="Non-finite"):
        parse_2b(b'{"docdata":{},"x":NaN}', "p", "2b.json", files[0], "2026-10")
