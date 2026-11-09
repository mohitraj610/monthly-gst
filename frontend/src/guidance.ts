/** Local guidance from source facts. No model calls, mutations or tax decisions. */
export type GuideRow = {
  status: string;
  books: {
    number: string;
    values: Record<string, string | null>;
    itc: string;
  }[];
  portal: {
    number: string;
    values: Record<string, string | null>;
    itc: string;
  }[];
  differences: { field: string }[];
};
export type GuideContext = {
  row?: GuideRow;
  workspace?: boolean;
  hasBooks?: boolean;
  hasPortal?: boolean;
  hasRun?: boolean;
  stale?: boolean;
  sample?: boolean;
  phase?: "import-books" | "import-portal" | "preview" | "export";
};
export type GuideAction =
  | "sample"
  | "create"
  | "books"
  | "portal"
  | "reconcile"
  | "record"
  | "export"
  | "note"
  | "sources"
  | "next";
const unchanged =
  "The app has not changed either file or decided which one is correct.";
const inspect =
  "Compare both records with the supplier’s original invoice. If the tax treatment is unclear, ask your accountant before changing anything.";

export function moneyLabel(value: string | null | undefined): string {
  if (value == null) return "Unknown";
  const [whole, fraction = "00"] = value.split(".");
  const sign = whole.startsWith("-") ? "-" : "";
  const n = whole.replace("-", "");
  const tail = n.slice(-3);
  const leading = n.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
  return `${sign}₹${leading ? leading + "," : ""}${tail}.${fraction.padEnd(2, "0")}`;
}

function taxDescription(values: Record<string, string | null>) {
  const heads = ["igst", "cgst", "sgst", "cess"];
  const present = heads.filter(
    (h) => values[h] != null && !/^0+(?:\.0+)?$/.test(values[h]!),
  );
  const amounts = present.map(
    (h) =>
      `${h === "sgst" ? "SGST/UTGST" : h.toUpperCase()} ${moneyLabel(values[h])}`,
  );
  const unknown = heads
    .filter((h) => values[h] == null)
    .map((h) => h.toUpperCase());
  return (
    [
      ...amounts,
      ...(unknown.length ? [`unknown ${unknown.join(", ")}`] : []),
    ].join(" + ") || "zero in each tax head"
  );
}

export function explainRow(row: GuideRow): {
  title: string;
  detail: string;
  next: string;
  unchanged: string;
} {
  const [a, b] = [row.books[0], row.portal[0]];
  const itcWarning = row.portal.some((d) => d.itc !== "Y");
  const explanations: Record<
    string,
    { title: string; detail: string; next: string }
  > = {
    tax_head_difference: {
      title: "The tax amounts disagree.",
      detail:
        a && b
          ? `Your books show ${taxDescription(a.values)}. The portal file shows ${taxDescription(b.values)}.`
          : "Compare the tax amounts in the two files.",
      next: inspect,
    },
    amount_difference: {
      title: "The recorded amounts disagree.",
      detail:
        "The taxable value or invoice total differs between the two files. The changed fields are shown below.",
      next: inspect,
    },
    metadata_difference: {
      title: "An invoice detail disagrees.",
      detail:
        "The date, place of supply or reverse-charge answer differs. Equal totals do not resolve that difference.",
      next: inspect,
    },
    duplicate: {
      title: "More than one entry shares this invoice identity.",
      detail: `${row.books.length} entries in your books; ${row.portal.length} in the portal file. All entries are kept. The app has not chosen a winner or counted them as one clean match.`,
      next: "Inspect the original entries to see whether the source contains repeated invoices or item rows. Do not delete an entry until you understand why it repeats.",
    },
    suggested: {
      title: "The invoice numbers look similar.",
      detail:
        a && b
          ? `Your books say “${a.number}”; the portal file says “${b.number}”. They become similar after punctuation is removed. This is only a suggestion.`
          : "This is only a suggested counterpart.",
      next: inspect,
    },
    ambiguous: {
      title: "There is more than one possible counterpart.",
      detail:
        "Several invoice numbers look similar. The app has kept every entry and has not linked them automatically.",
      next: "Open the original records and identify the correct counterpart with your accountant.",
    },
    books_only: {
      title: "This entry appears only in your books.",
      detail:
        "No counterpart was found in the selected portal file. That does not establish that the supplier has not filed.",
      next: "Check the invoice number, the selected month and whether the portal download is complete.",
    },
    portal_only: {
      title: "This entry appears only in the portal file.",
      detail:
        "No counterpart was found in the selected purchase records. It may be absent from this export or recorded differently.",
      next: "Check your source purchase export and the supplier’s invoice before adding or changing a book entry.",
    },
    incomplete: {
      title: "Some information needs checking.",
      detail:
        "A missing amount, unknown detail or import problem prevents a complete comparison. Unknown values have not been filled with zero.",
      next: "Inspect the original entries and mapping. Correct the source or mapping, reimport, then reconcile again.",
    },
    exact: {
      title: itcWarning
        ? "The fields agree, but a portal ITC flag needs attention."
        : "The compared fields agree.",
      detail: itcWarning
        ? "This invoice can match while the portal says credit is unavailable or its flag is unknown. Matching does not establish eligible input tax credit (ITC)."
        : "The invoice identity, amounts and compared details agree between these files. This does not establish eligible input tax credit (ITC).",
      next: itcWarning
        ? "Check the portal flag and original invoice with your accountant before any credit decision."
        : "You can continue to the next record. Credit eligibility and return filing remain separate checks.",
    },
  };
  return {
    ...(explanations[row.status] || {
      title: "Review these source records.",
      detail: "This result needs manual inspection.",
      next: inspect,
    }),
    unchanged,
  };
}

