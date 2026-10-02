# OEE Workflow and Audit — v0.4.7

## Audit result

| Area | Previous risk | v0.4.7 control |
|---|---|---|
| Machine-shift entry | Duplicate rows could inflate time and production | Exact-scope duplicate block; existing row loads for correction |
| Product/operation/machine | Unmatched combinations could be saved | Product route is validated for the date; mapped machines are prioritized and invalid mapped combinations are rejected |
| Cycle time | Free manual value could distort Performance | Effective Standard Cycle Time is loaded and persisted automatically |
| Time and counts | Negative/impossible relationships were accepted | API validation for shift, break, downtime, total, good and reject quantities |
| Summary scope | Different products on one machine/shift could mix | Daily page summary is filtered by selected product and operation |
| Loss reconciliation | All loss components were compared with downtime | Only Availability-category loss minutes reconcile with downtime |
| Loss identification | Table displayed numeric loss IDs | Approved loss name and OEE component are shown |
| Corrections | No controlled page update | Correction reason required; closed months still require Reopen or one-use authorization |
| Action plan | No direct OEE/loss-to-action workflow | Low OEE and loss-event actions create the standard Why-Why plan with source context |
| Management report | Charts lacked full traceability | Detailed shift and loss tables include source fields and action status |
| Early warning | OEE data faults were found late | Data Quality flags duplicate, unclassified and over-classified daily records |

## Master readiness before daily entry

1. Product has an effective Route and enabled Operation.
2. Operation has an effective Machine Mapping.
3. Product Operation/Machine has an effective positive Ideal Cycle Time.
4. Loss Categories are active and assigned to Availability, Performance, Quality or Non-OEE.

Missing mapping appears as a warning when no mapping exists at all. If mappings exist, an unmapped machine is blocked. A missing effective cycle time blocks OEE saving unless a positive legacy/manual value is supplied through the API; the web page expects the master value.

## Daily operating sequence

1. Open **Machine / OEE** and select Date, Shift, Product, Operation and mapped Machine.
2. Enter Shift Duration, Planned Break, Downtime, Total, Good and Reject quantities.
3. Review the automatic cycle time and any warnings, then save the shift entry.
4. Add each material loss using the approved category, minutes, quantity loss and a useful symptom/remark.
5. Reduce **Downtime unclassified** to zero and correct any **loss over-classified** warning.
6. Raise an OEE action when below target, or raise a loss action for the dominant/recurring event.
7. Complete the standard Why-Why plan in **Actions** and track it in **Management Reports → OEE & Loss**.
8. Check **Management Exceptions / Data Quality** before closing the daily review.

## Interpretation

- Availability explains planned time lost to downtime.
- Performance compares ideal production time with actual run time. Raw values above 100% remain visible for diagnosis; reported OEE caps Performance at 100%.
- Quality is Good / Total; unclassified output therefore reduces Quality rather than being silently accepted.
- Loss Pareto includes all OEE components, while downtime reconciliation includes only Availability losses.

## Pending Excel phase

Do not design a universal OEE upload workbook from assumptions. After the actual forms for every machine shop are attached, audit their sheets, cell layouts, shift conventions, machine/part naming, formulas, loss buckets and units. Then design one normalized Web OEE Upload template plus a helper/conversion function with Preview and Confirmation. Existing manual OEE records and master-effective dates must remain protected during that phase.
