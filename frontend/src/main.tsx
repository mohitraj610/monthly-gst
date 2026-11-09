import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowDownToLine,
  ArrowRight,
  Check,
  CheckCheck,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  FileCheck2,
  FileSpreadsheet,
  Files,
  History,
  Leaf,
  LoaderCircle,
  LockKeyhole,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Upload,
  X,
  AlertTriangle,
  ScanLine,
  MessageCircle,
} from "lucide-react";
import "./style.css";
import { GuidePanel } from "./Guide";
import { FilingReview } from "./FilingReview";
import type { FilingSheet } from "./FilingReview";
import { explainRow } from "./guidance";
import type { GuideAction, GuideContext } from "./guidance";

type Workspace = { id: string; name: string; gstin: string; period: string };
type Doc = {
  id: string;
  side: string;
  source_name: string;
  refs: string[];
  supplier_gstin: string;
  number: string;
  date: string;
  kind: string;
  itc: string;
  values: Record<string, string | null>;
  issues: string[];
  raw: Record<string, unknown>[];
};
type Row = {
  id: string;
  status: string;
  books: Doc[];
  portal: Doc[];
  differences: { field: string; books: unknown; portal: unknown }[];
  reasons: string[];
  review: { note: string; actor: string; created: string } | null;
};
type Source = {
  id: string;
  name: string;
  role: string;
  document_count: number;
  hash: string;
  issues: { section: string; reason: string }[];
  state: string;
  already_imported?: boolean;
  preview?: Doc[];
  coverage: Record<string, unknown>;
};
type Run = {
  id: string;
  created: string;
  stale: boolean;
  workspace: Workspace;
  rows: Row[];
  row_count: number;
  filtered_count: number;
  attention_count: number;
  counts: Record<string, number>;
  source_issues: { source_name: string; section: string; reason: string }[];
  source_coverage: { books_present: boolean; portal_present: boolean };
  coverage: {
    book_documents: number;
    portal_documents: number;
    conserved: boolean;
  };
  summary: Record<string, { tax: string; unknown_tax_amounts: number }>;
};
type Inspection = {
  headers: string[];
  sheets: string[];
  sheet: string;
  mapping: Record<string, string>;
  sample: { row: number; cells: Record<string, unknown> }[];
  input_rows: number;
};
const labels: Record<string, string> = {
  exact: "Exact match",
  tax_head_difference: "Tax heads differ",
  amount_difference: "Amount differs",
  metadata_difference: "Details differ",
  duplicate: "Duplicate records",
  suggested: "Possible match",
  ambiguous: "Ambiguous match",
  books_only: "Register only",
  portal_only: "2B only",
  incomplete: "Incomplete data",
};
const fields: Record<string, string> = {
  supplier_gstin: "Supplier GSTIN",
  number: "Supplier invoice / note number",
  date: "Invoice / note date",
  kind: "Document kind",
  taxable: "Taxable value",
  igst: "IGST amount",
  cgst: "CGST amount",
  sgst: "SGST / UTGST amount",
  cess: "Cess amount",
  total: "Invoice value",
  pos: "Place of supply code",
  rcm: "Reverse charge",
};
const heads = ["taxable", "igst", "cgst", "sgst", "cess", "total"];
let session = "";
async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (session) headers.set("X-Session", session);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch("/api" + path, { ...init, headers });
  if (!response.ok) {
    const data = await response.json().catch(() => ({
      detail:
        "The request could not be completed. Reload if your session has expired.",
    }));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  }
  return response.json();
}
function rupees(value: string | null | undefined) {
  if (value == null) return "Unknown";
  const [whole, fraction = "00"] = value.split(".");
  const sign = whole.startsWith("-") ? "-" : "";
  const n = whole.replace("-", "");
  const tail = n.slice(-3);
  const leading = n.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
  return `${sign}₹${leading ? leading + "," : ""}${tail}.${fraction.padEnd(2, "0")}`;
}
function previousMonth() {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
function month(period: string) {
  return new Date(period + "-02T12:00:00").toLocaleDateString("en-IN", {
    month: "long",
    year: "numeric",
  });
}
function Status({ status }: { status: string }) {
  return (
    <span className={`status ${status}`}>
      <span className="status-dot" />
      {labels[status] || status}
    </span>
  );
}
function Busy({ label = "Working…" }: { label?: string }) {
  return (
    <span className="busy">
      <LoaderCircle size={16} className="spin" />
      {label}
    </span>
  );
}
async function download(path: string, name: string) {
  const response = await fetch("/api" + path, {
    headers: { "X-Session": session },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(
      typeof data?.detail === "string"
        ? data.detail
        : "Could not prepare the download. Try again.",
    );
  }
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function App() {
  const [filing, setFiling] = useState<{ run: Run; sheet: FilingSheet } | null>(
    null,
  );
  const filingDirty = useRef(false);
  const [showGuide, setShowGuide] = useState(false);
  const [guidedRowId, setGuidedRowId] = useState("");
  const [guidePhase, setGuidePhase] = useState<GuideContext["phase"]>();
  const [showSources, setShowSources] = useState(false);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]),
    [active, setActive] = useState<Workspace | null>(null),
    [sources, setSources] = useState<Source[]>([]);
  const [run, setRun] = useState<Run | null>(null),
    [runId, setRunId] = useState(""),
    [status, setStatus] = useState("all"),
    [query, setQuery] = useState(""),
    [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [creating, setCreating] = useState(false),
    [importRole, setImportRole] = useState(""),
    [detail, setDetail] = useState<Row | null>(null),
    [history, setHistory] = useState<
      { id: string; created: string; stale: boolean }[]
    >([]),
    [showHistory, setShowHistory] = useState(false),
    [showHelp, setShowHelp] = useState(false);
  const sourcePanel = useRef<HTMLDivElement>(null);
  const refreshWorkspaces = async () =>
    setWorkspaces(await api<Workspace[]>("/workspaces"));
  async function selectWorkspace(w: Workspace) {
    setActive(w);
    setRun(null);
    setRunId("");
    setPage(0);
    setStatus("all");
    setQuery("");
    setDetail(null);
    const state = await api<
      Workspace & { sources: Source[]; history: typeof history }
    >("/workspaces/" + w.id);
    setSources(state.sources);
    setHistory(state.history);
    if (state.history[0]) setRunId(state.history[0].id);
    localStorage.setItem("monthly-gst-workspace", w.id);
  }
  useEffect(() => {
    (async () => {
      try {
        session = (await api<{ token: string }>("/bootstrap")).token;
        const ws = await api<Workspace[]>("/workspaces");
        setWorkspaces(ws);
        const last = localStorage.getItem("monthly-gst-workspace");
        const w = ws.find((x) => x.id === last) || ws[0];
        if (w) await selectWorkspace(w);
      } catch (e) {
        setError(String(e instanceof Error ? e.message : e));
      } finally {
        setLoading(false);
      }
    })();
  }, []);
  useEffect(() => {
    let live = true;
    if (runId) {
      api<Run>(
        `/runs/${runId}?status=${encodeURIComponent(status)}&q=${encodeURIComponent(query)}&offset=${page * 50}&limit=50`,
      )
        .then((r) => {
          if (live) setRun(r);
        })
        .catch((e) => {
          if (live) setError(e.message);
        });
    }
    return () => {
      live = false;
    };
  }, [runId, status, query, page]);
  async function action(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }
  async function demo() {
    await action("Preparing demo", async () => {
      const data = await api<{ workspace: Workspace; run_id: string }>(
        "/demo",
        { method: "POST" },
      );
      await refreshWorkspaces();
      await selectWorkspace(data.workspace);
      setRunId(data.run_id);
      setNotice(
        "Fictional data loaded. These records deliberately include duplicates and mismatches.",
      );
    });
  }
  async function reconcile() {
    if (!active) return;
    await action("Reconciling", async () => {
      const r = await api<Run>(`/workspaces/${active.id}/reconcile`, {
        method: "POST",
      });
      setPage(0);
      setStatus("all");
      setQuery("");
      setRunId(r.id);
      setRun(await api<Run>(`/runs/${r.id}?limit=50`));
      const w = await api<{ history: typeof history }>(
        "/workspaces/" + active.id,
      );
      setHistory(w.history);
    });
  }
  async function afterImport() {
    if (!active) return;
    const state = await api<{ sources: Source[]; history: typeof history }>(
      "/workspaces/" + active.id,
    );
    setSources(state.sources);
    setHistory(state.history);
    setImportRole("");
    if (runId) setRun(await api<Run>(`/runs/${runId}?limit=50`));
    setNotice(
      "Source saved with its original file and row references. Run reconciliation to use the new inputs.",
    );
  }
  const exceptions = run ? run.attention_count : 0;
  const sample =
    active?.name === "Demo · fictional business" &&
    sources.length > 0 &&
    sources.every((s) => s.name.startsWith("synthetic-"));
  const guideContext: GuideContext = {
    workspace: !!active,
    hasBooks: sources.some((s) => s.role === "books"),
    hasPortal: sources.some((s) => s.role === "portal"),
    hasRun: !!run,
    stale: run?.stale,
    sample,
    phase: guidePhase,
  };
  async function openGuidedRecord(number?: string) {
    if (!run) return;
    const result = await api<Run>(
      `/runs/${run.id}?limit=200&${number ? `q=${encodeURIComponent(number)}` : `status=${run.attention_count ? "attention" : "all"}`}`,
    );
    const record = number
      ? result.rows.find((r) =>
          [...r.books, ...r.portal].some((d) => d.number === number),
        )
      : result.rows[0];
    if (!record)
      throw new Error(
        "That sample record is not in the selected run. Open a fresh sample to continue.",
      );
    setShowGuide(false);
    setGuidedRowId(record.id);
    setDetail(record);
  }
  function guideAction(actionName: GuideAction) {
    if (actionName === "record") {
      void action("Opening record", () =>
        openGuidedRecord(sample ? "INV-1002" : undefined),
      );
      return;
    }
    if (actionName === "next" && detail) {
      const number = (detail.books[0] || detail.portal[0]).number;
      if (number === "INV-1009") {
        setDetail(null);
        setGuidePhase("export");
        setShowGuide(true);
        return;
      }
      void action("Opening next example", () =>
        openGuidedRecord(number === "INV-1002" ? "INV-1003" : "INV-1009"),
      );
      return;
    }
    if (actionName === "export" && run && active) {
      void action("Exporting", () =>
        download(
          `/runs/${run.id}/download/zip`,
          `Monthly-GST-${active.period}-evidence.zip`,
        ),
      );
      return;
    }
    setShowGuide(false);
    if (actionName === "sample") void demo();
    if (actionName === "create") setCreating(true);
    if (actionName === "books" || actionName === "portal")
      setImportRole(actionName);
    if (actionName === "reconcile") {
      setDetail(null);
      void reconcile();
    }
  }
  const allCount = run
    ? Object.values(run.counts).reduce((a, b) => a + b, 0)
    : 0;
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setStatus("all");
            setShowHistory(false);
          }}
        >
          <span className="brand-icon">
            <Leaf size={22} />
          </span>
          <span>
            monthly<span className="brand-sub">GST WORKSPACE</span>
          </span>
        </a>
        <div className="sidebar-label">
          YOUR WORKSPACE <span>ALPHA</span>
        </div>
        <button
          className="nav-item active"
          onClick={() => {
            setShowHistory(false);
            setStatus("all");
          }}
        >
          <ScanLine size={18} />
          Reconciliation
          <span className="nav-marker" />
        </button>
        <button className="nav-item" onClick={() => setShowSources(true)}>
          <Files size={18} />
          Source files
          {sources.length > 0 && (
            <span className="nav-count">{sources.length}</span>
          )}
        </button>
        <button className="nav-item" onClick={() => setShowHistory(true)}>
          <History size={18} />
          Run history
        </button>
        <div className="sidebar-divider" />
        <div className="sidebar-label">BUSINESSES</div>
        <div className="workspace-list">
          {workspaces.map((w) => (
            <button
              key={w.id}
              className={`workspace-link ${active?.id === w.id ? "selected" : ""}`}
              onClick={() => action("Loading", () => selectWorkspace(w))}
            >
              <span className="business-avatar">{w.name.slice(0, 1)}</span>
              <span>
                {w.name}
                <small>{w.period}</small>
              </span>
            </button>
          ))}
        </div>
        <button
          className="nav-item add-business"
          onClick={() => setCreating(true)}
        >
          <Plus size={17} />
          New business & month
        </button>
        <div className="sidebar-bottom">
          <div className="privacy-card">
            <ShieldCheck size={20} />
            <strong>Your books stay here.</strong>
            <p>
              Local processing. No account.
              <br />
              No financial data sent to a cloud.
            </p>
            <span>
              <i /> RUNNING ON THIS COMPUTER
            </span>
          </div>
          <button
            className="nav-item help-link"
            onClick={() => {
              setGuidePhase(undefined);
              setShowGuide(true);
            }}
          >
            <CircleHelp size={17} />
            Guide me
          </button>
          <small className="version">Monthly GST · 0.2.0 preview</small>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <ChevronRight size={14} />
            <strong>Purchase reconciliation</strong>
          </div>
          <span className="local-pill">
            <LockKeyhole size={13} />
            Local & private
          </span>
        </header>
        <div className="content">
          {error && (
            <div role="alert" className="alert error">
              <AlertTriangle size={18} />
              <span>{error}</span>
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div role="status" className="alert success">
              <Check size={18} />
              <span>{notice}</span>
              <button aria-label="Dismiss notice" onClick={() => setNotice("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {loading ? (
            <div className="empty">
              <Busy label="Opening your local workspace…" />
            </div>
          ) : !active ? (
            <div className="welcome">
              <span className="eyebrow">A CLEARER MONTH-END</span>
              <h1>
                Every invoice accounted for.
                <br />
                <em>Every difference explained.</em>
              </h1>
              <p>
                Bring your purchase register and GSTR-2B together.
                <br />
                Review the exceptions, keep the evidence, and move forward.
              </p>
              <div className="welcome-actions">
                <button
                  className="button primary"
                  onClick={() => setCreating(true)}
                >
                  Start your month <ArrowRight size={17} />
                </button>
                <button
                  className="button secondary"
                  disabled={!!busy}
                  onClick={demo}
                >
                  {busy ? (
                    <Busy label={busy} />
                  ) : (
                    <>
                      Explore sample data <FileSpreadsheet size={17} />
                    </>
                  )}
                </button>
              </div>
              <div className="welcome-features">
                <span>
                  <CheckCheck />
                  Compare every tax head
                </span>
                <span>
                  <Files />
                  Keep every source row
                </span>
                <span>
                  <LockKeyhole />
                  Work entirely offline
                </span>
              </div>
              <div className="welcome-note">
                Compare your purchases, then prepare a review workbook for
                filing.
              </div>
            </div>
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <span className="eyebrow">MONTHLY REVIEW</span>
                  <h1>Purchase reconciliation</h1>
                  <p>A complete trail from your register to GSTR-2B.</p>
                </div>
                <div className="heading-actions">
                  <button
                    className="button secondary"
                    onClick={() => setImportRole("books")}
                  >
                    <Upload size={16} />
                    Import files
                  </button>
                  <button
                    className="button primary"
                    disabled={!!busy || !sources.length}
                    onClick={reconcile}
                  >
                    {busy ? (
                      <Busy label={busy} />
                    ) : (
                      <>
                        <RefreshCw size={16} />
                        Reconcile
                      </>
                    )}
                  </button>
                </div>
              </div>
              <div className="business-bar">
                <span className="business-avatar large">
                  {active.name.slice(0, 1)}
                </span>
                <div>
                  <strong>{active.name}</strong>
                  <small>{active.gstin}</small>
                </div>
                <div className="period-pill">
                  <span className="mini-calendar">
                    {active.period.slice(5)}
                  </span>
                  {month(active.period)}
                </div>
                <span className="diagnostic-label">FILING PREPARATION</span>
              </div>
              <div className="source-panel" ref={sourcePanel}>
                <div className="source-panel-title">
                  <Files size={16} />
                  <strong>Your source files</strong>
                  <span>Originals and row references are preserved</span>
                </div>
                <div className="source-slots">
                  {(["books", "portal"] as const).map((role) => {
                    const selected = sources.filter((s) => s.role === role);
                    return (
                      <button
                        className={`source-slot ${selected.length ? "loaded" : ""}`}
                        key={role}
                        onClick={() => setImportRole(role)}
                      >
                        <span className={`file-icon ${role}`}>
                          <FileSpreadsheet size={21} />
                        </span>
                        <div>
                          <strong>
                            {role === "books"
                              ? "Purchase register"
                              : "GSTR-2B statement"}
                          </strong>
                          <small>
                            {selected.length
                              ? selected.map((s) => s.name).join(", ")
                              : role === "books"
                                ? "Import CSV or Excel from your books"
                                : "Import JSON downloaded from the GST portal"}
                          </small>
                        </div>
                        <span className="source-slot-end">
                          {selected.length ? (
                            <>
                              <Check size={15} />
                              {selected.reduce(
                                (a, s) => a + s.document_count,
                                0,
                              )}{" "}
                              records
                            </>
                          ) : (
                            <>
                              <Plus size={15} />
                              Add file
                            </>
                          )}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
              {run ? (
                <>
                  {run.stale && (
                    <div className="alert warning">
                      <AlertTriangle size={18} />
                      <span>
                        <strong>Source files changed.</strong> These results
                        belong to an earlier version. Reconcile again to review
                        the current inputs.
                      </span>
                    </div>
                  )}
                  {(!run.source_coverage.books_present ||
                    !run.source_coverage.portal_present) && (
                    <div className="alert warning">
                      <AlertTriangle size={18} />
                      <span>
                        One side is missing. Add both a purchase register and a
                        complete 2B file before drawing conclusions.
                      </span>
                    </div>
                  )}
                  {!!run.source_issues.length && (
                    <div className="alert warning">
                      <AlertTriangle size={18} />
                      <span>
                        <strong>
                          {run.source_issues.length} unsupported or incomplete
                          sections.
                        </strong>{" "}
                        Original data is retained. This run does not cover a
                        complete statement.
                        <details>
                          <summary>See sections</summary>
                          {run.source_issues.map((s, i) => (
                            <p key={i}>
                              {s.source_name} · {s.section}: {s.reason}
                            </p>
                          ))}
                        </details>
                      </span>
                    </div>
                  )}
                  <div className="metrics">
                    <div className="metric">
                      <span>
                        Register documents <FileSpreadsheet size={16} />
                      </span>
                      <strong>{run.coverage.book_documents}</strong>
                      <small>
                        {rupees(run.summary.books.tax)} recorded tax
                        {run.summary.books.unknown_tax_amounts
                          ? " · some amounts unknown"
                          : ""}
                      </small>
                    </div>
                    <div className="metric">
                      <span>
                        GSTR-2B documents <FileCheck2 size={16} />
                      </span>
                      <strong>{run.coverage.portal_documents}</strong>
                      <small>
                        {rupees(run.summary.portal.tax)} reported tax
                        {run.summary.portal.unknown_tax_amounts
                          ? " · some amounts unknown"
                          : ""}
                      </small>
                    </div>
                    <button
                      className="metric matched"
                      onClick={() => {
                        setStatus("exact");
                        setPage(0);
                      }}
                    >
                      <span>
                        Exact matches <CheckCheck size={17} />
                      </span>
                      <strong>{run.counts.exact || 0}</strong>
                      <small>Identity, amounts & tax heads agree</small>
                    </button>
                    <button
                      className="metric attention"
                      onClick={() => {
                        setStatus("attention");
                        setPage(0);
                      }}
                    >
                      <span>
                        Needs attention <AlertTriangle size={16} />
                      </span>
                      <strong>{exceptions}</strong>
                      <small>Differences, duplicates & portal ITC flags</small>
                    </button>
                  </div>
                  {run.source_coverage.books_present &&
                    run.source_coverage.portal_present && (
                      <div className="filing-entry">
                        <div>
                          <strong>Prepare your monthly filing review</strong>
                          <p>
                            Check the portal figures against your reviewed Table
                            4 and keep the source evidence together.
                          </p>
                        </div>
                        <button
                          className="button secondary"
                          disabled={!!busy}
                          onClick={() =>
                            void action("Opening filing review", async () => {
                              const sheet = await api<FilingSheet>(
                                `/runs/${run.id}/filing`,
                              );
                              filingDirty.current = false;
                              setFiling({ run, sheet });
                            })
                          }
                        >
                          <FileCheck2 size={16} /> Filing review
                        </button>
                      </div>
                    )}
                  <section className="results-panel">
                    <div className="results-title">
                      <div>
                        <h2>
                          Review your records <span>{allCount}</span>
                        </h2>
                        <p>
                          Start with the exceptions. Open a row to see exactly
                          why it was flagged.
                        </p>
                      </div>
                      <button
                        className="button secondary export"
                        disabled={!!busy}
                        onClick={() =>
                          action("Exporting", () =>
                            download(
                              `/runs/${run.id}/download/zip`,
                              `Monthly-GST-${active.period}-evidence.zip`,
                            ),
                          )
                        }
                      >
                        <ArrowDownToLine size={16} />
                        Export evidence
                      </button>
                    </div>
                    <div className="table-toolbar">
                      <div className="filter-tabs">
                        {[
                          ["all", "All records", allCount],
                          ["attention", "Needs attention", exceptions],
                          ["exact", "Exact matches", run.counts.exact || 0],
                        ].map(([key, label, count]) => (
                          <button
                            key={String(key)}
                            className={status === key ? "selected" : ""}
                            onClick={() => {
                              setStatus(String(key));
                              setPage(0);
                            }}
                          >
                            {label}
                            <span>{count}</span>
                          </button>
                        ))}
                      </div>
                      <div className="search">
                        <Search size={15} />
                        <input
                          aria-label="Search records"
                          placeholder="Invoice number or GSTIN"
                          value={query}
                          onChange={(e) => {
                            setQuery(e.target.value);
                            setPage(0);
                          }}
                        />
                      </div>
                      <label className="status-filter">
                        <SlidersHorizontal size={15} />
                        <select
                          aria-label="Filter result status"
                          value={status}
                          onChange={(e) => {
                            setStatus(e.target.value);
                            setPage(0);
                          }}
                        >
                          <option value="all">All statuses</option>
                          <option value="attention">Needs attention</option>
                          {Object.entries(labels).map(([key, label]) => (
                            <option key={key} value={key}>
                              {label}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <div className="table-scroll">
                      <table className="results-table">
                        <thead>
                          <tr>
                            <th>DOCUMENT / SUPPLIER</th>
                            <th>INVOICE DATE</th>
                            <th className="numeric">REGISTER VALUE</th>
                            <th className="numeric">2B VALUE</th>
                            <th>RESULT</th>
                            <th>
                              <span className="sr-only">Open record</span>
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {run.rows.map((row) => {
                            const d = row.books[0] || row.portal[0];
                            return (
                              <tr key={row.id} onClick={() => setDetail(row)}>
                                <td>
                                  <button
                                    className="row-button"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setDetail(row);
                                    }}
                                  >
                                    <span
                                      className={`doc-icon ${row.status === "exact" ? "ok" : ""}`}
                                    >
                                      <FileSpreadsheet size={16} />
                                    </span>
                                    <span>
                                      <strong>
                                        {d.number || "Missing document number"}
                                        {d.kind === "CN" && <em>CN</em>}
                                        {row.review && (
                                          <Check
                                            size={12}
                                            className="reviewed-check"
                                          />
                                        )}
                                      </strong>
                                      <small>
                                        {d.supplier_gstin ||
                                          "Missing supplier GSTIN"}
                                      </small>
                                    </span>
                                  </button>
                                </td>
                                <td>{d.date || "Unknown"}</td>
                                <td className="numeric">
                                  {row.books.length > 1 ? (
                                    <span className="multiple">
                                      {row.books.length} records
                                    </span>
                                  ) : row.books[0] ? (
                                    rupees(row.books[0].values.total)
                                  ) : (
                                    <span className="dash">—</span>
                                  )}
                                </td>
                                <td className="numeric">
                                  {row.portal.length > 1 ? (
                                    <span className="multiple">
                                      {row.portal.length} records
                                    </span>
                                  ) : row.portal[0] ? (
                                    rupees(row.portal[0].values.total)
                                  ) : (
                                    <span className="dash">—</span>
                                  )}
                                </td>
                                <td>
                                  <Status status={row.status} />
                                  {row.portal.some((d) => d.itc === "N") && (
                                    <small className="itc-warning">
                                      2B: ITC unavailable
                                    </small>
                                  )}
                                </td>
                                <td>
                                  <ChevronRight size={15} />
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                      {!run.rows.length && (
                        <div className="empty compact">
                          <Search size={25} />
                          <h3>No records in this view</h3>
                          <p>Try another status or search term.</p>
                          <button
                            className="text-button"
                            onClick={() => {
                              setStatus("all");
                              setQuery("");
                              setPage(0);
                            }}
                          >
                            Clear filters
                          </button>
                        </div>
                      )}
                    </div>
                    <div className="table-footer">
                      <span>
                        <ShieldCheck size={14} />
                        {run.coverage.conserved
                          ? "Every parsed document is accounted for"
                          : "Check source coverage"}
                        <span className="footer-separator">·</span>Credit notes
                        reduce source totals
                      </span>
                      <div>
                        <span>
                          {run.filtered_count
                            ? `${page * 50 + 1}–${Math.min((page + 1) * 50, run.filtered_count)}`
                            : "0"}{" "}
                          of {run.filtered_count}
                        </span>
                        <button
                          aria-label="Previous page"
                          disabled={!page}
                          onClick={() => setPage(page - 1)}
                        >
                          <ChevronLeft size={16} />
                        </button>
                        <button
                          aria-label="Next page"
                          disabled={(page + 1) * 50 >= run.filtered_count}
                          onClick={() => setPage(page + 1)}
                        >
                          <ChevronRight size={16} />
                        </button>
                      </div>
                    </div>
                  </section>
                  <div className="bottom-note">
                    <CircleHelp size={15} />
                    <span>
                      Needs attention also includes matching invoices with
                      unavailable or unknown portal ITC flags. An exact match
                      confirms agreement between files. It does not establish
                      ITC eligibility or that a return has been filed.
                    </span>
                    <button
                      onClick={() =>
                        action("Exporting", () =>
                          download(
                            `/runs/${run.id}/download/xlsx`,
                            `Monthly-GST-${active.period}-reconciliation.xlsx`,
                          ),
                        )
                      }
                    >
                      Download workbook <ArrowRight size={14} />
                    </button>
                  </div>
                </>
              ) : (
                <div className="empty getting-started">
                  <ScanLine size={32} />
                  <h2>Ready when your records are.</h2>
                  <p>
                    Add your purchase register and GSTR-2B, then select
                    Reconcile.
                    <br />
                    We’ll show every difference without changing your books.
                  </p>
                  <button
                    className="button secondary"
                    disabled={!!busy}
                    onClick={demo}
                  >
                    Try a fictional example <ArrowRight size={16} />
                  </button>
                </div>
              )}
            </>
          )}
          <footer className="page-footer">
            <span>
              <Leaf size={13} />
              Built for a more explainable month-end.
            </span>
            <span>Offline by design · No automated ITC claims</span>
          </footer>
        </div>
      </main>
      {creating && (
        <NewWorkspace
          close={() => setCreating(false)}
          created={async (w) => {
            setCreating(false);
            await refreshWorkspaces();
            await selectWorkspace(w);
          }}
        />
      )}
      {importRole && active && (
        <ImportDialog
          role={importRole}
          workspace={active}
          close={() => setImportRole("")}
          done={afterImport}
        />
      )}
      {filing && (
        <Modal
          title="Monthly filing review"
          wide
          close={() => {
            if (
              !filingDirty.current ||
              window.confirm("Close without saving your worksheet changes?")
            )
              setFiling(null);
          }}
        >
          <FilingReview
            initial={filing.sheet}
            period={month(filing.run.workspace.period)}
            gstin={filing.run.workspace.gstin}
            locked={filing.run.stale}
            attention={filing.run.attention_count}
            coverageIssues={filing.run.source_issues.length}
            onDirty={(dirty) => {
              filingDirty.current = dirty;
            }}
            save={(draft) =>
              api<FilingSheet>(`/runs/${filing.run.id}/filing`, {
                method: "PUT",
                body: JSON.stringify(draft),
              })
            }
            download={(revision) =>
              download(
                `/runs/${filing.run.id}/filing/download?revision=${revision}`,
                `Monthly-GST-${filing.run.workspace.period}-filing-review.zip`,
              )
            }
          />
        </Modal>
      )}
      {detail && run && (
        <DetailDrawer
          key={detail.id}
          row={detail}
          sample={sample}
          startGuide={guidedRowId === detail.id}
          onGuideAction={guideAction}
          run={run}
          close={() => {
            setDetail(null);
            setGuidedRowId("");
          }}
          saved={async () => {
            const r = await api<Run>(
              `/runs/${run.id}?status=${status}&q=${encodeURIComponent(query)}&offset=${page * 50}&limit=50`,
            );
            setRun(r);
            setDetail(r.rows.find((x) => x.id === detail.id) || null);
          }}
        />
      )}
      {showSources && active && (
        <Modal
          title="Source files for this month"
          close={() => setShowSources(false)}
          wide
        >
          <p className="muted">
            These files feed the next reconciliation. Excluding a file preserves
            its original bytes and all earlier runs. Reimport the same file and
            mapping to restore it.
          </p>
          {sources.length ? (
            sources.map((src) => (
              <div className="source-manage" key={src.id}>
                <div>
                  <strong>{src.name}</strong>
                  <p>
                    {src.role === "books" ? "Purchase register" : "GSTR-2B"} ·{" "}
                    {src.document_count} records
                  </p>
                  <small>SHA-256: {src.hash}</small>
                </div>
                <button
                  className="button secondary"
                  disabled={!!busy}
                  onClick={() =>
                    action("Excluding source", async () => {
                      await api(
                        `/workspaces/${active.id}/imports/${src.id}/exclude`,
                        { method: "POST" },
                      );
                      await afterImport();
                      setNotice(
                        "Source excluded from future runs. Earlier results and original evidence are preserved.",
                      );
                    })
                  }
                >
                  Exclude from next run
                </button>
              </div>
            ))
          ) : (
            <p>No source files selected.</p>
          )}
          <div className="modal-actions">
            <button
              className="button secondary"
              onClick={() => {
                setShowSources(false);
                setImportRole("books");
              }}
            >
              Import another file
            </button>
            <button
              className="button primary"
              onClick={() => setShowSources(false)}
            >
              Done
            </button>
          </div>
        </Modal>
      )}
      {showHistory && (
        <Modal
          title="Reconciliation history"
          close={() => setShowHistory(false)}
        >
          <p className="muted">
            Each run retains the source versions it used. New inputs never
            rewrite old results.
          </p>
          {!history.length ? (
            <p>No reconciliation runs yet.</p>
          ) : (
            history.map((h) => (
              <button
                key={h.id}
                className="history-item"
                onClick={() => {
                  setRunId(h.id);
                  setPage(0);
                  setStatus("all");
                  setQuery("");
                  setShowHistory(false);
                }}
              >
                <History size={19} />
                <span>
                  <strong>{new Date(h.created).toLocaleString("en-IN")}</strong>
                  <small>
                    {h.stale
                      ? "Earlier source version"
                      : "Current source version"}{" "}
                    · {h.id.slice(0, 8)}
                  </small>
                </span>
                <ChevronRight size={17} />
              </button>
            ))
          )}
        </Modal>
      )}
      {showGuide && (
        <Modal title="Your monthly guide" close={() => setShowGuide(false)}>
          <GuidePanel context={guideContext} onAction={guideAction} />
          <button
            className="text-button guide-manual"
            onClick={() => {
              setShowGuide(false);
              setShowHelp(true);
            }}
          >
            Read the full workflow instructions
          </button>
        </Modal>
      )}
      {showHelp && (
        <Modal
          title="One careful reconciliation at a time"
          close={() => setShowHelp(false)}
        >
          <div className="help-content">
            <p>1. Create a workspace for one GSTIN and month.</p>
            <p>
              2. Import a purchase register with invoice values and each tax
              head. CSV and XLSX are supported. Review the mapping and row
              granularity.
            </p>
            <p>
              3. Download the complete GSTR-2B JSON for the same GSTIN and month
              from the GST portal. Import it here.
            </p>
            <p>
              4. Reconcile. Inspect duplicates, missing records and differences.
              Record review notes; amounts and statuses stay unchanged.
            </p>
            <p>
              5. Export a workbook or evidence bundle for your accountant. This
              alpha does not assess eligible ITC or prepare upload-ready
              returns.
            </p>
            <div className="alert warning">
              Tally layouts vary. Use a values-only export with supplier invoice
              numbers, dates, GSTINs and separate tax amounts. Universal Tally
              compatibility has not been established.
            </div>
            <button
              className="button secondary"
              onClick={() =>
                download("/demo/files/books", "synthetic-purchases.csv")
              }
            >
              Download example register
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function Modal({
  title,
  close,
  children,
  wide = false,
}: {
  title: string;
  close: () => void;
  children: React.ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement;
    ref.current?.focus();
    function key(e: KeyboardEvent) {
      if (e.key === "Escape") close();
      if (e.key === "Tab") {
        const f = Array.from(
          ref.current?.querySelectorAll<HTMLElement>(
            'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]',
          ) || [],
        ).filter((element) => element.getClientRects().length > 0);
        if (!f?.length) return;
        const first = f[0],
          last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    }
    document.addEventListener("keydown", key);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow = overflow;
      before?.focus();
    };
  }, []);
  return (
    <div className="modal-backdrop" onClick={close}>
      <div
        ref={ref}
        tabIndex={-1}
        className={`modal ${wide ? "wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <header>
          <h2>{title}</h2>
          <button
            className="icon-button"
            aria-label="Close dialog"
            onClick={close}
          >
            <X size={20} />
          </button>
        </header>
        {children}
      </div>
    </div>
  );
}
function NewWorkspace({
  close,
  created,
}: {
  close: () => void;
  created: (w: Workspace) => Promise<void>;
}) {
  const [name, setName] = useState(""),
    [gstin, setGstin] = useState(""),
    [period, setPeriod] = useState(previousMonth),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <Modal title="Start a monthly workspace" close={close}>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setError("");
          setBusy(true);
          try {
            await created(
              await api<Workspace>("/workspaces", {
                method: "POST",
                body: JSON.stringify({ name, gstin, period }),
              }),
            );
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <p className="muted">
          One business GSTIN. One month. All source records stay on this
          computer.
        </p>
        {error && (
          <div role="alert" className="alert error">
            {error}
          </div>
        )}
        <label className="field">
          Business name
          <input
            required
            maxLength={100}
            placeholder="e.g. Mehta Trading"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="field">
          Business GSTIN
          <input
            required
            minLength={15}
            maxLength={15}
            placeholder="15-character GSTIN"
            value={gstin}
            onChange={(e) => setGstin(e.target.value.toUpperCase())}
          />
          <small>
            Format and checksum are checked locally. Registration status is not
            checked online.
          </small>
        </label>
        <label className="field">
          Tax month
          <input
            required
            type="month"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
          />
        </label>
        <div className="modal-actions">
          <button type="button" className="button secondary" onClick={close}>
            Cancel
          </button>
          <button className="button primary" disabled={busy}>
            {busy ? (
              <Busy />
            ) : (
              <>
                Create workspace <ArrowRight size={16} />
              </>
            )}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function ImportDialog({
  role: initialRole,
  workspace,
  close,
  done,
}: {
  role: string;
  workspace: Workspace;
  close: () => void;
  done: () => Promise<void>;
}) {
  const [guideOpen, setGuideOpen] = useState(false);
  const [role, setRole] = useState(initialRole),
    [file, setFile] = useState<File | null>(null),
    [inspection, setInspection] = useState<Inspection | null>(null),
    [mapping, setMapping] = useState<Record<string, string>>({}),
    [sheet, setSheet] = useState(""),
    [header, setHeader] = useState(1),
    [granularity, setGranularity] = useState("invoice"),
    [order, setOrder] = useState("DMY"),
    [preview, setPreview] = useState<Source | null>(null),
    [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function inspect(f: File, selected = sheet, row = header) {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", f);
      form.append("header_row", String(row));
      if (selected) form.append("sheet", selected);
      const data = await api<Inspection>("/inspect", {
        method: "POST",
        body: form,
      });
      setInspection(data);
      setMapping(data.mapping);
      setSheet(data.sheet);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function prepare() {
    if (!file) return;
    setError("");
    setBusy(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("role", role);
      form.append(
        "options",
        JSON.stringify(
          role === "books"
            ? {
                mapping,
                sheet,
                header_row: header,
                granularity,
                date_order: order,
              }
            : {},
        ),
      );
      setPreview(
        await api<Source>(`/workspaces/${workspace.id}/imports/preview`, {
          method: "POST",
          body: form,
        }),
      );
      setConfirmed(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={preview ? "Check your import" : "Bring in your source files"}
      close={close}
      wide
    >
      <div className="import-context">
        <span>{workspace.gstin}</span>
        <span>{month(workspace.period)}</span>
      </div>
      <button
        type="button"
        className="text-button import-guide-toggle"
        onClick={() => setGuideOpen(!guideOpen)}
        aria-expanded={guideOpen}
      >
        <MessageCircle size={15} />
        {guideOpen ? "Hide import guide" : "Guide me through this import"}
      </button>
      {guideOpen && (
        <GuidePanel
          key={`${role}-${!!preview}`}
          context={{
            phase: preview
              ? "preview"
              : role === "books"
                ? "import-books"
                : "import-portal",
          }}
          onClose={() => setGuideOpen(false)}
        />
      )}
      {error && (
        <div role="alert" className="alert error">
          {error}
        </div>
      )}
      {!preview ? (
        <>
          <div className="role-toggle">
            <button
              className={role === "books" ? "selected" : ""}
              onClick={() => {
                setRole("books");
                setFile(null);
                setInspection(null);
                setError("");
              }}
            >
              <FileSpreadsheet size={17} />
              Purchase register
            </button>
            <button
              className={role === "portal" ? "selected" : ""}
              onClick={() => {
                setRole("portal");
                setFile(null);
                setInspection(null);
                setError("");
              }}
            >
              <FileCheck2 size={17} />
              GSTR-2B JSON
            </button>
          </div>
          <label className="upload-area">
            <Upload size={27} />
            <strong>
              {file ? file.name : "Choose a file from your computer"}
            </strong>
            <span>
              {role === "books"
                ? "CSV or values-only XLSX · up to 20 MB"
                : "Complete GST portal JSON · same GSTIN and month"}
            </span>
            <input
              aria-label="Source file"
              type="file"
              accept={role === "books" ? ".csv,.xlsx" : ".json"}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) {
                  setFile(f);
                  setInspection(null);
                  setSheet("");
                  if (role === "books") inspect(f, "", header);
                }
              }}
            />
          </label>
          {role === "books" && file && (
            <>
              <div className="import-options">
                <label className="field">
                  Header row
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={header}
                    onChange={(e) => setHeader(Number(e.target.value))}
                  />
                </label>
                {inspection && (
                  <label className="field">
                    Sheet
                    <select
                      value={sheet}
                      onChange={(e) => {
                        setSheet(e.target.value);
                        inspect(file, e.target.value, header);
                      }}
                    >
                      {inspection.sheets.map((s) => (
                        <option key={s}>{s}</option>
                      ))}
                    </select>
                  </label>
                )}
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => inspect(file, sheet, header)}
                >
                  Read header
                </button>
              </div>
              {inspection && (
                <>
                  <div className="mapping-title">
                    <h3>Confirm the column mapping</h3>
                    <p>
                      Tax amounts are preserved. Missing values are never
                      silently treated as zero. Check every mapping below.
                    </p>
                  </div>
                  <div className="mapping-grid">
                    {Object.entries(fields).map(([key, label]) => (
                      <label className="field" key={key}>
                        {label}
                        <select
                          value={mapping[key] || ""}
                          onChange={(e) =>
                            setMapping({ ...mapping, [key]: e.target.value })
                          }
                        >
                          <option value="">Not mapped · remains unknown</option>
                          {inspection.headers.map((h) => (
                            <option key={h} value={h}>
                              {h}
                            </option>
                          ))}
                          {heads.includes(key) && (
                            <option value="__zero__">
                              Explicitly declare zero for every row
                            </option>
                          )}
                          {key === "rcm" && (
                            <option value="__no__">
                              Explicitly declare No for every row
                            </option>
                          )}
                          {key === "kind" && (
                            <option value="__invoice__">
                              All rows are ordinary invoices
                            </option>
                          )}
                        </select>
                      </label>
                    ))}
                  </div>
                  <div className="import-options">
                    <label className="field">
                      Row granularity
                      <select
                        value={granularity}
                        onChange={(e) => setGranularity(e.target.value)}
                      >
                        <option value="invoice">One invoice per row</option>
                        <option value="line">
                          One item per row · invoice total repeated
                        </option>
                      </select>
                    </label>
                    <label className="field">
                      Numeric date order
                      <select
                        value={order}
                        onChange={(e) => setOrder(e.target.value)}
                      >
                        <option value="DMY">Day / month / year</option>
                        <option value="MDY">Month / day / year</option>
                      </select>
                    </label>
                  </div>
                  <details className="raw-preview">
                    <summary>
                      Source preview · {inspection.input_rows} rows under header
                    </summary>
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            {inspection.headers.map((h) => (
                              <th key={h}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {inspection.sample.map((r) => (
                            <tr key={r.row}>
                              {inspection.headers.map((h) => (
                                <td key={h}>
                                  {JSON.stringify(r.cells[h] ?? "")}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </details>
                </>
              )}
            </>
          )}
          <div className="modal-actions">
            <button className="button secondary" onClick={close}>
              Cancel
            </button>
            <button
              className="button primary"
              disabled={busy || !file || (role === "books" && !inspection)}
              onClick={prepare}
            >
              {busy ? (
                <Busy label="Reading source…" />
              ) : (
                <>
                  Preview import <ArrowRight size={16} />
                </>
              )}
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="preview-heading">
            <span className="file-icon books">
              <FileSpreadsheet size={24} />
            </span>
            <div>
              <strong>{preview.name}</strong>
              <p>
                {preview.document_count} document records · original file
                preserved
              </p>
            </div>
          </div>
          {preview.already_imported && (
            <div className="alert success">
              <Check size={17} />
              This exact file and mapping are already imported. It will not be
              counted twice.
            </div>
          )}
          {!!preview.issues.length && (
            <div className="alert warning">
              <AlertTriangle size={18} />
              <span>
                Unsupported sections will remain visible and this statement will
                be incomplete.
                {preview.issues.map((x, i) => (
                  <p key={i}>
                    {x.section}: {x.reason}
                  </p>
                ))}
              </span>
            </div>
          )}
          {!!preview.preview?.some((d) => d.issues.length) && (
            <div className="alert warning">
              <AlertTriangle size={18} />
              Some records need correction. They will be retained as incomplete
              records, not dropped.
            </div>
          )}
          <div className="preview-docs">
            {preview.preview?.map((d) => (
              <div key={d.id}>
                <div>
                  <strong>{d.number || "Missing document number"}</strong>
                  <small>
                    {d.supplier_gstin} · {d.date || "Unknown date"} · {d.kind}
                  </small>
                </div>
                <span>{rupees(d.values.total)}</span>
                {d.issues.length > 0 && (
                  <p className="issue-list">{d.issues.join(" · ")}</p>
                )}
              </div>
            ))}
          </div>
          <label className="confirm-check">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            <span>
              I checked the file, date interpretation and row granularity.{" "}
              {role === "portal"
                ? "This is the complete 2B download, not one part of a multi-file statement. Importing it replaces the selected 2B revision."
                : "This file contains the purchase records I intend to reconcile, including relevant notes and prior-period entries."}
            </span>
          </label>
          <div className="modal-actions">
            <button
              className="button secondary"
              onClick={() => setPreview(null)}
            >
              Back to mapping
            </button>
            <button
              className="button primary"
              disabled={busy || !confirmed}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  await api(
                    `/workspaces/${workspace.id}/imports/${preview.id}/commit`,
                    {
                      method: "POST",
                      body: JSON.stringify({ coverage_confirmed: confirmed }),
                    },
                  );
                  await done();
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? (
                <Busy label="Saving…" />
              ) : (
                <>
                  Save source <Check size={16} />
                </>
              )}
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}

function DetailDrawer({
  row,
  run,
  close,
  saved,
  sample,
  onGuideAction,
  startGuide,
}: {
  row: Row;
  run: Run;
  close: () => void;
  saved: () => Promise<void>;
  sample: boolean;
  onGuideAction: (action: GuideAction) => void;
  startGuide: boolean;
}) {
  const [allFields, setAllFields] = useState(false);
  const [guideOpen, setGuideOpen] = useState(startGuide);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const sourceRef = useRef<HTMLDetailsElement>(null);
  const reviewRef = useRef<HTMLDetailsElement>(null);
  const [actor, setActor] = useState(row.review?.actor || ""),
    [note, setNote] = useState(row.review?.note || ""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const first = (row.books || [])[0] || row.portal[0];
  const explanation = explainRow(row);
  const differences = row.differences.map((d) => d.field);
  const comparisonFields = allFields
    ? [...heads, "date", "pos", "rcm"]
    : differences;
  function openReview() {
    setReviewOpen(true);
    requestAnimationFrame(() =>
      reviewRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  }
  function localGuideAction(action: GuideAction) {
    if (action === "note") {
      openReview();
      return;
    }
    if (action === "sources") {
      setSourcesOpen(true);
      requestAnimationFrame(() =>
        sourceRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        }),
      );
      return;
    }
    onGuideAction(action);
  }
  return (
    <Modal title={first.number || "Record detail"} close={close} wide>
      <div className="detail-top">
        <Status status={row.status} />
        <span className="muted">{first.supplier_gstin}</span>
      </div>
      <div className="result-meaning">
        <h3>{explanation.title}</h3>
        <p>{explanation.detail}</p>
        {row.books.length === 1 &&
          row.portal.length === 1 &&
          row.books[0].values.total != null &&
          row.books[0].values.total === row.portal[0].values.total && (
            <p className="same-total">
              Both files show an invoice total of{" "}
              <strong>{rupees(row.books[0].values.total)}</strong>.
            </p>
          )}
        <p className="unchanged-note">{explanation.unchanged}</p>
      </div>
      {row.portal.some((d) => d.itc !== "Y") && (
        <div className="alert warning">
          {row.portal.some((d) => d.itc === "N")
            ? "The portal marks ITC unavailable for at least one entry."
            : "The portal ITC flag is unknown for at least one entry."}{" "}
          A matching invoice is not an approval to claim credit.
        </div>
      )}
      <div className="next-check">
        <strong>Your next check</strong>
        <p>
          {run.stale
            ? "These inputs changed. Reconcile again before recording a review."
            : explanation.next}
        </p>
        <button
          className="text-button"
          onClick={() => setGuideOpen(!guideOpen)}
          aria-expanded={guideOpen}
        >
          <MessageCircle size={15} />
          {guideOpen ? "Hide guide" : "Help me understand"}
        </button>
      </div>
      {guideOpen && (
        <GuidePanel
          context={{ row, stale: run.stale, sample }}
          onAction={localGuideAction}
          onClose={() => setGuideOpen(false)}
        />
      )}
      {row.status === "incomplete" && (
        <div className="alert warning">
          {[...new Set([...row.books, ...row.portal].flatMap((d) => d.issues))]
            .slice(0, 5)
            .join(" · ")}
        </div>
      )}
      {row.books.length === 1 && row.portal.length === 1 && (
        <div className="comparison-heading">
          <strong>
            {allFields
              ? "All compared fields"
              : differences.length
                ? "What differs"
                : "No differences in compared fields"}
          </strong>
          <button
            className="text-button"
            aria-expanded={allFields}
            onClick={() => setAllFields(!allFields)}
          >
            {allFields ? "Show differences only" : "Show all compared fields"}
          </button>
        </div>
      )}
      {row.books.length === 1 &&
        row.portal.length === 1 &&
        comparisonFields.length > 0 && (
          <table className="comparison">
            <thead>
              <tr>
                <th>AMOUNT / DETAIL</th>
                <th className="numeric">YOUR BOOKS</th>
                <th className="numeric">PORTAL FILE (2B)</th>
              </tr>
            </thead>
            <tbody>
              {comparisonFields.map((h) => {
                const diff = row.differences.some((d) => d.field === h);
                function show(d: Doc) {
                  const value = (d as unknown as Record<string, unknown>)[h];
                  return heads.includes(h)
                    ? rupees(d.values[h])
                    : typeof value === "boolean"
                      ? value
                        ? "Yes"
                        : "No"
                      : String(value ?? "Unknown");
                }
                return (
                  <tr key={h} className={diff ? "different" : ""}>
                    <td>
                      {fields[h] || h}
                      {diff && <span>Different</span>}
                    </td>
                    <td className="numeric">{show(row.books[0])}</td>
                    <td className="numeric">{show(row.portal[0])}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      <details
        className="evidence-disclosure"
        open={sourcesOpen}
        onToggle={(e) => setSourcesOpen(e.currentTarget.open)}
        ref={sourceRef}
      >
        <summary>
          {row.books.length === 1 && row.portal.length === 1
            ? "See the two original records"
            : `See all ${row.books.length + row.portal.length} original entries`}
        </summary>
        <p className="evidence-intro">
          {row.books.length === 1 && row.portal.length === 1
            ? "Two copies of the same invoice: one from your purchase file, one from the portal file. These are not two extra bills. File names and row references show where each copy came from."
            : `${row.books.length} entries from your books and ${row.portal.length} from the portal file. Each source entry is preserved separately so you can inspect why they repeat.`}
        </p>
        <div className="source-detail-grid">
          {[...row.books, ...row.portal].map((d) => (
            <article className="source-detail" key={d.id}>
              <span className="eyebrow">
                {d.side === "books"
                  ? "FROM YOUR PURCHASE FILE"
                  : "FROM THE PORTAL FILE (2B)"}
              </span>
              <strong>
                {d.number || "Unknown number"} <span>{d.kind}</span>
              </strong>
              <p>
                {d.date || "Unknown date"} · {rupees(d.values.total)}
              </p>
              <small>{d.source_name}</small>
              <small>{d.refs.join(", ")}</small>
              {d.side === "portal" && (
                <span
                  className={
                    d.itc === "N" ? "itc-badge unavailable" : "itc-badge"
                  }
                >
                  Portal ITC flag: {d.itc} · eligibility not assessed
                </span>
              )}
              {d.issues.map((s, i) => (
                <p className="issue-list" key={i}>
                  {s}
                </p>
              ))}
              <details>
                <summary>View original row values</summary>
                <pre>{JSON.stringify(d.raw, null, 2)}</pre>
              </details>
            </article>
          ))}
        </div>
      </details>
      <details
        className="review-disclosure"
        open={reviewOpen}
        onToggle={(e) => setReviewOpen(e.currentTarget.open)}
        ref={reviewRef}
      >
        <summary>
          {row.review ? "View or add a review note" : "Add a review note"}
        </summary>
        <div className="review-section">
          <p>
            This records your investigation. It does not change amounts,
            matching status or claim eligibility.
          </p>
          {row.review && (
            <div className="saved-review">
              <Check size={15} />
              Last recorded by {row.review.actor} ·{" "}
              {new Date(row.review.created).toLocaleString("en-IN")}
            </div>
          )}
          {error && (
            <div className="alert error" role="alert">
              {error}
            </div>
          )}
          <label className="field">
            Your name
            <input
              value={actor}
              onChange={(e) => setActor(e.target.value)}
              placeholder="Reviewer name"
              maxLength={80}
            />
          </label>
          <label className="field">
            Review note
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="What did you check? What needs to happen next?"
              rows={3}
              maxLength={2000}
            />
          </label>
          <div className="modal-actions">
            <button className="button secondary" onClick={close}>
              Close
            </button>
            <button
              className="button primary"
              disabled={
                busy ||
                run.stale ||
                actor.trim().length < 3 ||
                note.trim().length < 8
              }
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  await api(`/runs/${run.id}/rows/${row.id}/review`, {
                    method: "POST",
                    body: JSON.stringify({ actor, note }),
                  });
                  await saved();
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? (
                <Busy label="Saving…" />
              ) : (
                <>
                  Save review note <Check size={16} />
                </>
              )}
            </button>
          </div>
          {run.stale && (
            <p className="issue-list">
              Inputs changed. Reconcile again before recording a new review.
            </p>
          )}
        </div>
      </details>
    </Modal>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