export function guideStep(context: GuideContext): {
  title: string;
  text: string;
  action?: GuideAction;
  button?: string;
} {
  if (context.stale)
    return {
      title: "Refresh this comparison first",
      text: "The selected files changed after this run. These results belong to earlier inputs. Reconcile again before recording a review.",
      action: "reconcile",
      button: "Reconcile current files",
    };
  if (context.phase === "export")
    return {
      title: "Sample · 4 of 4",
      text: "Download the evidence ZIP. It contains the original files, comparison, workbook and checksums. This is the last step in the sample walkthrough. The export is a review pack, not a filed return.",
      action: "export",
      button: "Download the sample evidence",
    };
  if (context.phase)
    return {
      title: "Check before saving",
      text:
        context.phase === "preview"
          ? "Check the parsed invoice numbers, dates and amounts. The checkbox is your confirmation of this file’s coverage; the guide cannot confirm it for you."
          : context.phase === "import-books"
            ? "Choose a CSV or values-only XLSX, then check every column mapping. Use the supplier’s invoice number and invoice date. Tax columns must contain INR amounts, not percentages."
            : "Choose the complete GSTR-2B JSON for this business GSTIN and month. A new statement replaces the earlier selected 2B revision. Do not import just one part of a split download.",
    };
  if (context.row) {
    const e = explainRow(context.row);
    const number = (context.row.books[0] || context.row.portal[0])?.number;
    if (context.sample) {
      if (
        number === "INV-1002" &&
        context.row.status === "tax_head_difference" &&
        context.row.books.length === 1 &&
        context.row.portal.length === 1 &&
        context.row.books[0].values.total != null &&
        context.row.books[0].values.total === context.row.portal[0].values.total
      )
        return {
          title: "Sample · 1 of 4",
          text: `Both totals are ${moneyLabel(context.row.books[0].values.total)}, but the tax heads differ. Neither file has been corrected. Next, see how repeated entries are kept.`,
          action: "next",
          button: "Next: inspect a duplicate",
        };
      if (number === "INV-1003" && context.row.status === "duplicate")
        return {
          title: "Sample · 2 of 4",
          text: "Every repeated entry is kept. Open the original entries to inspect them, then see why a match may still need attention.",
          action: "next",
          button: "Next: a match with an ITC warning",
        };
      if (
        number === "INV-1009" &&
        context.row.status === "exact" &&
        context.row.portal.some((d) => d.itc === "N")
      )
        return {
          title: "Sample · 3 of 4",
          text: "The fields agree, but the portal marks ITC unavailable. The app does not approve credit. Next, take the source evidence into an export.",
          action: "next",
          button: "Next: export the evidence",
        };
    }
    return {
      title: "Your next check",
      text: e.next,
      action: "note",
      button: "Add a review note",
    };
  }
  if (!context.workspace)
    return {
      title: "Start with a fictional example",
      text: "No GST knowledge or business files are needed. I’ll walk you through a difference, a duplicate, an ITC warning and an evidence export.",
      action: "sample",
      button: "Open the sample",
    };
  if (!context.hasBooks)
    return {
      title: "Bring in your purchase records",
      text: "These are the bills recorded in your books. Use a CSV or values-only Excel export with the supplier invoice details and separate tax amounts.",
      action: "books",
      button: "Import purchase records",
    };
  if (!context.hasPortal)
    return {
      title: "Add the portal statement",
      text: "GSTR-2B is the portal statement being compared with your books. Use the complete JSON for the same business GSTIN and month.",
      action: "portal",
      button: "Import GSTR-2B",
    };
  if (!context.hasRun)
    return {
      title: "Compare the two files",
      text: "Reconciliation finds agreements, differences and repeated entries. It does not edit your books or the portal file.",
      action: "reconcile",
      button: "Run reconciliation",
    };
  return {
    title: context.sample ? "Sample · 1 of 4" : "Start with a record",
    text: context.sample
      ? "Let’s open INV-1002. I’ll explain the actual result inside the invoice."
      : "Open a record that needs attention. I’ll explain the result and suggest what to check next.",
    action: "record",
    button: context.sample ? "Open INV-1002" : "Open a record to review",
  };
}

