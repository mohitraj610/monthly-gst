"""All source bytes, versions and runs share one atomic SQLite database."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .domain import ENGINE_VERSION, TAX_HEADS, document_from_dict, formatted, reconcile, stable_hash, valid_gstin
from .filing import normalize_filing, worksheet
from .imports import PARSER_VERSION, inspect_table, parse_2b, parse_books


def now():
    return datetime.now(timezone.utc).isoformat()


class Conflict(ValueError):
    pass


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY, name TEXT NOT NULL, gstin TEXT NOT NULL, period TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS files(hash TEXT PRIMARY KEY, content BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), role TEXT NOT NULL,
              name TEXT NOT NULL, hash TEXT NOT NULL REFERENCES files(hash), options TEXT NOT NULL, parsed TEXT NOT NULL,
              state TEXT NOT NULL CHECK(state IN ('staged','active','superseded')), created TEXT NOT NULL,
              UNIQUE(workspace_id,role,hash,options));
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), fingerprint TEXT NOT NULL,
              result TEXT NOT NULL, source_ids TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), row_id TEXT NOT NULL,
              actor TEXT NOT NULL, note TEXT NOT NULL, created TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS filing_reviews(run_id TEXT PRIMARY KEY REFERENCES runs(id), revision INTEGER NOT NULL,
              data TEXT NOT NULL, updated TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS source_workspace ON sources(workspace_id,state);
            CREATE INDEX IF NOT EXISTS run_workspace ON runs(workspace_id,created);
            PRAGMA user_version=2;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def create_workspace(self, name: str, gstin: str, period: str):
        from datetime import date
        gstin = gstin.strip().upper()
        if not valid_gstin(gstin):
            raise ValueError("GSTIN fails format/checksum validation. Verify the 15-character number.")
        try:
            date.fromisoformat(period + "-01")
            if len(period) != 7:
                raise ValueError()
        except ValueError as exc:
            raise ValueError("Choose one calendar month in YYYY-MM format") from exc
        if not name.strip() or len(name) > 100:
            raise ValueError("Business name must contain 1–100 characters")
        data = {"id": uuid.uuid4().hex, "name": name.strip(), "gstin": gstin, "period": period, "created": now()}
        with self.connect() as db:
            db.execute("INSERT INTO workspaces VALUES(:id,:name,:gstin,:period,:created)", data)
        return data

    def workspace(self, wid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM workspaces WHERE id=?", (wid,)).fetchone()
            if not row:
                raise KeyError("Workspace not found")
            return dict(row)

    def list_workspaces(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM workspaces ORDER BY created DESC")]

    def preview(self, wid, role, name, content, options):
        workspace = self.workspace(wid)
        name = re.sub(r'[\x00-\x1f\x7f<>:"|?*]', '_', Path(name.replace('\\', '/')).name)[:200]
        if role not in {"books", "portal"}:
            raise ValueError("Choose purchase register or GSTR-2B")
        digest = hashlib.sha256(content).hexdigest()
        encoded_options = json.dumps({**options, "_parser_version": PARSER_VERSION}, sort_keys=True)
        sid = stable_hash([wid, role, digest, encoded_options, PARSER_VERSION])[:32]
        with self.connect() as db:
            existing = db.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
            if existing:
                return self.source_public(existing, include_docs=True) | {"already_imported": existing["state"] == "active"}
        if role == "portal":
            parsed = parse_2b(content, sid, name, workspace["gstin"], workspace["period"])
        else:
            table = inspect_table(content, name, options.get("sheet"), int(options.get("header_row", 1)))
            parsed = parse_books(table, sid, name, options)
        parsed["parser_version"] = PARSER_VERSION
        if role == "books" and not parsed["documents"] and not parsed["issues"]:
            raise ValueError("No document records found. Check the selected sheet and header row.")
        record = {"id": sid, "workspace_id": wid, "role": role, "name": Path(name).name[:200], "hash": digest,
                  "options": encoded_options, "parsed": json.dumps(parsed, ensure_ascii=False), "state": "staged", "created": now()}
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO files VALUES(?,?)", (digest, content))
            db.execute("INSERT OR IGNORE INTO sources VALUES(:id,:workspace_id,:role,:name,:hash,:options,:parsed,:state,:created)", record)
        return self.source_public(record, include_docs=True)

    @staticmethod
    def source_public(row, include_docs=False):
        result = {k: row[k] for k in ("id", "workspace_id", "role", "name", "hash", "state", "created")}
        parsed = json.loads(row["parsed"])
        result["parser_version"] = parsed.get("parser_version", "unversioned-development")
        result.update({"document_count": len(parsed["documents"]), "issues": parsed["issues"], "coverage": parsed["coverage"], "options": json.loads(row["options"])})
        if include_docs:
            result["preview"] = [document_from_dict(d).public() for d in parsed["documents"][:10]]
        return result

    def sources(self, wid):
        self.workspace(wid)
        with self.connect() as db:
            return [self.source_public(r) for r in db.execute("SELECT * FROM sources WHERE workspace_id=? AND state='active' ORDER BY created,id", (wid,))]

    def commit(self, wid, sid, confirmed):
        if not confirmed:
            raise ValueError("Confirm the source-file coverage and row granularity after inspecting the preview")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM sources WHERE id=? AND workspace_id=?", (sid, wid)).fetchone()
            if not row:
                raise KeyError("Preview does not belong to this workspace")
            if row["state"] == "active":
                return self.source_public(row)
            if row["state"] == "superseded":
                raise Conflict("This preview is superseded. Prepare a new preview from the current source.")
            # Same bytes with a changed mapping are an explicit revision, not a second copy.
            if row["role"] == "portal":
                db.execute("UPDATE sources SET state='superseded' WHERE workspace_id=? AND role='portal' AND state='active'", (wid,))
            else:
                db.execute("UPDATE sources SET state='superseded' WHERE workspace_id=? AND role='books' AND hash=? AND state='active'", (wid, row["hash"]))
            db.execute("UPDATE sources SET state='active' WHERE id=?", (sid,))
            return self.source_public(dict(row) | {"state": "active"})

    def fingerprint(self, db, wid):
        rows = db.execute("SELECT id FROM sources WHERE workspace_id=? AND state='active' ORDER BY id", (wid,)).fetchall()
        return stable_hash([ENGINE_VERSION, [r["id"] for r in rows]])

    def exclude(self, wid, sid):
        """Reversible by reimport; old runs and original bytes remain intact."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM sources WHERE workspace_id=? AND id=?", (wid, sid)).fetchone()
            if not row:
                raise KeyError("Source does not belong to this workspace")
            if row["state"] == "active":
                db.execute("UPDATE sources SET state='staged' WHERE id=?", (sid,))
        return {"excluded": True}

    def run(self, wid):
        workspace = self.workspace(wid)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            sources = db.execute("SELECT * FROM sources WHERE workspace_id=? AND state='active' ORDER BY id", (wid,)).fetchall()
            if not sources:
                raise ValueError("Import at least one source before reconciling")
            fp = self.fingerprint(db, wid)
            documents = {"books": [], "portal": []}
            source_issues = []
            for src in sources:
                parsed = json.loads(src["parsed"])
                documents[src["role"]].extend(document_from_dict(d) for d in parsed["documents"])
                source_issues.extend({**issue, "source_id": src["id"], "source_name": src["name"]} for issue in parsed["issues"])
            result = reconcile(documents["books"], documents["portal"])
            result["summary"] = {side: {"tax": formatted(sum(d.sign * sum(d.amounts[h] or 0 for h in TAX_HEADS) for d in docs)),
                                         "unknown_tax_amounts": sum(d.amounts[h] is None for d in docs for h in TAX_HEADS)} for side, docs in documents.items()}
            result["workspace"] = workspace
            result["source_issues"] = source_issues
            result["source_coverage"] = {"books_present": any(s["role"] == "books" for s in sources), "portal_present": any(s["role"] == "portal" for s in sources)}
            result["fingerprint"] = fp
            rid = uuid.uuid4().hex
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?)", (rid, wid, fp, json.dumps(result, ensure_ascii=False), json.dumps([s["id"] for s in sources]), now()))
        return self.get_run(rid)

    def history(self, wid):
        with self.connect() as db:
            return [dict(r) | {"stale": r["fingerprint"] != self.fingerprint(db, wid)} for r in db.execute("SELECT id,created,fingerprint FROM runs WHERE workspace_id=? ORDER BY created DESC", (wid,))]

    def get_run(self, rid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
            if not row:
                raise KeyError("Run not found")
            result = json.loads(row["result"])
            # Early local snapshots predate the separate attention indicator.
            for item in result["rows"]:
                item.setdefault("needs_attention", item["status"] != "exact" or any(d["itc"] != "Y" for d in item["portal"]))
            result.setdefault("attention_count", sum(item["needs_attention"] for item in result["rows"]))
            result.update({"id": rid, "created": row["created"], "source_ids": json.loads(row["source_ids"]), "stale": row["fingerprint"] != self.fingerprint(db, row["workspace_id"])})
            reviews = [dict(r) for r in db.execute("SELECT * FROM reviews WHERE run_id=? ORDER BY created,id", (rid,))]
            by_row = {r["row_id"]: r for r in reviews}
            for item in result["rows"]:
                item["review"] = by_row.get(item["id"])
            result["review_events"] = reviews
            return result

    def review(self, rid, row_id, actor, note):
        result = self.get_run(rid)
        if not any(r["id"] == row_id for r in result["rows"]):
            raise KeyError("Result row not found")
        if not 3 <= len(actor.strip()) <= 80 or not 8 <= len(note.strip()) <= 2000:
            raise ValueError("Enter your name (3–80 characters) and a useful note (8–2000 characters)")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if result["fingerprint"] != self.fingerprint(db, result["workspace"]["id"]):
                raise Conflict("Inputs changed. Reconcile again before recording a review.")
            db.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?)", (uuid.uuid4().hex, rid, row_id, actor.strip(), note.strip(), now()))
        return self.get_run(rid)

    def export_sources(self, ids):
        with self.connect() as db:
            result = []
            for sid in ids:
                src = db.execute("SELECT s.*,f.content FROM sources s JOIN files f ON f.hash=s.hash WHERE s.id=?", (sid,)).fetchone()
                if not src:
                    raise KeyError("Source evidence missing")
                if hashlib.sha256(bytes(src["content"])).hexdigest() != src["hash"]:
                    raise ValueError("Source checksum failed. Restore a verified backup before exporting evidence.")
                result.append((self.source_public(src), bytes(src["content"])))
            return result

    def filing_review(self, rid):
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM runs WHERE id=?", (rid,)).fetchone():
                raise KeyError("Run not found")
            saved = db.execute("SELECT * FROM filing_reviews WHERE run_id=?", (rid,)).fetchone()
        return worksheet(json.loads(saved["data"]) | {"revision": saved["revision"], "updated": saved["updated"]} if saved else None)

    def save_filing_review(self, rid, revision, data):
        normalized = normalize_filing(data)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            run = db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
            if not run:
                raise KeyError("Run not found")
            if run["fingerprint"] != self.fingerprint(db, run["workspace_id"]):
                raise Conflict("The inputs changed. Reconcile again to start a worksheet for the current files.")
            coverage = json.loads(run["result"])["source_coverage"]
            if not (coverage["books_present"] and coverage["portal_present"]):
                raise ValueError("Reconcile both the purchase register and GSTR-2B before saving a filing worksheet")
            saved = db.execute("SELECT * FROM filing_reviews WHERE run_id=?", (rid,)).fetchone()
            current_revision = saved["revision"] if saved else 0
            if saved and json.loads(saved["data"]) == normalized:
                return worksheet(normalized | {"revision": current_revision, "updated": saved["updated"]})
            if revision != current_revision:
                raise Conflict("This worksheet changed in another tab. Reopen it to load the saved revision.")
            updated = now()
            db.execute("""INSERT INTO filing_reviews VALUES(?,?,?,?) ON CONFLICT(run_id) DO UPDATE
                       SET revision=excluded.revision, data=excluded.data, updated=excluded.updated""",
                       (rid, current_revision + 1, json.dumps(normalized, ensure_ascii=False), updated))
        return worksheet(normalized | {"revision": current_revision + 1, "updated": updated})
