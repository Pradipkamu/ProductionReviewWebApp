# Mobile Navigation & Role-Based Module Permissions — Development TODO

**Status:** Planned / Not implemented  
**Target:** ProductionReviewWebApp + Android companion app  
**Repository:** `Pradipkamu/ProductionReviewWebApp`  
**Planning branch:** `main` (this document only)  
**Implementation branch:** Create a dedicated feature branch from the latest `main` when development starts.  
**Purpose:** Define web-app-managed permissions and configurable Android navigation so Quality, Production, Admin, Management and other users see the modules relevant to their work without weakening backend authorization.

---

## 1. Agreed product direction

Build a **role- and permission-driven hybrid navigation system**:

- A compact top app bar with hamburger menu, current screen title and optional notifications.
- A bottom navigation bar for up to **four destinations**, including **More**.
- A left-side Material 3 modal navigation drawer for secondary modules, account information and Logout.
- The bottom bar is not hardcoded by Android role names. It is driven by configuration returned by the backend.
- Admin/Management can configure the default navigation for each role in the **web application**.
- Optionally allow per-user shortcut customization later, but only within modules the user is already authorized to access.
- Backend permissions remain authoritative. Hiding a menu item is not security.

### Example default navigation (subject to actual role/permission configuration)

| User profile / role | Suggested bottom destinations |
|---|---|
| Quality | Pending Actions, Rejection Entry, More |
| Production | Pending Actions, OEE, More |
| Admin / Management | Pending Actions, Quality/Rejection, OEE, More |
| Other roles | Pending Actions plus only the modules explicitly granted to them, then More |

The exact role names and module assignments must be confirmed against the existing user/role model before implementation. Do not assume every user with a role name has access to a module.

### Drawer / More destinations

- My Action History
- Other authorized modules not pinned to the bottom bar
- Account / Profile (read-only details initially unless profile editing already exists)
- Logout

Do not show duplicate destinations in both bottom navigation and the drawer unless there is a clear UX reason. Logout must be visually separated from normal navigation.

---

## 2. Phase 0 — Audit current authorization and mobile implementation

- [ ] Inspect current backend user model, role enum/constants, permission dependencies and authorization helpers.
- [ ] Inspect existing web-app user/role management screens and identify where permissions are currently assigned.
- [ ] Inventory all mobile-accessible modules and their existing API routes.
- [ ] For each module, record read, create, update, submit, approve/reject, attachment and administrative capabilities as applicable.
- [ ] Identify whether permissions are role-based, user-specific, plant-scoped or a combination.
- [ ] Inspect current Android login response and token/session handling.
- [ ] Inspect current `/api/actions/my-pending`, `/api/actions/admin/pending-by-user`, quality rejection and OEE API contracts.
- [ ] Confirm the exact role names used for Admin, Management, Quality and Production.
- [ ] Check whether OEE is already exposed through APIs suitable for mobile; do not create a mobile shortcut to a screen that cannot load real authorized data.
- [ ] Document existing permissions and preserve backward compatibility. Do not replace or weaken existing access checks.

**Deliverable:** A short authorization matrix and API inventory before code changes.

---

## 3. Phase 1 — Define a central module and permission catalog

Create a backend-owned catalog of stable module identifiers. Suggested initial identifiers:

| Module key | Display label | Intended purpose |
|---|---|---|
| `actions` | Pending Actions | View and update assigned actions; Admin/Management user-wise overview where authorized |
| `quality_rejection` | Rejection Entry | Create and view quality rejection records |
| `oee` | OEE | View permitted OEE / machine loss information |
| `action_history` | Action History | View permitted action history |
| `production_monitor` | Production Monitor | Future/when mobile-ready |
| `machine_loading` | Machine Loading | Future/when mobile-ready |
| `compliance` | Compliance | Future/when mobile-ready |

- [ ] Confirm module identifiers and labels with existing web-app terminology.
- [ ] Define permission keys separately from module identifiers. Examples: `actions.view_own`, `actions.view_all`, `actions.update_own`, `quality_rejection.create`, `quality_rejection.view`, `oee.view`.
- [ ] Define action-level permissions only where the business workflow requires them; avoid creating an unnecessarily complex permission for every button.
- [ ] Add plant/organizational scope to permission evaluation where existing application rules require it.
- [ ] Keep module catalog server-owned; Android must not invent permission keys or grant access locally.
- [ ] Decide how unknown/future module keys are handled: ignore safely and log diagnostically.

---

## 4. Phase 2 — Backend permission enforcement

