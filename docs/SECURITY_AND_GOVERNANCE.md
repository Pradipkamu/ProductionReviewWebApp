# Security and month governance

Passwords require 12–128 characters including uppercase, lowercase, a digit and a symbol. Admin creation/reset forces a change at the next sign-in. Changing or resetting a password, role or active state invalidates old JWTs. Password hashes are excluded from governance audit JSON.

| Role | Write access |
|---|---|
| Admin | All modules and user administration |
| Production | MIS, process, OEE, vendor movements, actions and reviews |
| Quality | Quality, quality imports, actions and reviews |
| Planning | Planning/schedules, masters, production/MIS/price imports, MIS, actions and reviews |
| Management | Reviews, actions, month close/reopen/correction authorization and reminder acknowledgment |
| Purchase / Vendor | Vendor movements and actions |
| Dispatch | Actions |
| View Only | Read access; can change own password |

All roles can read business reports. User lists and administration are Admin-only; audit reading requires Admin or Management. API authorization applies regardless of frontend controls. Management can authorize a correction for a known user ID; Admin can select the user from the UI. Authorization does not grant additional module write permissions.

Month status is application-wide. Month Close protects daily MIS, requirements, process production, quality daily/monthly history, machine production/loss, calendar and vendor outward/receipt transactions. Effective-dated price/route/cycle changes are also checked against closed periods they could affect. Adding receipts in a current open month to an outward issued in a closed month is allowed because receipts are separate immutable transactions.

Admin or Management can close/reopen a month with a reason (minimum 5 characters) or issue a user-bound correction authorization for one closed month, expiring after one hour and consumed on one successful request. Send the authorization in `X-Correction-ID`. New data in a closed period also requires authorization. Historical updates/deletions require `X-Change-Reason`; MIS edit reasons and correction-grant reasons are also accepted. The sidebar's Historical correction controls set these headers.

Before/after business snapshots are appended within the same transaction as edits, imports and schedule recalculation. Audit API is read-only. A correction spanning multiple closed months must be done after explicit reopen of those months, since a grant covers one month. Reclose with a reason when finished.

Database credentials and `.env` stay outside Git. These controls do not replace PostgreSQL access control: direct database access can bypass API roles and application auditing. The existing Compose development database credentials and exposed ports are unchanged; configure deployment networking and private credentials for your installation.
