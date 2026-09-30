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