export function answerGuide(question: string, context: GuideContext): string {
  const q = question.toLowerCase();
  if (
    /\b(correct|wrong|right|fix|fixed|changed|change|updated|update|winner)\b/.test(
      q,
    )
  )
    return `${unchanged} GSTR-2B is an imported portal file, not a corrected output from this app. ${inspect}`;
  if (
    /\b(two|2|cards?|copies|copy|sources?|original|records?)\b/.test(q) &&
    !/\b(next|note|notes|review|export|download|mapping|row|rows)\b/.test(q)
  )
    return context.row &&
      (!context.row.books.length || !context.row.portal.length)
      ? `This result has ${context.row.books.length} entries from your books and ${context.row.portal.length} from the portal file. ${explainRow(context.row).detail}`
      : context.row &&
          (context.row.books.length > 1 || context.row.portal.length > 1)
        ? explainRow(context.row).detail +
          " Open the original entries to see each file and row reference."
        : "An invoice can have two source records: one imported from your purchase file and one from the portal file. They represent the same invoice; file names and row references identify where each copy came from. They are not two extra bills.";
  if (/\b(itc|eligible|eligibility|claim|credit)\b/.test(q)) {
    const flags = context.row?.portal.map((d) => d.itc) || [];
    return `${flags.includes("N") ? "For this record, the imported portal flag says ITC is unavailable. " : ""}Input tax credit (ITC) means GST credit on purchases. This tool does not decide whether you may claim it. A match only says the compared fields agree. Check eligibility with your accountant.`;
  }
  if (/\b(duplicate|repeat|repeated)\b/.test(q))
    return context.row?.status === "duplicate"
      ? explainRow(context.row).detail + " " + explainRow(context.row).next
      : "A duplicate group contains more than one entry with the same supplier, financial year, document kind and invoice number. The app keeps them all so you can inspect the reason; it does not silently merge or delete them.";
  if (
    /\b(igst|cgst|sgst|tax heads?|difference|different|total|totals|amount|looking)\b/.test(
      q,
    )
  )
    return context.row
      ? `${explainRow(context.row).detail} ${unchanged}`
      : "Each tax amount is compared separately. Two invoice totals can agree while IGST, CGST, SGST or cess differs. Open a record to see its actual values.";
  if (/\b(note|notes|review)\b/.test(q))
    return "A review note records what you checked and what should happen next. It does not clear the difference or change the amounts. Use Add a review note; after saving, the original result remains visible.";
  if (/\b(export|download|evidence)\b/.test(q))
    return "Export evidence creates a ZIP with the original source files, saved comparison, CSV, Excel workbook and checksum manifest. It is a review pack for you or your accountant, not a return upload or proof of eligible credit.";
  if (/\b(row|rows|granularity|line|lines|item|items)\b/.test(q))
    return "Choose One invoice per row when each row is a complete bill. Choose One item per row only when taxable and tax amounts are line amounts and the full invoice total repeats on every line. Check the preview: the wrong choice can create duplicates or incorrect aggregates.";
  if (/\b(import|upload|mapping|columns?|excel|csv|tally)\b/.test(q))
    return "Import a CSV or values-only XLSX purchase export. Map the supplier GSTIN, supplier invoice number, invoice date and separate INR tax amounts. Do not substitute a voucher number or tax percentage. Tally layouts vary; check the preview before saving. Then import the complete portal 2B JSON for this business and month.";
  if (/\b(gstin|business|month|period)\b/.test(q))
    return "A workspace holds one business GSTIN and one month. GSTIN format and checksum are checked locally; registration status is not verified online. The portal file’s receiving GSTIN and statement month must match the workspace.";
  if (/\b(register|books|book)\b/.test(q))
    return "Your books, also called the purchase register, are your own recorded purchase bills imported from Excel, CSV or a Tally export. They are one source of the comparison, not an automatic statement of which tax treatment is correct.";
  if (/\b(portal|gstr|2b)\b/.test(q))
    return "GSTR-2B is the statement downloaded from the GST portal and imported here. The app displays what that file reports. It has not logged in, amended the statement or corrected your purchase register.";
  if (/\b(ai|bot|model|cloud|offline|privacy)\b/.test(q))
    return "I’m the built-in offline guide, using prepared explanations and the values on this screen. I’m not a general AI model. Your questions stay in this open guide session and are not sent to a cloud service. I cannot edit invoices, decide credit eligibility or submit returns.";
  if (/\b(next|start|step|help|do|begin)\b/.test(q))
    return guideStep(context).text;
  return "I can explain the comparison, source copies, import mapping, review notes and evidence export. I don’t have an answer to that question in this offline guide. Try one of the questions below, or share the question with the person helping you test the app.";
}
