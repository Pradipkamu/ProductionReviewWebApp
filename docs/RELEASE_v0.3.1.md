# v0.3.1 — Historical schedule correction

Historical MIS imports freeze daily requirements. Previously, creating a monthly schedule saved a revision but silently skipped those imported requirements, leaving May's report plan at zero. A preview now shows current, proposed and resulting plans and identifies protected imported days. Applying a revision with protected days is rejected instead of reporting misleading success.

## Apply the May 2026 schedule

1. Update the existing installation using `update_in_place_windows.bat` or `./update_in_place_linux.sh`. These scripts retain the database and validate a backup before starting the updated application. Follow `docs/UPDATE_v0.3.0.md`; this patch requires no additional migration.
2. Open Schedule, Price & Working Calendar, select the exact product and May 2026. Set Effective from to `2026-05-01` and enter the original approved May monthly schedule quantity. Actual dispatch is not the source for the monthly target.
3. Select **Correct imported historical plans** and enter a specific reason/reference, e.g. “Add missing May customer schedule, reference …”. If May is closed, obtain a user-bound correction authorization or ask Admin/Management to reopen it with a reason. Preview does not consume a correction authorization.
4. Preview the daily plan distribution using the product's Plant working calendar; verify the target and dates. Click Apply revision. The success message reports the number of applied and corrected imported days. A failed authorization or date check is displayed on screen.
5. Refresh Compliance, choose `2026-05-31` and Qty with the same product filters. The May revised plan now reflects the entered schedule; actual dispatch remains unchanged. Repeat separately for June, July and August with each month's approved target and effective date.

Original MIS plan quantities, imported baseline requirements, actual dispatch and sales values are retained. Revised requirements and applicable MIS schedule-revision links are updated from the effective date onward, with before/after audit evidence and the supplied reason. Imported requirements remain protected against ordinary recalculation. An earlier effective date must be selected deliberately; dates before it are preserved. The existing target-minus-actual-before-effective-date allocation remains in effect for mid-month revisions.

Existing saved revisions that did not apply are retained as history. Enter a new correction revision; no revision or historical actual is deleted. P2 AFMS/MQTT and Power BI remain deferred.
