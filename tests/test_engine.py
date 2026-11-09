from copy import deepcopy

import pytest
from hypothesis import given, settings, strategies as st

from monthly_gst.domain import HEADS, TAX_HEADS, formatted, money, parse_date, reconcile, valid_gstin
from conftest import document


@pytest.mark.parametrize("raw,expected", [("0", 0), ("0.01", 1), ("₹1,23,456.78", 12345678), ("Rs. 1,234.50", 123450), ("12.000", 1200)])
def test_exact_money(raw, expected):
    assert money(raw) == expected


@pytest.mark.parametrize("raw", [None, "", True, "NaN", "Infinity", "1e3", "-1", "1.001", "1,23", "=1+1", "9" * 30])
def test_money_never_invents_or_rounds(raw):
    with pytest.raises(ValueError):
        money(raw)


@given(st.integers(min_value=0, max_value=99_999_999_999_999))
def test_paise_round_trip(p):
    assert money(formatted(p)) == p


def test_known_gstin_and_date_order():
    assert valid_gstin("27ABCDE1234F1Z0")
    assert not valid_gstin("27ABCDE1234F1ZA")
    assert parse_date("01/02/2026", "DMY") == "2026-02-01"
    assert parse_date("01/02/2026", "MDY") == "2026-01-02"


def test_control_and_itc_unavailable_are_separate():
    result = reconcile([document()], [document("p1", "portal", itc="N")])
    row = result["rows"][0]
    assert row["status"] == "exact"
    assert row["itc"] == "NOT_ASSESSED"
    assert any("unavailable" in reason for reason in row["reasons"])
    assert row["needs_attention"]
    assert result["attention_count"] == 1


def test_equal_tax_sum_cannot_hide_wrong_heads():
    portal = document("p1", "portal")
    portal.amounts.update(igst=0, cgst=9000, sgst=9000)
    row = reconcile([document()], [portal])["rows"][0]
    assert row["status"] == "tax_head_difference"
    assert {d["field"] for d in row["differences"]} == {"igst", "cgst", "sgst"}


@pytest.mark.parametrize("head", HEADS)
def test_one_paisa_difference_is_never_exact(head):
    portal = document("p1", "portal")
    portal.amounts[head] += 1
    row = reconcile([document()], [portal])["rows"][0]
    assert row["status"] != "exact"
    assert next(d for d in row["differences"] if d["field"] == head)["delta_paise"] == 1


@pytest.mark.parametrize("field,value", [("date", "2026-10-02"), ("pos", "27"), ("rcm", True)])
def test_metadata_disagreement(field, value):
    row = reconcile([document()], [document("p1", "portal", **{field: value})])["rows"][0]
    assert row["status"] == "metadata_difference"


def test_missing_head_is_not_zero():
    portal = document("p1", "portal")
    portal.amounts["cess"] = None
    row = reconcile([document()], [portal])["rows"][0]
    assert row["status"] == "incomplete"


@pytest.mark.parametrize("b,p", [(2, 1), (1, 2), (2, 2), (3, 0)])
def test_duplicates_conserve_every_document(b, p):
    result = reconcile([document(f"b{i}") for i in range(b)], [document(f"p{i}", "portal") for i in range(p)])
    assert result["counts"] == {"duplicate": 1}
    assert result["coverage"]["assigned_documents"] == b+p
    assert len(result["rows"][0]["books"]) == b
    assert len(result["rows"][0]["portal"]) == p


def test_year_and_document_kind_do_not_collide():
    result = reconcile([document(), document("old", date="2025-10-01"), document("cn", kind="CN")], [document("p1", "portal")])
    assert result["counts"] == {"books_only": 2, "exact": 1}


def test_punctuation_is_suggestion_leading_zeros_are_not_removed():
    assert reconcile([document()], [document("p1", "portal", number="INV-001")])["counts"] == {"suggested": 1}
    assert reconcile([document()], [document("p1", "portal", number="INV/1")])["counts"] == {"books_only": 1, "portal_only": 1}


def test_ambiguous_suggestions_are_never_linked():
    result = reconcile([document(number="INV/001"), document("b2", number="INV.001")], [document("p1", "portal", number="INV-001")])
    assert result["counts"] == {"ambiguous": 1}
    assert result["coverage"]["assigned_documents"] == 3


def test_credit_notes_subtract_debit_notes_add():
    result = reconcile([document(kind="CN"), document("dn", kind="DN"), document("inv")], [])
    assert result["totals"]["books"]["igst"] == {"paise": 18000, "unknown": 0}


@given(st.lists(st.integers(min_value=0, max_value=40), max_size=120), st.lists(st.integers(min_value=0, max_value=40), max_size=120))
@settings(max_examples=100)
def test_arbitrary_duplicates_never_lose_or_reuse_inputs(a, b):
    books = [document(f"b{i}", number=f"I/{n}") for i, n in enumerate(a)]
    portal = [document(f"p{i}", "portal", number=f"I-{n}" if i % 2 else f"I/{n}") for i, n in enumerate(b)]
    before = deepcopy(books + portal)
    result = reconcile(books, portal)
    assert books + portal == before
    assert result["coverage"]["assigned_documents"] == len(a)+len(b)
    assert result["totals"]["books"]["total"]["paise"] == len(a) * 118000
    reverse = reconcile(list(reversed(books)), list(reversed(portal)))
    assert reverse == result
