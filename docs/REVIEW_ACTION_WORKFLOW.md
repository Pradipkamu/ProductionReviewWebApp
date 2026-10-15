# Daily Review & Action Workflow — v0.2.1

## Review session

1. Open **Daily Review** and choose the review date.
2. Click **Start review**.
3. The server is now the source of truth for the active review session. Browser local storage is only a cache.
4. Click **Close review** and enter the closing comment. Open actions remain active after review closure.

If a browser contains an old/stale review ID after an app/database reset, v0.2.1 automatically clears it when the Daily Review page loads.

## Raise an action

Actions can be raised in three ways:

- **Daily Review → Raise action** in the page header.
- **Daily Review → Priority exceptions → Raise** for a specific product.
- **Actions → Raise action** form.

The form captures Date, Product, Operation, optional Machine, Problem Category, Problem, Action, Owner, Due Date/Time, and Priority.

If a Daily Review session is active for the same action date, the new action is automatically linked to that review. Closing the review does not close its actions; they continue through OPEN → IN_PROGRESS / BLOCKED → CLOSED in the Actions screen.


## Daily Management Review enhancements — Phase 1 and Phase 2

- The Daily Management Review page displays a live business snapshot for the selected date and plant scope.
- Production, sales, tonnage and action KPIs are month-to-date through the selected date. Quality and OEE are selected-date views. Vendor WIP is a rolling 36-month view. The UI identifies the different periods.
- The exception agenda combines daily-control blockers/warnings with month-to-date dispatch exceptions. An exception can be prefilled into a MOM point and linked to its Product Master context.
- When an action is required, the page requires a responsible active user and target date/time. Product context is stored with the MOM point and copied to Action Context when an action is created.
- Previous pending actions are sourced from earlier review-session links, with a fallback for legacy Daily Review actions. Later-dated meetings are not included in an earlier meeting's carry-forward list.
- Meeting participants and remarks can be saved while the meeting is open. Closed meetings remain selectable from history and are no longer replaced by the active-meeting lookup for the selected date.
- MOM action counts include actions linked through either a MOM point or the action-link workflow. An empty meeting is retained if an action was linked through the Actions page.
- Quality history is stored monthly in some cases. When selected dates overlap a monthly historical rejection upload, the snapshot displays the source note explaining that the full month is included.
