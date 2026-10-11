import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'
const code = ts.transpileModule(fs.readFileSync(new URL('../src/time.ts', import.meta.url), 'utf8'), {
  compilerOptions: {module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022},
}).outputText
const {formatIST, dateIST, istLocalToUTC, timestampDateIST} = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'))
for (const zone of ['UTC', 'Asia/Kolkata', 'America/Los_Angeles']) {
  process.env.TZ = zone
  assert.equal(dateIST(new Date('2026-12-31T18:30:00Z')), '2027-01-01')
  assert.equal(istLocalToUTC('2027-01-01T00:15'), '2026-12-31T18:45:00.000Z')
  assert.equal(timestampDateIST('2026-12-31T18:45:00'), '2027-01-01')
  assert.equal(formatIST('2026-12-31T18:45:00Z'), formatIST('2027-01-01T00:15:00+05:30'))
  assert.equal(formatIST('2027-01-01T00:15:00+0530'), formatIST('2026-12-31T18:45:00'))
  assert.equal(formatIST(null), '—')
}
console.log('IST conversion checks passed across three host time zones')