- [ ] Reuse the existing authorization framework and role model wherever possible.
- [ ] Add/extend permission records or role-permission mappings only after Phase 0 schema audit.
- [ ] Support role defaults and explicit user-level grants/denials if the existing architecture supports them cleanly.
- [ ] Define precedence clearly. Recommended: explicit user denial overrides role grant; explicit user grant is allowed only when policy permits; no matching grant means deny.
- [ ] Enforce permissions in every relevant API endpoint, not just in the mobile client.
- [ ] Verify ownership rules for ordinary users: they can only read/update their own assigned actions unless specifically granted broader access.
- [ ] Verify Admin/Management access to user-wise pending-action groups is permission-controlled and not based solely on a client-supplied role.
- [ ] Enforce Quality rejection create/view permissions and existing plant/data scope.
- [ ] Enforce OEE view permissions and plant/machine scope.
- [ ] Enforce attachment upload/download permissions independently of parent-screen visibility.
- [ ] Return consistent HTTP 401 for unauthenticated requests and 403 for authenticated but unauthorized requests.
- [ ] Ensure permission checks also apply to direct API calls, guessed IDs, downloads and background operations.
- [ ] Add audit logging for permission changes, including actor, target role/user, old value, new value and timestamp.
- [ ] Ensure permission changes take effect on the next API request; avoid requiring a fresh APK or relying indefinitely on stale token claims.
- [ ] Add migration with safe defaults that preserve existing authorized workflows. Review migration/rollback and backup impact.

**Security rule:** A hidden Android button is not an authorization control. Every protected operation must be rejected by the backend when the caller lacks permission.

---

## 5. Phase 3 — Web application Permission Management UI

Add a permission-management area to the existing web app, accessible only to appropriately authorized Admin users.

### 5.1 Role permission matrix

- [ ] Add a page such as **Administration → Roles & Permissions**.
- [ ] Display roles as rows and modules/permissions as columns or grouped sections.
- [ ] Group permissions by module (Actions, Quality, OEE, etc.).
- [ ] Provide clear View / Create / Update / Approve / Admin capabilities where applicable.
- [ ] Distinguish own-record access from all-user access.
- [ ] Show plant scope where applicable.
- [ ] Provide Save, Cancel and confirmation for high-impact changes.
- [ ] Warn when a change removes access that users currently rely on.
- [ ] Prevent removal of the last effective administrator permission or provide a protected recovery path.
- [ ] Show who last changed the role configuration and when.

### 5.2 User-specific access

- [ ] Extend the existing user management screen with an **Effective Permissions** view.
- [ ] Show inherited role permissions and user-specific overrides separately.
- [ ] Allow authorized administrators to grant/restrict specific modules for an individual user, if approved in Phase 0.
- [ ] Make the effective result understandable; do not silently override role permissions.
- [ ] Provide a reset-to-role-default action.
- [ ] Keep user-specific permission editing restricted to designated administrators.

### 5.3 Mobile navigation configuration

- [ ] Add a **Mobile Navigation** configuration section under administration.
- [ ] Allow an administrator to select the default bottom-bar destinations for each role.
- [ ] Only offer modules that the role is permitted to access.
- [ ] Limit the bottom bar to four destinations maximum, counting More.
- [ ] Allow ordering of shortcuts.
- [ ] Place remaining authorized modules in the More/drawer list automatically.
- [ ] Prevent duplicate module assignments.
- [ ] Provide a preview for each role before saving.
- [ ] If a module is disabled or permission is revoked, remove it from the effective navigation automatically.
- [ ] Keep a safe fallback navigation (for example, Pending Actions if authorized, otherwise the first permitted module) so users are not stranded.
- [ ] Do not allow configuration to grant permissions; navigation configuration only chooses among already permitted modules.

### 5.4 Optional individual shortcut preference

- [ ] Decide whether users may personalize their own bottom-bar shortcuts.
- [ ] If enabled, let users choose only from their effective permitted modules.
- [ ] Preserve administrator-defined mandatory shortcuts, if any.
- [ ] Store user preferences separately from security permissions.
- [ ] Provide Reset to role defaults.

---

## 6. Phase 4 — API contract for Android

Provide a single authenticated endpoint, subject to existing API conventions, for example:

`GET /api/mobile/navigation`

Suggested response shape (illustrative; finalize to match project conventions):

```json
{
  "user": {
    "id": 123,
    "display_name": "Example User",
    "role": "QUALITY"
  },
  "modules": [
    {
      "key": "actions",
      "label": "Pending Actions",
      "icon": "clipboard-list",
      "route": "actions",
      "permissions": ["actions.view_own"]
    },
    {
      "key": "quality_rejection",
      "label": "Rejection Entry",
      "icon": "alert-circle",
      "route": "rejection",
      "permissions": ["quality_rejection.create"]
    }
  ],
  "bottom_navigation": ["actions", "quality_rejection"],
  "drawer_navigation": ["action_history"],
  "configuration_version": 1
}
```

- [ ] Return only modules the current user is authorized to access.
- [ ] Return the effective bottom-bar order and drawer destinations.
- [ ] Return stable module keys; Android maps keys to native screens.
- [ ] Do not return arbitrary executable routes, code or URLs that Android blindly opens.
- [ ] Include a configuration version or updated timestamp for cache invalidation.
- [ ] Define behavior for empty module lists and expired sessions.
- [ ] Keep existing APIs working; this endpoint supplements, not replaces, their backend permission checks.
- [ ] Add API schema and integration tests.

