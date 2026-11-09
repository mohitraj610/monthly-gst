"""Fictional data: deliberately contains audited failure patterns."""
import csv
import io
import json

from .domain import gstin_check_digit


def synthetic_gstin(state="29"):
    prefix = state + "ABCDE1234F1Z"
    return prefix + gstin_check_digit(prefix)


def demo_files():
    gstin, supplier = synthetic_gstin(), synthetic_gstin("27")
    headers = ["Supplier GSTIN", "Invoice Number", "Invoice Date", "Document Type", "Taxable Value", "IGST Amount", "CGST Amount", "SGST Amount", "Cess Amount", "Invoice Value", "Place of Supply", "Reverse Charge"]
    book = []
    portal = []
    def add(number, *, b=True, p=True, kind="INV", bt=(1000,180,0,0,0,1180), pt=None, pn=None, bd="2026-10-01", pd=None, itc="Y"):
        if b:
            book.append([supplier, number, bd, kind, *bt, "29", "N"])
        if p:
            t = pt or bt
            portal.append({"inum": pn or number, "dt": pd or bd, "val": str(t[5]), "pos": "29", "rev": "N", "itcavl": itc,
                           "items": [{"txval": str(t[0]), "igst": str(t[1]), "cgst": str(t[2]), "sgst": str(t[3]), "cess": str(t[4])}], "_kind": kind})
    add("INV-1001")
    add("INV-1002", bt=(1000,0,90,90,0,1180), pt=(1000,180,0,0,0,1180))
    add("INV-1003")
    add("INV-1003", p=False)
    add("INV/1004", pn="INV-1004")
    add("INV-1005", p=False)
    add("INV-1006", b=False)
    add("CN-1007", kind="CN", bt=(200,36,0,0,0,236))
    add("INV-1008", bd="2026-09-30", pd="2026-10-01")
    add("INV-1009", itc="N")
    add("ANNUAL-01", bd="2025-10-01", p=False)
    add("ANNUAL-01", bd="2026-10-01")
    normal, notes = [], []
    for item in portal:
        kind = item.pop("_kind")
        if kind == "CN":
            item["ntty"] = "C"
            item["nt_num"] = item.pop("inum")
            notes.append(item)
        else:
            normal.append(item)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(book)
    statement = {"gstin": gstin, "rtnprd": "102026", "docdata": {"b2b": [{"ctin": supplier, "trdnm": "Fictional supplier", "inv": normal}], "cdnr": [{"ctin": supplier, "nt": notes}]}}
    return gstin, output.getvalue().encode("utf-8-sig"), json.dumps(statement, indent=2).encode()
