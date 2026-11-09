# Monthly GST · filing preparation preview

A local Windows workspace for comparing a purchase register with GSTR-2B and preparing a monthly GST review pack. It keeps invoice differences, GSTR-3B Table 4 working figures and original evidence together for the business and its accountant.

**Version 0.2 is a filing preparation preview for regular monthly returns.** Check the results against original invoices and the GST Portal before relying on them for a return. The preview has been tested on fictional data. Validation against real Tally and portal exports and independent accountant review are pending.

## Get started on Windows

Extract the Windows release ZIP into a folder you can write to. Install Python 3.12 or newer with Python on PATH, then run **`Setup.cmd`** with internet access to install the pinned dependencies. The release ZIP includes the built interface. A Git source checkout also needs Node.js 24 with npm for setup.

Open **`Start Monthly GST.cmd`** and visit **http://127.0.0.1:8765**. Select **Explore sample data**. The app works offline after setup. Keep the terminal open during use and press Ctrl+C to stop it. [Try the fictional sample](docs/FIRST-TEST.md)

Developer commands in PowerShell:

```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m monthly_gst.cli
```

To use a different port or storage folder, pass `--port 8766 --data-dir .local/other-business-data`.

## What works

- One GSTIN and calendar month per workspace, with local format/checksum validation.
- Purchase-register CSV and values-only XLSX; header/sheet selection, explicit mapping, day-first/month-first dates, invoice rows or item rows with repeated invoice totals.
- GSTR-2B JSON with `docdata.b2b` invoices and `docdata.cdnr` credit/debit notes, including a `data` wrapper. Receiver GSTIN and statement period must agree with the workspace. An empty 2B can be imported.
- Separate comparison of taxable value, IGST, CGST, SGST/UTGST, cess, invoice total, invoice date, place of supply and reverse-charge flag.
- Exact matches, tax/amount/detail differences, duplicate groups, punctuation suggestions, ambiguous suggestions, records present on only one side, and incomplete records.
- Financial-year and document-kind separation, one-to-one conservation, signed credit-note totals, unknown amounts retained as unknown.
- Review notes without overwriting machine results. Unavailable/unknown portal ITC flags stay in **Needs attention**, even where amounts match.
- Original source bytes and row/JSON references, transactional imports, idempotent exact reimports, changed-mapping revisions, reversible source exclusion, immutable financial snapshots and stale-input warnings.
- Search, filters, run history, CSV, six-sheet XLSX and an evidence ZIP containing original inputs, JSON results, mapping settings and SHA-256 checksums. Identical exports of an unchanged run are byte-identical.

Monetary comparisons use integer paise. The UI displays decimal strings produced by the backend.

## Prepare a filing review

1. Reconcile your purchase register and GSTR-2B for the selected GSTIN and month. Investigate differences, duplicates and coverage exceptions against the original files.
2. Open **Filing review**. Work through the monthly checklist for GSTR-1 sales, GSTR-3B credit, liability and payment, and the filing acknowledgement.
3. Enter Table 4 figures from your portal draft and your reviewed records. Enter confirmed zero amounts explicitly and leave pending amounts blank. Add notes explaining changes and save the worksheet.
4. Open **Compare saved figures**. The worksheet shows differences by tax head and calculates 4(C) when the corresponding 4(A) and 4(B) amounts are complete. It keeps 4(D) disclosures separate from that arithmetic. [CBIC guidance on Table 4](https://cbic-gst.gov.in/pdf/Circular-170-02-2022-GST.pdf)
5. Select **Export filing review**. The ZIP contains the Excel working papers, saved worksheet, reconciliation and original inputs with a checksum manifest. The worksheet belongs to the saved reconciliation run. Changing source files makes the earlier worksheet read-only.

Your accountant or authorised signatory checks eligibility and tax liability, prepares the sales and return figures, and completes payment and submission on the GST Portal. [GST Portal](https://www.gst.gov.in/)

## Built-in guide

Select **Guide me** in the sidebar, **Help me understand** inside a record, or the import guide during file selection. The guide explains actual comparison values, the two source copies and what to check next. Its sample buttons walk through a difference, duplicate, ITC flag and export. The initial invoice view shows only differing fields; original records, all fields and review notes expand on request.

This is prepared local guidance with supported typed questions, not general-purpose AI. Unsupported questions are acknowledged. Questions remain in component memory while the guide is open; no model service receives them. The guide never edits financial fields or decides which file is legally correct.

## Import contract and limits

All amounts must be authoritative **INR amounts**, not tax rates. The application does not reconstruct tax from a rate or guess rounding adjustments. Keep credit-note amounts positive and declare the document kind explicitly; source totals apply the negative sign. Negative amounts require correction or a deliberate future adapter.

Required identity mappings: supplier GSTIN, supplier invoice/note number and invoice date. Other missing fields stay unknown; zero or reverse-charge No must be supplied by the source or explicitly declared. Numeric state codes or labels such as `29-Karnataka` are supported. Bare state names are not inferred. Excel formula cells require a values-only export; formulas are never evaluated.

Invoice rows remain separate, including duplicates. In item-row mode, amounts are summed by supplier, financial year, document kind and number; repeated invoice totals are counted once. Conflicting dates/metadata/totals create incomplete records. Only choose this mode after inspecting the file.

Limits: 20 MB per file, 50,000 data rows/documents per source, 100 columns, header rows 1–50. XLS/XLSM/XLSB, PDFs, CSV delimiters other than comma, vendor-specific Tally XML and arbitrary workbook layouts are not supported. Tally exports require the correct supplier invoice fields and explicit mapping; universal Tally compatibility is not claimed.

Only one **complete** 2B statement is selected per workspace. A new 2B replaces the earlier selected revision. Split downloads need to be handled separately. Unsupported sections such as amendments, imports and ISD appear as coverage exceptions and remain in the source evidence. The worksheet takes reviewed figures from the business and its accountant, including any amounts the purchase reconciliation cannot cover.

## Evidence and local data

SQLite stores source bytes, parsed versions, runs and append-only review notes in one transaction boundary. Default storage is `.local/workspace.sqlite`; development preview data uses `.local/preview/workspace.sqlite`. These folders are Git-ignored. Excluding a source moves it out of the active selection; reimporting the same file with the same settings restores it. Previously superseded revisions remain in historical evidence.

The process binds to `127.0.0.1`; it checks Host/Origin and uses a per-launch session token. There is no cloud upload, analytics, GST portal login or paid model API in this build. SQLite is not encrypted: normal Windows file permissions protect it. Stop the app before copying its SQLite file for a backup; keep financial evidence ZIPs private. Backup/restore UI, encrypted storage and signed distribution are future work.

## Verification

```powershell
New-Item -ItemType Directory -Force .local | Out-Null
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.local/test-run
npm --prefix frontend test
npm --prefix frontend run build
```

Use a dedicated temporary path for `--basetemp` because pytest clears that path.

The suite covers exact paise arithmetic, duplicate groups, file coverage, SQLite persistence, stale results, source evidence, local session and origin restrictions, and worksheet calculation, versioning and export. See the release notes for the preview scope and validation still needed. [Release notes](docs/RELEASE.md)

MIT licensed.
