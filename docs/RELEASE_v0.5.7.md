# ProductionReviewWebApp v0.5.7

## Fixes

- Daily Rejection preview detects repeated Date, Shift, Product, Detection Process, Responsible Process, Machine and Phenomenon combinations inside the same workbook.
- Duplicate feedback includes both Excel row numbers and instructs the user to combine quantities into one row.
- Database and preview exceptions no longer render as an empty `[]` row error.
- The login form starts with an empty username instead of displaying the administrator account name.

## Compatibility and deployment

- No database migration is required from v0.5.6.
- The new HTTPS server must retain `REQUIRE_HTTPS=true` and `TRUST_PROXY_HEADERS=true` in its existing `.env`. Local HTTP installations retain their existing settings.
- PostgreSQL and backend host bindings remain localhost-only by default.
- Existing data and credentials are unchanged.

For an existing installation, copy the release files over the application directory while retaining `.env` and `database/`, then run the normal update-in-place script.

## Completion update (6 October 2026)

- Restore the missing Process Monitor daily Plan/Actual chart below the average chart, with stage selection and the daily table. Working dates come from the existing API; missing quantities remain distinct from recorded zero.
- Include the corrected Windows backup helper: native stderr status messages no longer stop successful SSH/SCP operations; nonzero exits and SHA-256 failures still stop the script.
- No new database migration or version-number change; identify this completion update by its Git commit.