---

## 7. Phase 5 — Android navigation implementation

- [ ] Implement a reusable Material 3 navigation shell.
- [ ] Add top app bar with hamburger menu and current destination title.
- [ ] Add dynamic bottom navigation with a maximum of four items including More.
- [ ] Add modal navigation drawer opened by hamburger or More.
- [ ] Drawer should show user display name and role, then authorized secondary modules, Account and Logout.
- [ ] Close the drawer automatically after selecting a destination.
- [ ] Close the drawer on outside tap and Android Back.
- [ ] Preserve the selected destination and sensible back-stack behavior.
- [ ] Prevent duplicate navigation destinations.
- [ ] Use native screen mapping for known module keys; safely ignore unsupported keys.
- [ ] Show a useful access-denied or unavailable state if permissions change while the app is open.
- [ ] Refresh navigation configuration after login and when returning from a long-lived session, and handle 401/403 responses.
- [ ] Clear session/token and local user-specific state on Logout.
- [ ] Ask for confirmation before Logout to avoid accidental sign-out.
- [ ] Do not store passwords or treat locally cached navigation as proof of authorization.
- [ ] Keep the existing Rejection Entry and Pending Actions workflows intact.
- [ ] Add OEE destination only when the authorized OEE mobile screen and API integration are ready.
- [ ] Ensure keyboard, small-screen, accessibility labels and touch targets are handled.

---

## 8. Phase 6 — Role and permission test matrix

Create automated backend tests and a manual Android acceptance checklist.

| Scenario | Expected result |
|---|---|
| Quality user with rejection permission | Rejection appears; authorized rejection APIs work |
| Quality user without OEE permission | OEE is absent; direct OEE API request returns 403 |
| Production user with OEE permission | OEE appears; authorized OEE APIs work |
| Production user without rejection-create permission | Rejection create is absent/disabled; direct create API returns 403 |
| Admin with user-wise action permission | User groups and authorized action details appear |
| Management with user-wise action permission | User groups appear according to configured permission |
| Ordinary user | Only own assigned actions appear |
| User guesses another user's action ID | Backend denies access unless explicitly authorized |
| Permission revoked while session is active | Subsequent protected API request is denied; navigation refresh removes module |
| User has no optional modules | Safe fallback screen is shown; no crash |
| Logout | Session is cleared and login screen is shown |
| User changes plant/scope | Data and module access respect the effective scope |
| Attachment URL is accessed directly | Backend checks the caller's permission and parent-record access |

Also test:
- [ ] Role configuration save/cancel and audit history.
- [ ] User override and reset-to-role-default.
- [ ] Bottom-bar ordering and four-item limit.
- [ ] Disabled modules are not selectable in web configuration.
- [ ] Drawer closes after selection, outside tap and Back.
- [ ] Android process restart and token expiry.
- [ ] Existing rejection photo upload and action evidence upload.
- [ ] Regression test existing web application navigation and APIs.

---

## 9. Phase 7 — Rollout and documentation

- [ ] Implement on a new feature branch created from latest `main`; do not work directly on `main`.
- [ ] Keep this planning document updated as tasks are completed.
- [ ] Add migration and rollback instructions.
- [ ] Run backend unit/integration tests and frontend lint/build.
- [ ] Build Android APK in the established Termux ARM64 environment.
- [ ] Test with separate Quality, Production, Admin, Management and ordinary-user accounts.
- [ ] Test API authorization independently of the Android UI.
- [ ] Obtain user acceptance before merging to `main`.
- [ ] Deploy backend/web changes before distributing an APK that depends on the new navigation endpoint.
- [ ] Keep old APK behavior compatible during staged rollout or provide a clear minimum-version policy.
- [ ] Record the final permission matrix and administrator operating instructions.

---

## 10. Suggested implementation order

1. **Audit existing roles, permissions and API checks** (Phase 0).
2. **Design permission catalog and effective-permission rules** (Phases 1–2).
3. **Implement backend enforcement and tests** (Phase 2).
4. **Build web Role & Permission Management UI** (Phase 3.1–3.2).
5. **Build web Mobile Navigation configuration** (Phase 3.3).
6. **Implement navigation configuration API** (Phase 4).
7. **Implement Android dynamic navigation shell** (Phase 5).
8. **Complete role-based acceptance and regression tests** (Phase 6).
9. **Document, stage and release** (Phase 7).

### Acceptance criteria

The work is complete only when an administrator can configure role permissions and mobile shortcuts in the web application; Android displays the configured permitted destinations; and direct API calls to unauthorized modules/actions are denied by the backend. Existing web workflows and Android Rejection Entry / Pending Actions must continue to work.

**Important:** This is a planning document only. No application code, database schema, permissions, web UI, Android UI or production configuration is changed by saving this TODO.
