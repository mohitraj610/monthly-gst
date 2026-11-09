"""Bounded CSV/XLSX and explicit 2B adapters with immutable raw row lineage."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from zipfile import ZipFile, BadZipFile
from xml.etree.ElementTree import ParseError
from defusedxml.common import DefusedXmlException

from .domain import Document, HEADS, STATES, money, parse_date, stable_hash, valid_gstin

MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 50_000
MAX_COLUMNS = 100
PARSER_VERSION = "imports-1.0.0-alpha.2"
FIELDS = ("supplier_gstin", "number", "date", "kind", "taxable", "igst", "cgst", "sgst", "cess", "total", "pos", "rcm")
ALIASES = {
    "supplier_gstin": ["supplier gstin", "gstin of supplier", "gstin", "party gstin", "vendor gstin"],
    "number": ["supplier invoice number", "supplier invoice no", "invoice number", "invoice no", "bill no", "document number"],
    "date": ["invoice date", "document date", "supplier invoice date", "bill date"],
    "kind": ["document type", "document kind", "invoice type", "kind"],
    "taxable": ["taxable value", "taxable amount", "assessable value"],
    "igst": ["igst", "igst amount", "integrated tax", "integrated tax amount"],
    "cgst": ["cgst", "cgst amount", "central tax", "central tax amount"],
    "sgst": ["sgst", "sgst amount", "state tax", "state tax amount", "sgst utgst", "utgst"],
    "cess": ["cess", "cess amount", "cess tax"],
    "total": ["invoice value", "invoice total", "total amount", "bill amount", "gross total"],
    "pos": ["place of supply", "pos", "pos code", "state code"],
    "rcm": ["reverse charge", "rcm", "reverse charge applicable"],
}


def header_key(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def safe_raw(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat() if isinstance(value, date) else value


def inspect_table(content: bytes, name: str, sheet: str | None = None, header_row: int = 1) -> dict:
    if not content or len(content) > MAX_BYTES:
        raise ValueError("Choose a non-empty file no larger than 20 MB")
    if not 1 <= header_row <= 50:
        raise ValueError("Header row must be between 1 and 50")
    suffix = Path(name).suffix.lower()
    if suffix == ".csv":
        if content.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = content.decode("utf-16")
        else:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise ValueError("CSV must be UTF-8 or UTF-16. Save a UTF-8 CSV from Excel.") from exc
        reader = csv.reader(io.StringIO(text), delimiter=",", strict=True)
        matrix = []
        try:
            for row in reader:
                if len(row) > MAX_COLUMNS or len(matrix) > MAX_ROWS + 50:
                    raise ValueError("File exceeds 50,000 rows or 100 columns")
                matrix.append(row)
        except csv.Error as exc:
            raise ValueError("Invalid CSV or excessively long cell; use a clean comma-separated export") from exc
        sheets, selected = ["CSV"], "CSV"
    elif suffix == ".xlsx":
        try:
            with ZipFile(io.BytesIO(content)) as z:
                if sum(i.file_size for i in z.infolist()) > 100 * 1024 * 1024 or len(z.infolist()) > 2000:
                    raise ValueError("Workbook expands beyond safe limits")
                if any("externallinks/" in i.filename.lower() or "vbaproject" in i.filename.lower() or ".." in i.filename.split("/") for i in z.infolist()):
                    raise ValueError("Workbook contains external links, macros or unsafe paths")
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=False)
            sheets = wb.sheetnames
            if sheet and sheet not in sheets:
                raise ValueError("Selected sheet does not exist")
            selected = sheet or sheets[0]
            ws = wb[selected]
            if (ws.max_row or 0) > MAX_ROWS + 50 or (ws.max_column or 0) > MAX_COLUMNS:
                raise ValueError("Workbook exceeds 50,000 rows or 100 columns")
            matrix = []
            for cells in ws.iter_rows():
                if len(matrix) > MAX_ROWS + 50 or len(cells) > MAX_COLUMNS:
                    raise ValueError("Workbook exceeds 50,000 rows or 100 columns")
                row = []
                for cell in cells:
                    if cell.data_type == "f":
                        row.append({"formula": cell.value})
                    else:
                        row.append(safe_raw(cell.value))
                matrix.append(row)
            wb.close()
        except (BadZipFile, KeyError, ParseError, DefusedXmlException) as exc:
            raise ValueError("Invalid XLSX workbook") from exc
    else:
        raise ValueError("Use CSV or XLSX. Convert XLS/XLSM/XLSB files to a values-only XLSX.")
    if len(matrix) < header_row:
        raise ValueError("Header row is outside the file")
    headers = [str(v or "").strip() for v in matrix[header_row-1]]
    if not headers or len(set(headers)) != len(headers) or any(not h for h in headers):
        raise ValueError("Headers must be non-empty and unique; select the correct header row")
    mapping = {}
    for field, aliases in ALIASES.items():
        candidates = [h for h in headers if header_key(h) in {header_key(a) for a in aliases}]
        if len(candidates) == 1:
            mapping[field] = candidates[0]
    rows = []
    excluded = []
    for index, values in enumerate(matrix[header_row:], start=header_row+1):
        if any(v is not None and str(v).strip() for v in values[len(headers):]):
            raise ValueError(f"Row {index} contains cells beyond the selected header columns; correct the header row")
        if not any(v is not None and str(v).strip() for v in values):
            excluded.append({"row": index, "reason": "Empty row"})
        else:
            rows.append({"row": index, "cells": {h: values[i] if i < len(values) else None for i, h in enumerate(headers)}})
    if len(rows) > MAX_ROWS:
        raise ValueError("File exceeds 50,000 data rows")
    return {"headers": headers, "sheets": sheets, "sheet": selected, "mapping": mapping, "rows": rows, "excluded": excluded,
            "preamble_rows": header_row-1, "header_row": header_row, "input_rows": len(matrix)-header_row}


def _bool(value):
    s = str(value if value is not None else "").strip().upper()
    if s in {"Y", "YES", "TRUE", "1"}:
        return True
    if s in {"N", "NO", "FALSE", "0"}:
        return False
    return None


def _pos(value):
    s = str(value or "").strip()
    if re.fullmatch(r"\d{1,2}\.0", s):
        s = s[:-2]  # Numeric Excel state-code cells.
    m = re.fullmatch(r"(\d{1,2})(?:(?:\s*[-–]\s*|\s+)[A-Za-z][A-Za-z &().-]*)?", s)
    return m[1].zfill(2) if m and m[1].zfill(2) in STATES else None


def parse_books(table: dict, source_id: str, name: str, options: dict) -> dict:
    mapping = options.get("mapping", table["mapping"])
    if not isinstance(mapping, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
        raise ValueError("Mapping must contain field names and source column names")
    mapping = {k: v for k, v in mapping.items() if v}
    if set(mapping) - set(FIELDS) or any(v not in table["headers"] and v not in {"__zero__", "__no__", "__invoice__"} for v in mapping.values()):
        raise ValueError("Mapping contains an unknown field or source column")
    if not all(mapping.get(f) for f in ("supplier_gstin", "number", "date")):
        raise ValueError("Map supplier GSTIN, supplier document number and invoice date first")
    granularity = options.get("granularity", "invoice")
    if granularity not in {"invoice", "line"}:
        raise ValueError("Choose invoice-per-row or line-per-row")
    order = options.get("date_order", "DMY")
    if order not in {"DMY", "MDY"}:
        raise ValueError("Unsupported date order")
    docs = []
    for row in table["rows"]:
        issues = []
        def value(field):
            col = mapping.get(field)
            if col == "__zero__":
                return "0"
            if col == "__no__":
                return "N"
            if col == "__invoice__":
                return "INV"
            val = row["cells"].get(col)
            if isinstance(val, dict) and "formula" in val:
                issues.append(f"{field}: formula cell requires a values-only export")
                return None
            return val
        supplier = str(value("supplier_gstin") or "").strip().upper()
        if not valid_gstin(supplier):
            issues.append("Supplier GSTIN is missing or fails format/checksum validation")
        number = str(value("number") or "").strip()
        if not number or len(number) > 64:
            issues.append("Supplier document number is missing or longer than 64 characters")
        try:
            d = parse_date(value("date"), order)
        except ValueError as exc:
            d = ""
            issues.append(str(exc))
        kind_raw = str(value("kind") or "").strip().upper()
        kind = {"INVOICE": "INV", "TAX INVOICE": "INV", "INV": "INV", "CREDIT NOTE": "CN", "CN": "CN", "DEBIT NOTE": "DN", "DN": "DN"}.get(kind_raw, "UNKNOWN")
        if kind == "UNKNOWN":
            issues.append("Declare document kind: invoice, credit note or debit note")
        amounts = {}
        for head in HEADS:
            try:
                amounts[head] = money(value(head))
            except ValueError as exc:
                amounts[head] = None
                issues.append(f"{head}: {exc}")
        pos, rcm = _pos(value("pos")), _bool(value("rcm"))
        if pos is None:
            issues.append("Place of supply is unknown; map a state code")
        if rcm is None:
            issues.append("Reverse-charge status is unknown; map it or explicitly declare No")
        docs.append(Document(stable_hash([source_id, row["row"]])[:24], "books", source_id, name,
                             [f"{table['sheet']}!row {row['row']}"], supplier, number, d, kind, amounts, pos, rcm, issues=issues, raw=[row["cells"]]))
    if granularity == "line":
        groups = defaultdict(list)
        for d in docs:
            groups[d.key() or (d.id,)].append(d)
        merged = []
        for group in groups.values():
            first = group[0]
            if len(group) > 1:
                for f in ("date", "pos", "rcm"):
                    if len({getattr(d, f) for d in group}) != 1:
                        first.issues.append(f"Conflicting {f} across line rows")
                for h in HEADS:
                    vals = [d.amounts[h] for d in group]
                    if h == "total":
                        first.amounts[h] = vals[0] if len(set(vals)) == 1 else None
                        if len(set(vals)) != 1:
                            first.issues.append("Repeated invoice totals disagree across line rows")
                    else:
                        first.amounts[h] = sum(vals) if all(v is not None for v in vals) else None
                first.refs = [r for d in group for r in d.refs]
                first.raw = [r for d in group for r in d.raw]
                first.issues = sorted(set(first.issues + [e for d in group for e in d.issues]))
            merged.append(first)
        docs = merged
    return {"documents": [asdict(d) for d in docs], "issues": [], "coverage": {"input_rows": table["input_rows"], "data_rows": len(table["rows"]),
            "excluded_rows": table["excluded"], "document_count": len(docs), "incomplete_documents": sum(bool(d.issues) for d in docs)},
            "mapping": mapping, "options": options}


def parse_2b(content: bytes, source_id: str, name: str, gstin: str, period: str) -> dict:
    if not content or len(content) > MAX_BYTES:
        raise ValueError("2B file must be non-empty and at most 20 MB")
    def unique_object(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("JSON contains duplicate keys; no data was imported")
            result[k] = v
        return result
    try:
        root = json.loads(content.decode("utf-8-sig"), parse_float=str, object_pairs_hook=unique_object,
                          parse_constant=lambda v: (_ for _ in ()).throw(ValueError("Non-finite JSON number is invalid")))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Invalid or excessively nested JSON") from exc
    if isinstance(root, dict) and isinstance(root.get("data"), dict):
        root = root["data"]
    if not isinstance(root, dict) or not isinstance(root.get("docdata"), dict):
        raise ValueError("Expected official 2B JSON containing docdata")
    if str(root.get("gstin", "")).strip().upper() != gstin:
        raise ValueError("This 2B belongs to another GSTIN. Nothing was imported.")
    statement_period = str(root.get("rtnprd") or root.get("fp") or "")
    expected_period = period[5:7] + period[:4]
    if statement_period != expected_period:
        raise ValueError(f"2B period is {statement_period or 'missing'}, expected {expected_period}. Select the corresponding month.")
    docs, issues = [], []
    docdata = root["docdata"]
    for section, suppliers in docdata.items():
        if section not in {"b2b", "cdnr"}:
            if suppliers:
                issues.append({"section": section, "reason": "Unsupported 2B section retained in the original source; reconciliation is incomplete", "path": f"docdata.{section}"})
            continue
        if not isinstance(suppliers, list):
            raise ValueError(f"Invalid {section} section: expected a list")
        for si, supplier in enumerate(suppliers):
            if not isinstance(supplier, dict):
                raise ValueError("Invalid supplier record")
            records = supplier.get("inv", []) if section == "b2b" else supplier.get("nt", supplier.get("inv", []))
            if not isinstance(records, list):
                raise ValueError("Invalid document list")
            if not records:
                issues.append({"section": section, "path": f"docdata.{section}[{si}]", "reason": "Supplier entry has no recognized document list; inspect original source"})
            for ii, inv in enumerate(records):
                if not isinstance(inv, dict):
                    raise ValueError("Invalid invoice record")
                problems = []
                supplier_gstin = str(supplier.get("ctin", "")).strip().upper()
                if not valid_gstin(supplier_gstin):
                    problems.append("Supplier GSTIN fails checksum/format validation")
                number = str(inv.get("inum") or inv.get("ntnum") or inv.get("nt_num") or "").strip()
                if not number:
                    problems.append("Document number is missing")
                try:
                    dt = parse_date(inv.get("dt") or inv.get("nt_dt") or inv.get("ntdt"))
                except ValueError:
                    dt = ""
                    problems.append("Document date is invalid or missing")
                kind = "INV" if section == "b2b" else {"C": "CN", "D": "DN"}.get(str(inv.get("typ") or inv.get("ntty") or "").upper(), "UNKNOWN")
                if section == "b2b" and inv.get("typ") not in (None, "R"):
                    problems.append("Non-regular invoice type is outside this alpha's supported scope")
                if kind == "UNKNOWN":
                    problems.append("Credit/debit note kind is unknown")
                aliases = {"taxable": ("txval",), "igst": ("igst", "iamt"), "cgst": ("cgst", "camt"), "sgst": ("sgst", "samt"), "cess": ("cess", "csamt")}
                items = inv.get("items")
                if items is not None and (not isinstance(items, list) or not all(isinstance(i, dict) for i in items)):
                    raise ValueError("Invalid invoice items")
                amounts = {}
                for head, names in aliases.items():
                    def field_amount(obj):
                        present = [money(obj[n]) for n in names if n in obj]
                        if len(set(present)) > 1:
                            raise ValueError("Conflicting amount aliases in source")
                        return present[0] if present else 0 if head != "taxable" else None
                    try:
                        direct = field_amount(inv) if any(n in inv for n in names) else None
                        listed = [field_amount(i) for i in items] if items else []
                        aggregate = sum(listed) if listed and all(v is not None for v in listed) else None
                        if direct is not None and aggregate is not None and direct != aggregate:
                            problems.append(f"{head}: header and item amounts disagree")
                        amounts[head] = aggregate if aggregate is not None else direct
                        if amounts[head] is None:
                            amounts[head] = 0 if head != "taxable" else None
                    except ValueError as exc:
                        amounts[head] = None
                        problems.append(f"{head}: {exc}")
                try:
                    amounts["total"] = money(inv.get("val"))
                except ValueError as exc:
                    amounts["total"] = None
                    problems.append(f"total: {exc}")
                pos, rcm = _pos(inv.get("pos")), _bool(inv.get("rev", inv.get("rchrg")))
                if pos is None or rcm is None:
                    problems.append("Place of supply or reverse-charge status is missing")
                path = f"docdata.{section}[{si}].{'inv' if 'inv' in supplier else 'nt'}[{ii}]"
                itc = str(inv.get("itcavl", "UNKNOWN")).strip().upper()
                docs.append(asdict(Document(stable_hash([source_id, path])[:24], "portal", source_id, name, [path], supplier_gstin, number, dt, kind, amounts,
                                           pos, rcm, itc if itc in {"Y", "N"} else "UNKNOWN", problems, [inv])))
                if len(docs) > MAX_ROWS:
                    raise ValueError("2B contains more than 50,000 supported documents")
    return {"documents": docs, "issues": issues, "coverage": {"supported_documents": len(docs), "unsupported_sections": len(issues), "sections_seen": list(docdata)},
            "metadata": {"gstin": gstin, "period": period, "statement_period": statement_period}, "options": {}}
