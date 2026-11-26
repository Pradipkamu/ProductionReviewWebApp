# Shared Quality Phenomena Master for FTA

## Scope

Revision `0031_shared_fta_phenomena` connects FTA defects to the canonical
`quality_rejection_phenomena` master without deleting or renumbering existing
records. It is additive and intentionally preserves the legacy FTA code contract.

## Data model

- `quality_rejection_phenomena` is the canonical phenomenon record.
- `fta_category` and `fta_description` store FTA-specific classification and
  explanation on that shared record.
- `fta_phenomenon_code_map` maps each unchanged legacy FTA defect code to one
  canonical `quality_rejection_phenomena.id`.
- `fta_defect_library` remains as a compatibility/code registry because
  `fta_templates.defect_code` still references its unique `code`.
- Existing template codes, versions, trees, investigation records, findings,
  histories, evidence, and `template_snapshot_json` are not rewritten.

For an existing FTA defect whose normalized name already exists in Quality,
the migration reuses that Quality row and preserves its ID/code/group/team/
criticality. Otherwise it creates a new Quality phenomenon with an `FTA_`
prefixed code and `Machining Rejection` group. The legacy FTA code is retained
in the mapping in either case. No fuzzy name matching is performed; for example,
`MH-001` is not automatically merged with a similarly worded dimensional
phenomenon unless the names normalize exactly.

## Safe rollout

1. Take and verify a database backup. Record the current Alembic revision and
   counts for `quality_rejection_phenomena`, `fta_defect_library`,
   `fta_templates`, and `fta_investigations`.
2. Deploy this feature branch to a test environment only.
3. Run `alembic upgrade head`. Revision 0031 adds two nullable metadata
   columns, creates the mapping table, adds any missing canonical rows, and
   maps every current FTA code. It aborts if any FTA code remains unmapped.
4. Verify the counts and mapping queries below before allowing users to test.
5. Test FTA defect listing/creation, template listing/creation/revision, and
   investigation/report views. Confirm that existing template codes and
   snapshots remain byte-for-byte unchanged.
6. Only after test approval, plan a separately approved production rollout.
7. Do not drop `fta_defect_library` in this phase. Its FK is still required by
   `fta_templates.defect_code`; replacing that FK and retiring the compatibility
   table require a separate reviewed migration after all consumers are audited.

## Post-migration verification SQL

```sql
-- Every legacy FTA code must have exactly one canonical mapping.
SELECT
    (SELECT COUNT(*) FROM fta_defect_library) AS legacy_defects,
    (SELECT COUNT(*) FROM fta_phenomenon_code_map) AS mapped_defects;

-- No unmapped legacy codes.
SELECT d.code
FROM fta_defect_library d
LEFT JOIN fta_phenomenon_code_map m
  ON m.legacy_defect_code = d.code
WHERE m.legacy_defect_code IS NULL;

-- No template code may lose its legacy registry row or canonical mapping.
SELECT t.id, t.code, t.defect_code
FROM fta_templates t
LEFT JOIN fta_defect_library d ON d.code = t.defect_code
LEFT JOIN fta_phenomenon_code_map m ON m.legacy_defect_code = t.defect_code
WHERE d.code IS NULL OR m.legacy_defect_code IS NULL;

-- Review FTA metadata attached to canonical Quality phenomena.
SELECT q.id, q.code, q.name, q.phenomenon_group,
       q.fta_category, q.fta_description, m.legacy_defect_code
FROM quality_rejection_phenomena q
JOIN fta_phenomenon_code_map m ON m.phenomenon_id = q.id
ORDER BY q.fta_category, q.name, m.legacy_defect_code;
```

## Rollback policy

The migration's downgrade intentionally refuses to remove shared mappings or
metadata. If a test rollout must be reverted, restore the verified pre-migration
backup or prepare a reviewed forward repair. Do not manually drop the mapping,
metadata columns, or legacy code rows.
