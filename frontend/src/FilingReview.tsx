import { useState } from "react";
import { ArrowDownToLine, Check } from "lucide-react";
import { moneyLabel } from "./guidance";

type AmountGrid = Record<string, Record<string, string>>;
type Totals = Record<string, string | null>;
type Side = "portal" | "reviewed";

export type FilingDraft = {
  revision: number;
  portal: AmountGrid;
  reviewed: AmountGrid;
  notes: Record<string, string>;
  reviewer: string;
  checks: string[];
};

export type FilingSheet = FilingDraft & {
  updated: string | null;
  rows: { id: string; code: string; label: string; difference: Totals }[];
  heads: string[];
  net: Record<Side, Totals>;
  checklist: { id: string; title: string; detail: string; url: string }[];
};

const headName = (head: string) =>
  head === "sgst" ? "SGST / UTGST" : head.toUpperCase();

export function FilingReview({
  initial,
  period,
  gstin,
  locked,
  attention,
  coverageIssues,
  onDirty,
  save,
  download,
}: {
  initial: FilingSheet;
  period: string;
  gstin: string;
  locked: boolean;
  attention: number;
  coverageIssues: number;
  onDirty: (dirty: boolean) => void;
  save: (draft: FilingDraft) => Promise<FilingSheet>;
  download: (revision: number) => Promise<void>;
}) {
  const [saved, setSaved] = useState(initial);
  const [draft, setDraft] = useState<FilingDraft>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const dirty = draft !== saved;

  function edit(changes: Partial<FilingDraft>) {
    setDraft((previous) => ({ ...previous, ...changes }));
    setNotice("");
    onDirty(true);
  }

  async function perform(operation: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await operation();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="filing-review"
      onSubmit={(event) => {
        event.preventDefault();
        if (locked || busy) return;
        const { revision, portal, reviewed, notes, reviewer, checks } = draft;
        void perform(async () => {
          const updated = await save({
            revision,
            portal,
            reviewed,
            notes,
            reviewer,
            checks,
          });
          setSaved(updated);
          setDraft(updated);
          onDirty(false);
          setNotice(`Worksheet saved · revision ${updated.revision}`);
        });
      }}
    >
      <p className="filing-period">
        {period} · {gstin}
      </p>
      <p className="muted">
        Use this working paper alongside your GST Portal draft for a regular
        monthly return. It brings together the figures you enter, review notes
        and invoice evidence.
      </p>
      {locked && (
        <div className="alert warning">
          This worksheet belongs to an earlier set of files. Reconcile the
          current files to start a new worksheet.
        </div>
      )}
      {(attention > 0 || coverageIssues > 0) && (
        <div className="alert warning">
          Reconciliation flagged {attention}{" "}
          {attention === 1 ? "record" : "records"} for attention
          {coverageIssues > 0
            ? ` and ${coverageIssues} coverage ${coverageIssues === 1 ? "exception" : "exceptions"}`
            : ""}
          . Review those items alongside the full portal statement.
        </div>
      )}
      <fieldset disabled={busy || locked} className="filing-fields">
        <details className="filing-section">
          <summary>Monthly filing checklist</summary>
          {saved.checklist.map((item) => (
            <div className="filing-check" key={item.id}>
              <label>
                <input
                  type="checkbox"
                  checked={draft.checks.includes(item.id)}
                  onChange={(event) =>
                    edit({
                      checks: event.target.checked
                        ? [...draft.checks, item.id]
                        : draft.checks.filter((id) => id !== item.id),
                    })
                  }
                />
                <strong>{item.title}</strong>
              </label>
              <p>
                {item.detail}{" "}
                <a href={item.url} target="_blank" rel="noreferrer">
                  Official guidance
                </a>
              </p>
            </div>
          ))}
        </details>
        <p className="muted">
          Enter the amounts from your portal draft and your reviewed records.
          Enter 0 when you have confirmed a zero amount. Leave amounts awaiting
          review blank.
        </p>
        {(["portal", "reviewed"] as const).map((side) => (
          <details className="filing-section" key={side}>
            <summary>
              {side === "portal"
                ? "Enter portal Table 4 figures"
                : "Enter reviewed Table 4 figures"}
            </summary>
            <div className="filing-scroll">
              <table className="filing-table">
                <thead>
                  <tr>
                    <th scope="col">Table 4 row</th>
                    {saved.heads.map((head) => (
                      <th scope="col" key={head}>
                        {headName(head)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {saved.rows.map((row) => (
                    <tr key={row.id}>
                      <th scope="row">
                        <strong>{row.code}</strong> {row.label}
                      </th>
                      {saved.heads.map((head) => (
                        <td key={head}>
                          <input
                            aria-label={`${side === "portal" ? "Portal" : "Reviewed"} ${row.code} ${headName(head)}`}
                            inputMode="decimal"
                            maxLength={40}
                            value={draft[side][row.id]?.[head] ?? ""}
                            onChange={(event) =>
                              edit({
                                [side]: {
                                  ...draft[side],
                                  [row.id]: {
                                    ...draft[side][row.id],
                                    [head]: event.target.value,
                                  },
                                },
                              })
                            }
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        ))}
        <details className="filing-section">
          <summary>Reviewer and notes</summary>
          <label className="field">
            Reviewer name
            <input
              value={draft.reviewer}
              maxLength={80}
              onChange={(event) => edit({ reviewer: event.target.value })}
            />
          </label>
          {saved.rows.map((row) => (
            <label className="field" key={row.id}>
              {row.code} {row.label}
              <input
                value={draft.notes[row.id] ?? ""}
                maxLength={500}
                placeholder="Reason or supporting reference"
                onChange={(event) =>
                  edit({
                    notes: { ...draft.notes, [row.id]: event.target.value },
                  })
                }
              />
            </label>
          ))}
        </details>
      </fieldset>
      {saved.revision > 0 && !dirty && (
        <details className="filing-section">
          <summary>Compare saved figures</summary>
          <p className="muted">
            Differences are reviewed amounts minus portal amounts. Table 4(C)
            uses 4(A) less 4(B) once every amount for that tax head is entered.
          </p>
          <div className="filing-scroll">
            <table className="filing-table">
              <thead>
                <tr>
                  <th scope="col">Saved comparison</th>
                  {saved.heads.map((head) => (
                    <th scope="col" key={head}>
                      {headName(head)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">4(C) from portal figures</th>
                  {saved.heads.map((head) => (
                    <td key={head}>{moneyLabel(saved.net.portal[head])}</td>
                  ))}
                </tr>
                <tr>
                  <th scope="row">4(C) from reviewed figures</th>
                  {saved.heads.map((head) => (
                    <td key={head}>{moneyLabel(saved.net.reviewed[head])}</td>
                  ))}
                </tr>
                {saved.rows
                  .filter((row) =>
                    saved.heads.some((head) => row.difference[head] !== null),
                  )
                  .map((row) => (
                    <tr key={row.id}>
                      <th scope="row">{row.code} difference</th>
                      {saved.heads.map((head) => (
                        <td key={head}>{moneyLabel(row.difference[head])}</td>
                      ))}
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="alert success" role="status">
          {notice}
        </div>
      )}
      <div className="modal-actions">
        {dirty && <small className="muted">Unsaved changes</small>}
        <button
          type="submit"
          className="button secondary"
          disabled={busy || locked || (!dirty && saved.revision > 0)}
        >
          <Check size={16} /> Save worksheet
        </button>
        <button
          type="button"
          className="button primary"
          disabled={busy || dirty || !saved.revision}
          onClick={() => void perform(() => download(saved.revision))}
        >
          <ArrowDownToLine size={16} /> Export filing review
        </button>
      </div>
    </form>
  );
}
