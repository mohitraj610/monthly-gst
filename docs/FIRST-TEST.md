# Your first 10-minute test

Use this fictional example to learn how to read a comparison and prepare a review pack.

Open `Start Monthly GST.cmd`, visit the address it prints, then select **Explore sample data**. The business and records are fictional. A purchase register is the buyer's own list of bills; GSTR-2B is the portal statement being compared with that list.

You can also select **Guide me** in the sidebar to start the linked sample walkthrough. Inside an invoice, **Help me understand** opens a local guide that explains the result and suggests the next step. It uses prepared guidance and the current comparison; it is not a general AI model.

## 1. Find the hidden difference

Search for **INV-1002** and open it. Both invoice totals are **₹1,180**. In the register, CGST and SGST are **₹90 each**, while the portal has **₹180 IGST**. The result should say **Tax heads differ**, and highlight those three cells. The app has not corrected either file or proved which source is right. The tool should help you see what differs before you inspect the original invoice.

Open **Add a review note**, then enter your name and: “The totals agree, but the tax heads differ. The accountant should inspect the invoice.” Save it. The mismatch must remain visible.

## 2. Find the duplicate

Clear the search and open **INV-1003**. Expand **See all 3 original entries**. You should see **two register records and one 2B record**, with the original source row references. Neither register row should disappear. Do not decide that either row is wrong yet; the source file could itself contain duplicate entries.

## 3. Find a match that still needs attention

Open **INV-1009**. Its compared fields agree, but the portal says **ITC unavailable**. It should remain in **Needs attention**. “Exact match” does not mean “you can claim this credit.”

## 4. Try taking evidence away with you

Select **Export evidence**. The ZIP should contain the original two source files, `result.json`, `manifest.json`, a CSV and an Excel workbook. Open the workbook and inspect **Source documents**; the source records should be present there too.

## 5. Try the filing worksheet

Open **Filing review**. Enter a fictional IGST amount of ₹180.01 under portal row 4(A)(5) and ₹175.00 under the corresponding reviewed row. Save, then expand **Compare saved figures**. The difference should be −₹5.01, and 4(C) should show unknown because other amounts are blank. Export the filing review and open **Table 4 review** in the workbook to see the same difference.

## Share feedback

Use fictional or anonymised values when reporting an issue. Include the app version, what you tried, and what you expected. Helpful feedback includes the following.

- The first screen or phrase you did not understand.
- Whether you could explain the INV-1002 difference in your own words.
- Any button that failed, or anything that looked correct when you thought it should be flagged.
