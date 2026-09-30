# Standard Why-Why Action Plan — v0.2.3

The Action module uses one workflow across Production, Quality/Rejection, Process, Vendor, OEE/Loss, Schedule and management review exceptions.

## Flow

1. Raise Action: date, context, problem, immediate/proposed action, owner, due date and priority.
2. Immediate Containment.
3. Why 1 → Why 2 → Why 3 → Why 4 → Why 5.
4. Root Cause.
5. Corrective Action.
6. Preventive / Systemic Action.
7. Verification Method and Result.
8. Effectiveness Check and Result.
9. Lessons Learned / Horizontal Deployment.
10. Close only after the required standard fields are complete.

Why 3–5 are optional if the root cause has already been demonstrated; the system does not encourage artificial Why statements merely to reach five rows.

## Required before closure

- Why 1
- Why 2
- Root Cause
- Corrective Action
- Verification Method
- Verification Result
- Effectiveness Result

## Attachments

Evidence can be added to any action: defect photos, trial reports, 5-Why sheets, fishbone diagrams, Excel analyses, SOP/WI updates and training records.

Files are stored in the persistent `database/attachments/<ACTION-NO>/` hierarchy. The database stores filename, MIME type, size, SHA-256, caption, user and upload timestamp.
