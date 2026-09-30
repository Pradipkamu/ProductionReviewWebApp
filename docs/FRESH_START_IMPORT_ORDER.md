# Fresh Start Import Order — v0.2.6

For a new installation with no live data, use this order:

1. Verify Product Master names, Plant, Customer and Type.
2. Import Historical Sales Price revisions (`Historical_Sales_Price_Import`).
3. Import Historical Daily MIS (`Historical_Daily_MIS_Import`).
4. Import Historical Rejection history when its remaining master/dispatch inputs are complete.
5. From go-live onward, use normal daily production workbook / Daily Rejection template.

## Why prices come before MIS
The historical MIS importer asks the effective-dated price engine for the price that applies on each MIS date. Loading price history first means Plan Sales and Actual Sales are correct at first import.

## Historical price business key
`Product + Effective From`

The previous rate is automatically closed on the day before the next rate begins. No Effective To entry is required.

## Safety
Exact repeat workbooks are skipped by SHA-256. Changed one-time import files update matching business keys; absence of a row does not delete historical data.
