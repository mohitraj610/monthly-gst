"""Deterministic diagnostic exports; no independent monetary calculations."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime
from decimal import Decimal
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from .domain import HEADS, formatted, stable_hash
from .filing import signed_paise


def text_cell(value):
    value = ILLEGAL_CHARACTERS_RE.sub("\ufffd", str(value if value is not None else ""))
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r")) else value


def deterministic_zip(entries):
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as z:
        for name, content in sorted(entries.items()):
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            z.writestr(info, content)
    return output.getvalue()


def amount_cell(paise):
    # Excel numeric cells preserve only 15 significant digits. Keep larger
    # aggregates as exact text instead of silently rounding source totals.
    if paise is None:
        return "UNKNOWN"
    return Decimal(paise) / 100 if abs(paise) < 10**15 else formatted(paise)


def workbook(result, filing=None):
    wb = Workbook()
    wb.remove(wb.active)
    wb.properties.created = wb.properties.modified = datetime(2000, 1, 1)
    sheets = {}
    def sheet(name, headers):
        ws = wb.create_sheet(name)
        ws.append(headers)
        ws.freeze_panes = "A2"
        for cell in ws[1]:
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = PatternFill("solid", fgColor="163A32")
        sheets[name] = ws
        return ws
    summary = sheet("Summary", ["Field", "Value"])
    purpose = "FILING REVIEW WORKING PAPERS" if filing else "INCOMPLETE RECONCILIATION DIAGNOSTIC — NOT A RETURN OR ITC CLAIM"
    for key, value in {"Purpose": purpose, "Business": result["workspace"]["name"],
                       "GSTIN": result["workspace"]["gstin"], "Period": result["workspace"]["period"], "Run": result["id"],
                       "Inputs fingerprint": result["fingerprint"], "Engine": result["engine_version"], "Stale inputs": str(result["stale"]),
                       "Book documents": result["coverage"]["book_documents"], "Portal documents": result["coverage"]["portal_documents"],
                       "Every parsed document accounted for": str(result["coverage"]["conserved"]), "Unsupported sections": len(result["source_issues"])}.items():
        summary.append([key, text_cell(value) if isinstance(value, str) else value])
    if filing:
        for label, value in {
            "Worksheet revision": filing["revision"], "Saved UTC": filing["updated"],
            "Reviewer entered by user": filing["reviewer"], "Records flagged for attention": result["attention_count"],
            "Use": "Compare the entered figures with the portal draft and accountant-reviewed records before filing.",
            "Blank amounts": "Await entry. Only confirmed zeros should be entered as zero.",
            "Table 4(C)": "Calculated per head once every 4(A) and 4(B) amount for that head is entered.",
            "Difference": "Reviewed amount minus portal amount.",
        }.items():
            summary.append([label, text_cell(value) if isinstance(value, str) else value])
    amounts = sheet("Source totals", ["Side", "Amount", "Signed value INR", "Unknown document amounts"])
    for side, totals in result["totals"].items():
        for h, t in totals.items():
            amounts.append([side, h, amount_cell(t["paise"]), t["unknown"]])
    rows = sheet("Reconciliation", ["Status", "Supplier GSTIN", "Books documents", "Portal documents", "Books refs", "Portal refs", "Differences", "Portal ITC flag", "Review note", "Row ID"])
    detail = sheet("Source documents", ["Row ID", "Side", "Source", "Reference", "Supplier GSTIN", "Document", "Date", "Kind", *HEADS, "Issues"])
    for row in result["rows"]:
        a, b = row["books"], row["portal"]
        rows.append([text_cell(row["status"]), text_cell((a or b)[0]["supplier_gstin"]), text_cell("; ".join(d["number"] for d in a)), text_cell("; ".join(d["number"] for d in b)),
                     text_cell("; ".join(f"{d['source_name']}:{','.join(d['refs'])}" for d in a)), text_cell("; ".join(f"{d['source_name']}:{','.join(d['refs'])}" for d in b)),
                     text_cell("; ".join(f"{d['field']}: {d['books']} → {d['portal']}" for d in row["differences"])), text_cell(", ".join(d["itc"] for d in b)), text_cell((row["review"] or {}).get("note", "")), row["id"]])
        for d in a+b:
            detail.append([row["id"], d["side"], text_cell(d["source_name"]), text_cell("; ".join(d["refs"])), d["supplier_gstin"], text_cell(d["number"]), d["date"], d["kind"],
                           *[amount_cell(d["amounts"][h]) for h in HEADS], text_cell("; ".join(d["issues"]))])
    unsupported = sheet("Coverage exceptions", ["Source", "Section", "Source path", "Reason"])
    for issue in result["source_issues"]:
        unsupported.append([text_cell(issue["source_name"]), text_cell(issue["section"]), text_cell(issue["path"]), issue["reason"]])
    reviews = sheet("Review history", ["Row", "Reviewer", "Note", "Recorded UTC"])
    for r in result["review_events"]:
        reviews.append([r["row_id"], text_cell(r["actor"]), text_cell(r["note"]), r["created"]])
    if filing:
        table = sheet("Table 4 review", ["Table", "Description", "Figures", "IGST", "CGST", "SGST / UTGST", "Cess", "Review note"])
        for row in filing["rows"]:
            key = row["id"]
            for label, values, note in (
                ("Portal", filing["portal"].get(key, {}), ""),
                ("Reviewed", filing["reviewed"].get(key, {}), filing["notes"].get(key, "")),
                ("Difference", row["difference"], ""),
            ):
                cells = [amount_cell(signed_paise(values[head])) if values.get(head) is not None else None for head in filing["heads"]]
                table.append([row["code"], row["label"], label, *cells, text_cell(note)])
        for label, side in (("From portal entries", "portal"), ("From reviewed entries", "reviewed")):
            values = filing["net"][side]
            cells = [amount_cell(signed_paise(values[head])) if values[head] is not None else None for head in filing["heads"]]
            table.append(["4(C)", "Net ITC after reversals", label, *cells, ""])
        checklist = sheet("Filing checklist", ["Step", "Recorded by user", "Check", "Official reference"])
        for item in filing["checklist"]:
            status = "Checked" if item["id"] in filing["checks"] else "Pending"
            checklist.append([item["title"], status, item["detail"], item["url"]])
    for ws in wb:
        ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            max_length = max(len(str(c.value or "")) for c in col)
            ws.column_dimensions[get_column_letter(col[0].column)].width = min(65, max(14, max_length + 2))
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(vertical="top")
                if isinstance(cell.value, Decimal):
                    cell.number_format = '#,##0.00;[Red]-#,##0.00'
    out = io.BytesIO()
    wb.save(out)
    with ZipFile(io.BytesIO(out.getvalue())) as z:
        entries = {n: z.read(n) for n in z.namelist()}
    # openpyxl writes its current save time despite Workbook.properties.modified.
    import re
    entries["docProps/core.xml"] = re.sub(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)", rb"\g<1>2000-01-01T00:00:00Z\g<2>", entries["docProps/core.xml"])
    return deterministic_zip(entries)


def csv_report(result):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["Diagnostic only - no ITC claim or filing assessment", result["workspace"]["gstin"], result["workspace"]["period"]])
    writer.writerow(["Status", "Side", "Supplier GSTIN", "Document", "Date", "Kind", *HEADS, "Source", "Source refs", "Issues", "Portal ITC flag", "Review"])
    for row in result["rows"]:
        for d in row["books"] + row["portal"]:
            writer.writerow([text_cell(row["status"]), d["side"], d["supplier_gstin"], text_cell(d["number"]), d["date"], d["kind"],
                             *[formatted(d["amounts"][h]) if d["amounts"][h] is not None else "UNKNOWN" for h in HEADS],
                             text_cell(d["source_name"]), text_cell(";".join(d["refs"])), text_cell(";".join(d["issues"])), text_cell(d["itc"] if d["side"] == "portal" else "NOT_ASSESSED"), text_cell((row["review"] or {}).get("note", ""))])
    return out.getvalue().encode("utf-8-sig")


def evidence_bundle(result, source_pairs, filing=None):
    workbook_name = "filing-review.xlsx" if filing else "reconciliation.xlsx"
    entries = {workbook_name: workbook(result, filing), "reconciliation.csv": csv_report(result),
               "result.json": json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2).encode()}
    if filing:
        entries["filing-review.json"] = json.dumps(filing, sort_keys=True, ensure_ascii=False, indent=2).encode()
    sources = []
    for meta, content in source_pairs:
        path = f"sources/{meta['hash'][:16]}-{meta['name']}"
        entries[path] = content
        sources.append({**meta, "path": path})
    manifest = {"purpose": "Reconciliation diagnostic only; not a return or credit claim", "workspace": result["workspace"], "run_id": result["id"],
                "engine_version": result["engine_version"], "fingerprint": result["fingerprint"], "stale": result["stale"], "sources": sources,
                "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(entries.items())}}
    if filing:
        manifest["purpose"] = "Filing review working papers with user-entered figures"
        manifest["worksheet_revision"] = filing["revision"]
    manifest["manifest_hash"] = stable_hash(manifest)
    entries["manifest.json"] = json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2).encode()
    return deterministic_zip(entries)
