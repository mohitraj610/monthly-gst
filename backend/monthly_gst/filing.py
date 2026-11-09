"""Table 4 working papers based on values entered by the reviewer."""
from __future__ import annotations

from decimal import Decimal

from .domain import TAX_HEADS, formatted, money


TABLE_ROWS = {
    "4A1": ("4(A)(1)", "Goods imports"),
    "4A2": ("4(A)(2)", "Service imports"),
    "4A3": ("4(A)(3)", "Other inward reverse charge"),
    "4A4": ("4(A)(4)", "Credit from an input service distributor"),
    "4A5": ("4(A)(5)", "Other purchase credit"),
    "4B1": ("4(B)(1)", "Permanent reversals"),
    "4B2": ("4(B)(2)", "Other reversals"),
    "4D1": ("4(D)(1)", "Disclosure of reclaimed credit"),
    "4D2": ("4(D)(2)", "Disclosure of specified ineligible credit"),
}
CHECKS = {
    "sales": ("Check GSTR-1 sales", "Compare the sales register with the portal draft for this GSTIN and month. Review credit/debit notes, tax heads, HSN and document totals before filing GSTR-1.",
              "https://tutorial.gst.gov.in/userguide/returns/Creation_of_Outward_Supplies_Return_in_GSTR-1.htm"),
    "credit": ("Review GSTR-3B credit", "Check the portal’s Table 4 against reviewed records. Consider reversals, reclaims and other eligibility checks with your accountant.",
               "https://cbic-gst.gov.in/pdf/Circular-170-02-2022-GST.pdf"),
    "liability": ("Check the draft and payment", "Review outward tax, reverse charge and any interest or late fee in the GST Portal. Use the portal’s payment and liability offset steps where applicable.",
                  "https://www.gst.gov.in/"),
    "receipt": ("Save your filing acknowledgement", "After the authorised signatory files on the GST Portal, verify the return status and retain the acknowledgement with your records.",
                "https://www.gst.gov.in/"),
}


def filing_values(cells):
    """Keep unknowns blank and preserve signed amounts at paise precision."""
    result = {}
    for key, fields in cells.items():
        if key not in TABLE_ROWS:
            raise ValueError(f"Unknown Table 4 row: {key}")
        for head, raw in fields.items():
            if head not in TAX_HEADS:
                raise ValueError(f"Unknown tax head: {head}")
            raw = raw.strip()
            if not raw:
                continue
            negative = raw.startswith("-")
            try:
                paise = money(raw[1:] if negative else raw)
            except ValueError as exc:
                raise ValueError(f"{TABLE_ROWS[key][0]} {head.upper()}: enter an INR amount with at most two decimal places") from exc
            result.setdefault(key, {})[head] = formatted(-paise if negative else paise)
    return result


def normalize_filing(data):
    if set(data["notes"]) - TABLE_ROWS.keys():
        raise ValueError("Enter notes against a Table 4 row")
    if set(data["checks"]) - CHECKS.keys():
        raise ValueError("Unknown filing checklist item")
    return {
        "portal": filing_values(data["portal"]),
        "reviewed": filing_values(data["reviewed"]),
        "notes": {key: value.strip() for key, value in data["notes"].items() if value.strip()},
        "reviewer": data["reviewer"].strip(),
        "checks": sorted(set(data["checks"])),
    }


def signed_paise(value):
    # This path only receives normalized values and calculated differences.
    return int(Decimal(value) * 100)


def net_credit(values):
    """Table 4(C) is 4(A) less 4(B). Table 4(D) is disclosure."""
    result = {}
    net_rows = [key for key in TABLE_ROWS if not key.startswith("4D")]
    for head in TAX_HEADS:
        amounts = [values.get(key, {}).get(head) for key in net_rows]
        if all(value is not None for value in amounts):
            result[head] = formatted(sum(
                signed_paise(value) * (-1 if key.startswith("4B") else 1)
                for key, value in zip(net_rows, amounts)
            ))
        else:
            result[head] = None
    return result


def worksheet(saved=None):
    data = saved or {"revision": 0, "updated": None, "reviewer": "", "portal": {}, "reviewed": {}, "notes": {}, "checks": []}
    rows = []
    for key, (code, label) in TABLE_ROWS.items():
        portal = data["portal"].get(key, {})
        reviewed = data["reviewed"].get(key, {})
        difference = {
            head: formatted(signed_paise(reviewed[head]) - signed_paise(portal[head]))
            if head in reviewed and head in portal else None
            for head in TAX_HEADS
        }
        rows.append({"id": key, "code": code, "label": label, "difference": difference})
    return {
        **data, "rows": rows, "heads": TAX_HEADS,
        "net": {side: net_credit(data[side]) for side in ("portal", "reviewed")},
        "checklist": [{"id": key, "title": title, "detail": detail, "url": url}
                      for key, (title, detail, url) in CHECKS.items()],
    }
