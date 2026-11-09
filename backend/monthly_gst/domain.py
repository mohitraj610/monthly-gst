"""Pure reconciliation types. No I/O, UI, clock, or credit-claim decisions."""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

ENGINE_VERSION = "reconciliation-1.0.0-alpha.1"
HEADS = ("taxable", "igst", "cgst", "sgst", "cess", "total")
TAX_HEADS = ("igst", "cgst", "sgst", "cess")
STATES = {f"{n:02}" for n in range(1, 39)} | {"97", "99"}
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def gstin_check_digit(prefix: str) -> str:
    total = 0
    for i, ch in enumerate(prefix):
        factor = 1 if i % 2 == 0 else 2
        value = ALPHABET.index(ch) * factor
        total += value // 36 + value % 36
    return ALPHABET[(36 - total % 36) % 36]


def valid_gstin(value: str) -> bool:
    value = value.strip().upper()
    return bool(re.fullmatch(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[A-Z0-9]", value)) and value[:2] in STATES and gstin_check_digit(value[:14]) == value[-1]


def money(value: Any) -> int:
    """Parse authoritative money into paise; never silently round extra precision."""
    if value is None or isinstance(value, bool):
        raise ValueError("Missing amount; choose a source column or explicitly declare zero")
    s = str(value).strip().replace("₹", "").replace("\u00a0", "")
    s = re.sub(r"^Rs\.?\s*", "", s, flags=re.I)
    if not s:
        raise ValueError("Blank amount is unknown, not zero")
    if "," in s:
        if not (re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?", s) or re.fullmatch(r"\d{1,2}(,\d{2})*,\d{3}(\.\d+)?", s)):
            raise ValueError("Invalid grouping in amount")
        s = s.replace(",", "")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        raise ValueError("Use a non-negative plain amount and an explicit invoice/credit/debit kind")
    whole, _, fraction = s.partition(".")
    whole = whole.lstrip("0")
    if len(whole) > 12 or fraction[2:].strip("0"):
        raise ValueError("Amount needs explicit correction: precision exceeds paise or supported range")
    return int(whole or "0") * 100 + int(fraction[:2].ljust(2, "0"))


def formatted(paise: int | None) -> str | None:
    return None if paise is None else format(Decimal(paise) / 100, ".2f")


def parse_date(value: Any, order: str = "DMY") -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value or "").strip()
    formats = ["%Y-%m-%d", "%Y/%m/%d", "%d-%b-%Y", "%d %b %Y"]
    formats += ["%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"] if order == "DMY" else ["%m-%d-%Y", "%m/%d/%Y", "%m.%d.%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError("Invalid date; select day-first or month-first and inspect the preview")


def fiscal_year(iso: str) -> str:
    d = date.fromisoformat(iso)
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y}-{y+1}"


def normalize_number(raw: str) -> str:
    return raw.strip().upper()  # Punctuation and leading zeroes are meaningful.


def candidate_number(raw: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize_number(raw))


@dataclass
class Document:
    id: str
    side: str
    source_id: str
    source_name: str
    refs: list[str]
    supplier_gstin: str
    number: str
    date: str
    kind: str
    amounts: dict[str, int | None]
    pos: str | None = None
    rcm: bool | None = None
    itc: str = "UNKNOWN"
    issues: list[str] = field(default_factory=list)
    raw: list[dict] = field(default_factory=list)

    @property
    def sign(self) -> int:
        return -1 if self.kind == "CN" else 1

    def key(self, relaxed: bool = False) -> tuple | None:
        if not self.supplier_gstin or not self.date or not self.number or self.kind not in {"INV", "CN", "DN"}:
            return None
        num = candidate_number(self.number) if relaxed else normalize_number(self.number)
        return self.supplier_gstin, fiscal_year(self.date), self.kind, num

    def public(self) -> dict:
        result = asdict(self)
        result["values"] = {h: formatted(self.amounts[h]) for h in HEADS}
        return result


def document_from_dict(data: dict) -> Document:
    return Document(**{k: data[k] for k in Document.__dataclass_fields__ if k in data})


def compare(a: Document, b: Document) -> list[dict]:
    differences = []
    for h in HEADS:
        av, bv = a.amounts.get(h), b.amounts.get(h)
        if av != bv or av is None or bv is None:
            differences.append({"field": h, "books": formatted(av), "portal": formatted(bv), "delta_paise": None if av is None or bv is None else bv-av})
    for name in ("date", "pos", "rcm"):
        av, bv = getattr(a, name), getattr(b, name)
        if av != bv or av is None or bv is None:
            differences.append({"field": name, "books": av, "portal": bv, "delta_paise": None})
    return differences


def classify(a: Document, b: Document, differences: list[dict]) -> str:
    if a.issues or b.issues or any(a.amounts[h] is None or b.amounts[h] is None for h in HEADS) or a.pos is None or b.pos is None or a.rcm is None or b.rcm is None:
        return "incomplete"
    fields = {d["field"] for d in differences}
    if fields.intersection(TAX_HEADS):
        return "tax_head_difference"
    if fields.intersection({"total", "taxable"}):
        return "amount_difference"
    if fields:
        return "metadata_difference"
    return "exact"


def reconcile(books: list[Document], portal: list[Document]) -> dict:
    """Conservative, O(n) grouping. Every document belongs to exactly one result."""
    rows = []
    grouped = [defaultdict(list), defaultdict(list)]

    def emit(status: str, aa: list[Document], bb: list[Document], reasons: list[str] | None = None):
        diffs = compare(aa[0], bb[0]) if len(aa) == len(bb) == 1 else []
        ids = sorted(d.id for d in aa+bb)
        row = {"id": stable_hash(ids)[:24], "status": status, "books": [d.public() for d in aa], "portal": [d.public() for d in bb],
               "differences": diffs, "reasons": reasons or [], "itc": "NOT_ASSESSED", "review": None}
        if any(d.itc == "N" for d in bb):
            row["reasons"].append("Portal marks ITC unavailable. Matching does not authorize a credit claim.")
        if any(d.itc == "UNKNOWN" for d in bb):
            row["reasons"].append("Portal eligibility flag is unknown. No ITC eligibility has been assessed.")
        row["needs_attention"] = status != "exact" or any(d.itc != "Y" for d in bb)
        rows.append(row)

    for side, documents in enumerate((books, portal)):
        for doc in sorted(documents, key=lambda d: d.id):
            key = doc.key()
            if key is None:
                emit("incomplete", [doc] if side == 0 else [], [doc] if side else [], doc.issues.copy() or ["Document identity is incomplete"])
            else:
                grouped[side][key].append(doc)
    leftovers = [[], []]
    for key in sorted(set(grouped[0]) | set(grouped[1])):
        a, b = grouped[0].get(key, []), grouped[1].get(key, [])
        if len(a) > 1 or len(b) > 1:
            emit("duplicate", a, b, ["Multiple records share supplier, financial year, document kind and number. None was overwritten or automatically linked."])
        elif a and b:
            diffs = compare(a[0], b[0])
            status = classify(a[0], b[0], diffs)
            emit(status, a, b, ["Identity and all compared fields agree."] if status == "exact" else ["Inspect the differences and source records before taking action."])
        else:
            leftovers[0].extend(a)
            leftovers[1].extend(b)
    candidates = [defaultdict(list), defaultdict(list)]
    for side in (0, 1):
        for d in leftovers[side]:
            candidates[side][d.key(relaxed=True)].append(d)
    for key in sorted(set(candidates[0]) | set(candidates[1])):
        a, b = candidates[0].get(key, []), candidates[1].get(key, [])
        if a and b:
            emit("suggested" if len(a) == len(b) == 1 else "ambiguous", a, b, ["Numbers become similar only after removing punctuation. This is a suggestion, not an exact match."])
        else:
            for d in a+b:
                status = "incomplete" if d.issues else "books_only" if a else "portal_only"
                emit(status, [d] if a else [], [d] if b else [], d.issues.copy() or ["No counterpart found in the selected source files. This does not establish supplier non-filing or ITC eligibility."])
    rows.sort(key=lambda r: (r["status"] == "exact", r["status"], (r["books"] or r["portal"])[0]["supplier_gstin"], (r["books"] or r["portal"])[0]["number"], r["id"]))
    counts = {s: sum(r["status"] == s for r in rows) for s in sorted({r["status"] for r in rows})}
    totals = {}
    for label, docs in (("books", books), ("portal", portal)):
        totals[label] = {h: {"paise": sum(d.sign * d.amounts[h] for d in docs if d.amounts[h] is not None), "unknown": sum(d.amounts[h] is None for d in docs)} for h in HEADS}
    assigned = [d["id"] for r in rows for side in ("books", "portal") for d in r[side]]
    expected = [d.id for d in books+portal]
    if len(set(expected)) != len(expected) or sorted(assigned) != sorted(expected):
        raise ValueError("Internal conservation failure: a source document was lost or consumed twice")
    return {"engine_version": ENGINE_VERSION, "rows": rows, "counts": counts, "attention_count": sum(r["needs_attention"] for r in rows), "totals": totals,
            "coverage": {"book_documents": len(books), "portal_documents": len(portal), "assigned_documents": len(assigned), "conserved": True},
            "notice": "Reconciliation diagnostic only. ITC eligibility and return filing are not assessed."}
