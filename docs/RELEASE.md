# Monthly GST 0.2.0-alpha.1

This Windows preview helps businesses using Excel or mapped Tally exports prepare monthly GST working papers. It runs locally and includes a fictional business for evaluation.

- Compare purchase records and GSTR-2B by invoice and tax head. Investigate missing entries, mismatches and duplicates with their original source references.
- Record portal and reviewed Table 4 amounts, reasons for changes, and progress through the monthly filing checklist.
- Export a review pack with an Excel workbook, the saved worksheet, reconciliation and original inputs. The ZIP includes SHA-256 checksums.
- Use the offline guide to understand invoice results and walk through the example.

The Windows ZIP includes the built interface. Install Python 3.12 or newer, run `Setup.cmd`, then launch `Start Monthly GST.cmd`. Setup downloads pinned Python dependencies. [Getting started](../README.md)

Sales reporting, credit eligibility, final liability, payment and submission are handled by the business and its authorised signatory in the GST filing workflow. Testing covers fictional data. Independent accountant review and testing with permitted real Tally and GST Portal exports are pending.
