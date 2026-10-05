# Security & Governance

## Current deployment policy

ProductionReviewWebApp supports both HTTP and HTTPS.

For the current Oracle deployment, keep:

```env
REQUIRE_HTTPS=false
TRUST_PROXY_HEADERS=false
```

This avoids breaking the application while HTTPS is unavailable. HTTP traffic is not encrypted in transit, so the Oracle HTTP endpoint should not be exposed more broadly than necessary. Database and backend ports are bound to localhost by default; only the frontend port is externally reachable.

When a trusted HTTPS reverse proxy is working, switch to:

```env
REQUIRE_HTTPS=true
TRUST_PROXY_HEADERS=true
```

The reverse proxy must set `X-Forwarded-Proto` correctly. Verify HTTPS access before enabling `REQUIRE_HTTPS`.

## Authentication controls

- Passwords are PBKDF2-SHA256 hashed with a per-password salt.
- Password policy: 12–128 characters with upper case, lower case, number and symbol.
- Initial/reset passwords must be changed at first sign-in.
- Repeated failed sign-ins lock the account temporarily.
- Defaults: 5 failures -> 15 minute lock.
- Every login creates a server-side session.
- Sessions have an absolute token expiry and an idle timeout.
- Defaults: 720 minute absolute lifetime, 60 minute idle timeout.
- Password resets, account disablement and role changes revoke existing sessions.
- Users can revoke their own sessions; administrators can revoke any session.
- Successful/failed sign-ins, lockouts, password changes and session revocations are logged.

## Role policy

Backend API authorization is authoritative. Frontend navigation is only a convenience and is not relied on for security.

| Area | Write roles |
|---|---|
| MIS | Production, Planning |
| Process Actuals | Production |
| OEE / Machine Loss | Production |
| Schedule | Planning |
| Quality / Rejection | Quality |
| Vendor | Purchase, Vendor, Production |
| Imports | Planning, Quality, Production |
| Actions / Why-Why | Production, Quality, Planning, Purchase, Dispatch, Vendor, Management |
| Reviews | Management, Production, Quality, Planning |
| Masters | Planning |
| Capacity | Planning, Production |
| Month Close / Historical Authorization | Management |
| User Administration | Admin |
| Read-only reporting | Authenticated users unless an endpoint applies a stricter rule |

ADMIN bypasses normal write-role checks but remains subject to audit and month-protection rules.

### Page visibility configuration

An administrator can open **Security / Users → Page Visibility by Role** and choose which application pages appear for each role. Saving requires a reason and creates both governance-audit and security-event records. The same matrix blocks direct browser navigation to a hidden page.

The Admin role always retains every page. The Security / Users page remains available to every role so users cannot lose password and session controls. Existing installations begin with the previous hard-coded visibility defaults.

Page visibility does not grant backend permission. A visible page can still show an authorization error when its API requires a stricter role, and hiding a page does not replace backend API policy.

## Historical data

- Closed months are protected.
- Historical corrections require a reason.
- Closed-month corrections require a valid authorization.
- An authorization is user-specific, month-specific, time-limited and single-use.
- Old/new values are retained in governance audit records where supported.
- Process Actual corrections have dedicated old/new quantity history.
- A saved zero actual is valid data; absence of a record is treated as missing.

## Network exposure

Docker Compose defaults:

- PostgreSQL: `127.0.0.1:5432`
- FastAPI: `127.0.0.1:8000`
- Frontend: `0.0.0.0:5173`

Do not open PostgreSQL or FastAPI directly in an Oracle/Google/AWS firewall.

## HTTP security headers

Frontend and backend set defense-in-depth headers including:

- X-Content-Type-Options
- X-Frame-Options
- Referrer-Policy
- Permissions-Policy
- Content-Security-Policy on the frontend
- HSTS only when the backend actually sees HTTPS

No automatic HTTP-to-HTTPS redirect is enabled while Oracle HTTPS is unresolved.

## Phase 2 implemented in v0.5.5

- Workbook structure, upload size and expanded Office package validation.
- Action attachment type allow-list, content signature checks and path containment.
- Fresh-install strong database/bootstrap credentials.
- Safe database password rotation scripts for existing installations.
- Verified custom-format backups with SHA-256.
- Recorded isolated restore-verification evidence.
- Diagnostics for backup integrity, restore freshness, upload policy and secret/network hardening.

See SECURITY_PHASE2_v0.5.5.md.

## Next hardening phase

1. Optional two-factor authentication for Admin/Management.
2. Optional plant/department data-scope permissions if users should see only assigned areas.
3. Cloud secret-manager integration when the deployment platform is finalized.
4. Optional external malware scanner integration if a ClamAV/service endpoint is available.
