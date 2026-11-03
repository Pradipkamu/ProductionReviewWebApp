# Android Companion App — Rejection Entry Phase 1

## Decision

Build a dedicated native Android companion app inside this repository at `mobile-android/`. The existing ProductionReviewWebApp remains the sole system of record. The app is a fast, role-aware shop-floor capture client; it is not a second production database and does not replace the web Quality page.

Initial release scope: **Rejection entry only**. OEE and machine-loss capture are deliberately deferred until rejection capture is proven in production.

## Users and access

The intended user groups are:
- Production operators
- Production supervisors
- Quality inspectors

All users authenticate with their existing ProductionReviewWebApp account. The app must call the existing `POST /api/auth/login` and `GET /api/auth/me` endpoints, retain the returned bearer token securely using Android Keystore-backed encryption, and honor the existing server-side role/page/API authorization. It must never grant access merely because a user can install the APK. A role denied by the backend receives a clear access message and must be provisioned through the existing user/page-access administration workflow.

## Architecture

```text
Native Android app (Kotlin + Jetpack Compose)
  ├── Login / session
  ├── Rejection capture form
  ├── Master-data cache
  ├── Local draft + pending outbox (Room)
  └── Sync worker (WorkManager)
             |
          HTTPS only
             |
ProductionReviewWebApp FastAPI
  ├── Existing authentication and authorization
  ├── Mobile capture API adapter (thin)
  ├── Shared rejection validation/business service
  └── Existing quality + master APIs
             |
       Existing PostgreSQL
```

### Technology choices

- Kotlin, Android Studio/Gradle, Jetpack Compose and Material 3.
- Retrofit + OkHttp for HTTPS API calls; no direct database access.
- Room for local drafts, cached dropdown masters and pending submissions.
- WorkManager for constrained background synchronization.
- Android Keystore-backed encryption for session secrets and sensitive local data.
- Build and signed release artifacts through GitHub Actions; signing secrets remain in GitHub Actions secrets and are never committed.

The first build should target a practical minimum Android API level supported by the existing fleet; confirm the oldest shop-floor handset before setting `minSdk`. Support portrait phones, large touch targets, readable text, and low-bandwidth operation.

## Rejection entry workflow

1. Sign in with existing username/password.
2. Load `/api/auth/me` and confirm access.
3. Select rejection date (default to India-local today) and shift (A/B/C/General).
4. Select active product, optionally filtered by plant.
5. Fetch the product's effective route for the selected date from `GET /api/masters/routes/{product_id}?on_date=YYYY-MM-DD`.
6. Select detection process from that route. Responsible process and machine are optional, matching the existing web form.
7. Select an active rejection phenomenon from `GET /api/quality/phenomena`.
8. Enter reject quantity (required and greater than zero); rework and scrap default to zero; remark and raise-Why-Why-action are optional.
9. Review a compact confirmation summary and submit.
10. Show the server's saved record ID, calculated PPM or “PPM pending” status, and any validation/duplicate response.

### Existing API contract verified in main

- `POST /api/auth/login` — existing session/token login.
- `GET /api/auth/me` — current user, role and effective page access.
- `GET /api/masters/products` — product master.
- `GET /api/masters/filter-options` — plants and other filters.
- `GET /api/masters/routes/{product_id}?on_date=...` — date-effective route operations.
- `GET /api/masters/machines` — machine master.
- `GET /api/quality/phenomena` — active rejection phenomena.
- `POST /api/quality/daily` — existing manual rejection creation and business validation.
- Optional follow-up: `POST /api/quality/rejections/{id}/raise-action` when the user selects “Raise Why-Why action”.

The current `POST /api/quality/daily` contract requires rejection_date, shift, product_id, detection_route_operation_id, phenomenon_id and reject_qty. It accepts optional responsible_route_operation_id, machine_id, rework_qty, scrap_qty, remark and action_required. The backend validates active masters, the product route effective on the rejection date, positive reject quantity and duplicate record keys. It calculates the denominator/PPM when available; rejection must still save when PPM production is pending.

