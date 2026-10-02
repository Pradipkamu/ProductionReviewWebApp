# v0.4.6 — Controlled Daily Rejection Template

## What changed

- The Quality page generates `Daily_Rejection_Upload_v0.4.6.xlsx` from the active database masters at download time.
- Shift, Product, Detection Process, Responsible Process, Machine, Phenomenon and Raise Action use dropdowns backed by workbook named ranges.
- Date, Shift, Product, Detection Process, Phenomenon and Reject Qty are visually marked as required.
- Plant, Customer and Type auto-fill from Product Master and their formula cells are protected.
- Reject Qty must be greater than zero. Rework and Scrap must be non-negative when entered.
- A short Instructions sheet explains the daily workflow; the master list remains hidden.

## Preview controls

Excel validation can be bypassed by pasting values, so Import Preview also enforces the rules. It rejects a blank or invalid Date, Shift, Product, Detection Process, Phenomenon or Reject Qty; an unknown optional Machine or Responsible Process; negative quantities; and Raise Action values other than Yes/No.

Formula-assisted blank template rows are now ignored. They no longer appear as hundreds of false rejected rows during preview.

## Daily use

1. Add any new rejection phenomenon once under **Approved Phenomenon Master**.
2. Download a fresh Daily Template from **Quality / Rejection**.
3. Enter one rejection combination per row using the dropdowns.
4. Preview the workbook and correct every rejected row.
5. Confirm once the preview has no row errors.

Download a new template whenever Product, Process, Machine or Phenomenon masters change. No database migration is required for v0.4.6.
