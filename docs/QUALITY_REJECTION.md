# Quality / Rejection Module — v0.2.4

## Daily Excel workflow
1. Open **Quality / Rejection**.
2. Click **Download Daily Template**.
3. Enter daily rejection only using dropdown master values.
4. Upload the workbook from the same page.
5. The importer validates Product, Plant, Process, Machine and Phenomenon masters and updates existing business keys instead of duplicating them.

### PPM denominator
- Detection Process = `Disp_Done` → Daily MIS actual / dispatch-done actual.
- Intermediate operation → Process Daily actual.
- Machine + operation + shift available → Machine Shift Production total count.
- If no denominator exists yet, rejection quantity is imported and PPM is marked pending.

## Duplicate prevention
- Exact file duplicate: SHA-256 skip.
- Daily business key: Date + Shift + Product + Detection Process + Responsible Process + Machine + Phenomenon.
- Same key with revised quantities: update, not duplicate.
- Unknown Product/Process/Machine/Phenomenon: row error; importer does not silently create new masters.

## Quality actions
A rejection row can create an existing `Action` with category `Quality / Rejection`. It receives the same Standard Why-Why plan, attachment support and closure rules as all other actions. `quality_action_links` preserves traceability back to the rejection record.

## Historical rejection
The normalized workbook prepared from BAL / TVSM / HMCL is supported through **Upload Historical Rejection**. HMCL Total is aggregate history; the confirmed Siddharth Plant 2050 breakdown is retained separately and excluded from overall totals unless plant-level analysis is selected.