## Reliability and no-duplicate design

The app must not silently lose a rejection or create duplicate records:
- Save an unfinished form as a local draft.
- Do not auto-submit while offline until the backend idempotency contract is implemented.
- Add a server-side idempotency key for mobile submissions, persisted transactionally with the created rejection result. Repeating the same key and same payload returns the original result; reusing a key with a different payload returns a conflict.
- Keep a submission in the local outbox until the server confirms success.
- On timeout, retry using the same idempotency key; never generate a new key for a retry.
- Treat business duplicate HTTP 409 separately from transport retries. Show the user the duplicate message and provide a route to the existing web correction workflow; do not create an automatic second row.
- Validate on both client and server, but server validation is authoritative.
- Display pending, syncing, saved, duplicate and failed states explicitly.
- No automatic background upload of photos or attachments in Phase 1.

## Security and audit

- HTTPS only; reject cleartext traffic and invalid certificates. No trust-all TLS configuration.
- Bearer tokens stored encrypted; provide logout and clear local session data on logout/revocation.
- Never store passwords after login.
- Respect existing account lockout, session expiry, idle timeout, audit events and change-governance rules.
- Send a stable Android app/version user-agent. Preserve server-side actor identity and request audit.
- Do not expose arbitrary API paths, SQL, or shell commands.
- No new database tables except the minimal idempotency store and any required migration; no changes to existing rejection calculations or PPM denominator rules.

## Delivery plan

### Phase A — API contract and backend safety
1. Extract the current manual rejection creation logic into a shared service without changing validation or calculation behavior.
2. Add a narrow mobile submission adapter using the same service.
3. Add transactional idempotency-key persistence and tests for replay, mismatched payload, concurrency and duplicate business record.
4. Add a compact mobile bootstrap endpoint only if the existing master endpoints prove insufficient; avoid redundant master APIs.
5. Add API tests for every required field, invalid shift, inactive product/phenomenon/machine, invalid effective route, negative/zero quantities, PPM pending and duplicate record.

### Phase B — Android foundation
1. Add `mobile-android/` Kotlin/Gradle project and reproducible GitHub Actions build.
2. Implement login, secure session storage, session expiry and role-aware access.
3. Implement master-data loading/cache and refresh.
4. Implement the rejection form with dependent route operations and accessible controls.

### Phase C — Capture and synchronization
1. Implement online submission with server-confirmed result.
2. Implement local drafts and a durable outbox using idempotency keys.
3. Implement WorkManager retries, connectivity awareness and clear sync status.
4. Implement optional Why-Why action creation with a safe recovery state if the follow-up action request fails after the rejection has saved.

### Phase D — Validation and pilot
1. Unit, API integration and Android UI tests.
2. Test with one operator, one supervisor and one quality inspector account.
3. Verify same record appears in the web Quality page and all PPM/summary calculations remain unchanged.
4. Pilot on one plant before wider rollout.
5. Publish signed APK and release notes from GitHub Actions; keep production deployment and database migration separate from the Android APK build.

## Acceptance criteria for Rejection v1

- User can sign in with existing credentials and sees only what the backend permits.
- Rejection form takes minimal taps and uses live product, route, machine and phenomenon masters.
- Route operations change correctly when product or rejection date changes.
- A valid entry appears in the existing web Quality page with the correct user, date, shift, plant, product, process, machine and phenomenon.
- Invalid and duplicate entries are rejected with understandable messages.
- PPM pending does not block rejection capture.
- Network loss does not silently discard a draft or cause duplicate rows on retry.
- No attachment is required to submit a rejection.
- Existing web workflows, data, calculations and OEE logic remain unchanged.

## Explicitly out of scope for Phase 1

- OEE / machine-loss entry.
- Image/file attachments.
- Editing or deleting saved rejection rows.
- Master-data administration from the phone.
- A separate mobile database or independent rejection calculations.
- Production server deployment until API tests and pilot acceptance pass.
