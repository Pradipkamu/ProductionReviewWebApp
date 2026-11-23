# Fault Tree Analysis (FTA) – Machining Defects

## Purpose

FTA provides a structured, evidence-based investigation workflow for machining defects recorded in the existing Quality Rejection module. It does not modify rejection quantities, dispatch quantities, PPM, or the existing Quality Rejection records.

## Initial master data

Migration `0029_machining_fta` creates:

- 15 machining operation types.
- 14 machining defect types.
- 210 published starter templates (one for each seeded operation/defect combination).
- Versioned template records and investigation/finding/evidence/action/status-history tables.

Starter fault trees are investigation prompts. Their causes are not considered proven until an investigator records objective evidence and confirms the relevant leaf event.

## Investigation workflow

1. Open **Quality & OEE → Fault Tree Analysis**.
2. Select the machining operation, defect, source Quality Rejection, and matching published template.
3. Create the investigation. The selected template version and tree are snapshotted so later template revisions do not rewrite historical investigations.
4. Select each fault-tree node and record the observation, measured/expected values, verification method, and result.
5. Attach evidence to the relevant finding. Supported evidence extensions are JPG/JPEG, PNG, WEBP, PDF, XLSX, CSV, and TXT. Each file is limited to 20 MB and each investigation to 40 evidence files.
6. Mark a cause as confirmed only after evidence is attached and a verification method is entered. Only BASIC_EVENT and EXTERNAL_EVENT leaf nodes may be classified as root, occurrence, or escape causes.
7. Create a corrective/preventive action directly from the FTA, or link an existing action. An action created from FTA is marked as an FTA action and does **not** create a second Why-Why plan; the fault tree and its confirmed findings are the root-cause record. The action record is used once for owner, due date, implementation updates, attachments and closure. Existing standalone actions retain the standard Why-Why closure requirement.
8. Admin or Quality verifies the investigation, moving it to **VERIFIED_PENDING_ACTIONS**. Admin or Quality can close it only after at least one linked corrective/preventive action exists and all linked actions are closed. FTA-created actions can be closed through Action Management without filling a duplicate Why-Why form.

AND/OR gate states are derived from the status of child nodes. A gate state is an aid to reasoning; it is not a substitute for objective evidence or engineering approval.

## Roles

| Role | FTA access |
|---|---|
| Admin | Full access; maintain operations, defects and templates; verify and close |
| Quality | Full investigation access; maintain operations, defects and templates; verify and close |
| Production | Create and update investigations they own or created; attach evidence and link actions; cannot manage templates or verify/close |
| Management | Read-only investigation, evidence and dashboard access |

The FTA navigation item is available to Admin, Management, Quality and Production only when both FTA and Quality page visibility are enabled. The backend also enforces FTA role and investigation ownership checks.

## API surface

- `GET /api/fta/operations`
- `GET /api/fta/defects`
- `GET /api/fta/rejections`
- `GET/POST /api/fta/templates`
- `PUT /api/fta/templates/{id}`
- `POST /api/fta/templates/{id}/revisions`
- `POST /api/fta/templates/{id}/publish`
- `GET/POST /api/fta/investigations`
- `GET/PATCH /api/fta/investigations/{id}`
- `PUT /api/fta/investigations/{id}/findings/{node_id}`
- `GET/POST /api/fta/investigations/{id}/evidence`
- `GET /api/fta/investigations/{id}/evidence/{evidence_id}`
- `POST /api/fta/investigations/{id}/actions`
- `POST /api/fta/investigations/{id}/verify`
- `POST /api/fta/investigations/{id}/close`
- `GET /api/fta/dashboard`

## Validation and release sequence

1. Run backend tests, including `backend/tests/test_fta.py`, against the isolated CI test database.
2. Run the frontend build and npm audit.
3. Validate Alembic revision continuity from `0028_chat_device_tokens` to `0029_machining_fta`.
4. On a disposable database, run `alembic upgrade head`, confirm 15 operations, 14 defects and 210 starter templates, then test investigation creation, evidence upload/download, action linkage, verification and closure.
5. Test role behavior with Admin, Quality, Production and Management accounts.
6. Take and verify a production backup before any approved deployment.
7. Apply the migration and deploy only after explicit production approval.

**Production safety:** This feature branch and its draft pull request do not authorize a production migration, backend deployment, merge, or production data change. Do not run `alembic upgrade head` on the production database until approval is given.

## Rollback

The migration downgrade drops the FTA tables and their data. Before any production rollback, export FTA investigations, findings, evidence metadata and linked-action records, and confirm the backup/restore plan. Do not downgrade a production database without explicit approval.


## Action implementation discoveries and investigation report

FTA investigations are listed on Action Management so action owners and reviewers can navigate from an action workflow to the originating investigation. FTA actions remain exempt from the standalone Why-Why plan; their root-cause analysis stays in FTA.

When an FTA action owner changes the action status, the UI asks whether a different cause was discovered during implementation. If yes, the owner must provide the cause description and an evidence reference. The system creates a `PROPOSED` cause under **Causes Discovered During Action Implementation** in the originating investigation and records an Action History entry. If the investigation had already been verified, the new cause automatically reopens it to `IN_PROGRESS` and clears the previous verification so Quality must verify the revised analysis again. The owner can also use **Report new cause** from the Action list.

ADMIN/QUALITY reviewers can accept a proposal for further investigation, confirm it as a root cause (verification method required), or rule it out with review remarks. Accepted proposals remain open for resolution. FTA investigation closure is blocked while any discovered cause remains `PROPOSED` or `ACCEPTED`; an FTA action cannot be closed while its discovered cause is awaiting review.

A printable investigation report is available from Action Management and the FTA workspace at `/fta/report/{id}`. It includes the source rejection, complete snapshotted fault tree and findings, evidence register, confirmed root causes, linked corrective/preventive actions, action implementation history, newly discovered causes, and final verification/closure history. Use Print / Save PDF to export it.
