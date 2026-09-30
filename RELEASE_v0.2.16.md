# v0.2.16 consolidated release

This source tree is the consolidated application obtained from the v0.2.6 fresh-start baseline plus all update-in-place releases through v0.2.16.

Key retained capabilities include historical sales-price import, historical MIS import, Quality/Rejection history and PPM linkage to MIS dispatch, standard Why-Why actions and attachments, multi-select analytical filters, 8-week compliance reporting, Quality Qty/PPM trends, and day-wise action counts on Daily Compliance.

Backend regression status on the consolidated source: **22 passed, 1 skipped**.

Runtime data is intentionally excluded from source control. Never commit `.env`, PostgreSQL data, backups, imported workbooks, attachments, or production Excel/CSV files.
