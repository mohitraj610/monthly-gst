import csv
import io
import json

import pytest

from monthly_gst.demo import demo_files, synthetic_gstin
from monthly_gst.domain import Document, HEADS
from monthly_gst.store import Store


@pytest.fixture
def files():
    return demo_files()


@pytest.fixture
def loaded(tmp_path, files):
    store = Store(tmp_path / "data.sqlite")
    gstin, books, portal = files
    workspace = store.create_workspace("Test business", gstin, "2026-10")
    for role, name, data in (("books", "purchases.csv", books), ("portal", "2b.json", portal)):
        src = store.preview(workspace["id"], role, name, data, {})
        store.commit(workspace["id"], src["id"], True)
    return store, workspace


def document(id="b1", side="books", **changes):
    data = dict(id=id, side=side, source_id=side, source_name=side + ".csv", refs=[id],
                supplier_gstin=synthetic_gstin("27"), number="INV/001", date="2026-10-01", kind="INV",
                amounts=dict(zip(HEADS, (100000, 18000, 0, 0, 0, 118000))), pos="29", rcm=False, itc="Y")
    data.update(changes)
    return Document(**data)


def csv_bytes(rows):
    out = io.StringIO(newline="")
    csv.writer(out).writerows(rows)
    return out.getvalue().encode()


def changed_books(files, change):
    rows = list(csv.reader(io.StringIO(files[1].decode())))
    change(rows)
    return csv_bytes(rows)
