import fs from 'node:fs/promises';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const out=path.join(root,'outputs','process-template');await fs.mkdir(out,{recursive:true});
const design=JSON.parse(await fs.readFile(root+'/backend/app/data/approved_process_design.json','utf8'));
const w=Workbook.create();const sheets=['Instructions','Flow_Definition','Stage_Schedules','Daily_Actuals','Column_Reference'].map(name=>w.worksheets.add(name));
function table(s,headers,rows,widths){s.showGridLines=false;s.getRangeByIndexes(0,0,1,headers.length).values=[headers];if(rows.length)s.getRangeByIndexes(1,0,rows.length,headers.length).values=rows;const used=s.getRangeByIndexes(0,0,Math.max(rows.length+1,2),headers.length);used.format.font={name:'Arial',size:10,color:'#243746'};used.format.rowHeight=30;used.format.verticalAlignment='center';const h=s.getRangeByIndexes(0,0,1,headers.length);h.format.fill='#20364D';h.format.font={name:'Arial',size:10,color:'#FFFFFF',bold:true};h.format.wrapText=true;h.format.rowHeight=38;headers.forEach((_,i)=>s.getRangeByIndexes(0,i,Math.max(rows.length+1,2),1).format.columnWidth=widths[i]||22);s.freezePanes.freezeRows(1);s.freezePanes.freezeColumns(2);s.tables.add(s.getRangeByIndexes(0,0,Math.max(rows.length+1,2),headers.length),true,s.name.replaceAll('_','')+'Table');}
const instructions=[
 ['Production process upload v0.4.0',''],
 ['Source',design.source_file],
 ['1. Flow definition','Use the approved rows. Default effective date is 2026-10-01. Change all rows of a product together if another date is intended.'],
 ['Company','Enter your company in Flow_Definition.company. Existing product customer, plant and type masters are preserved.'],
 ['2. Stage schedules','Enter allocated monthly pieces, month, effective date, reference and reason. Blank quantity is missing; 0 is an explicit zero allocation.'],
 ['Working days','Allocation is divided across the plant working calendar. Sunday is off only when no explicit calendar entry exists. Integer remainders go to earlier working days.'],
 ['Revisions','A revised monthly allocation subtracts plans already issued before its effective date. Earlier plans remain unchanged. Actual production never changes this plan calculation.'],
 ['3. Daily actuals','Enter date, total actual pieces and rejected pieces for each active stage. Enter 0 rejects explicitly. Remove unfilled rows from Stage_Schedules and Daily_Actuals before importing.'],
 ['Corrections','Enter a reason when changing an existing actual or imported plan. Closed months require Reopen or Historical Correction authorization.'],
 ['HMCL dispatch','Enter all variant dispatch details and the parent total. Once all details are present, their sum must match the parent. Only parent dispatch feeds MIS.'],
 ['Vendor quantities','Daily outward/receipt summaries do not create challan transactions. Use Vendor WIP for outward challans and partial receipts. Missing coating vendors remain pending.'],
 ['Deferred columns','Column_Reference retains deferred, obsolete, summary and duplicate columns. These are excluded from daily and schedule import.'],
 ['Schedule provenance','Schedule Review quantities from the earlier layout are not copied: Kubota, Aluminium and Grab column meanings changed. Enter current allocations explicitly.'],
 ['Import sequence','Download template, fill inputs, Preview Flow Definition and Confirm, then Preview/Confirm Stage Schedules and Daily Actuals separately.'],
 ['Parent plan','Customer dispatch schedules remain in the Schedule screen. Stage schedules do not silently replace customer schedules.'],
 ['Historical quality','Platina 99 remains available for historical rejection reporting. The design does not delete existing records.'],
 ['Future expansion','AFMS / MQTT and Power BI remain deferred.'],
 ];table(sheets[0],['Topic','Guidance'],instructions,[28,116]);sheets[0].getRange('B2:B18').format.wrapText=true;sheets[0].getRange('A2:B18').format.rowHeight=48;sheets[0].freezePanes.unfreeze();
const defs=[],alloc=[],daily=[],reference=[];
for(const p of design.products)for(const s of p.stages){defs.push([p.name,s.code,s.name,s.role,s.branch,s.variant,s.vendor,s.predecessors.join(';'),s.source_column,s.active,s.parent_dispatch,s.alias_of,new Date('2026-10-01T00:00:00Z'),'Approved corrected process flow',null,p.plant,p.customer,p.type]);reference.push([p.name,s.source_column,s.code,s.name,s.active?'Active':p.historical_only?'Historical only':s.alias_of?'Duplicate alias':'Deferred / reference',s.alias_of,s.predecessors.join(';'),s.vendor||null,s.variant||null]);if(s.active){alloc.push([p.name,s.code,null,null,null,null,null,false]);daily.push([p.name,s.code,null,null,null,null]);}}
table(sheets[1],['product','stage_code','stage_name','role','branch','variant','vendor','predecessors','source_column','active','parent_dispatch','alias_of','effective_from','reason','company','plant','customer','type'],defs,[28,42,25,22,30,22,24,60,14,12,15,44,16,38,28,14,18,14]);
sheets[1].getRange(`H2:H${defs.length+1}`).format.wrapText=true;
sheets[1].getRange(`M2:M${defs.length+1}`).setNumberFormat('yyyy-mm-dd');sheets[1].getRange(`M2:O${defs.length+1}`).format.fill='#FFF3CD';
for(const col of ['J','K'])sheets[1].getRange(`${col}2:${col}${defs.length+1}`).dataValidation={rule:{type:'list',values:['TRUE','FALSE']}};
table(sheets[2],['product','stage_code','month','effective_from','allocated_qty','reference','reason','correct_imported_plans'],alloc,[28,42,16,16,18,28,44,22]);
sheets[2].getRange(`C2:D${alloc.length+1}`).setNumberFormat('yyyy-mm-dd');sheets[2].getRange(`E2:E${alloc.length+1}`).setNumberFormat('#,##0');sheets[2].getRange(`C2:H${alloc.length+1}`).format.fill='#FFF3CD';sheets[2].getRange(`E2:E${alloc.length+1}`).dataValidation={rule:{type:'whole',operator:'between',formula1:0,formula2:9999999999999}};
table(sheets[3],['product','stage_code','date','actual_qty','reject_qty','reason'],daily,[28,42,16,20,20,44]);sheets[3].getRange(`C2:C${daily.length+1}`).setNumberFormat('yyyy-mm-dd');sheets[3].getRange(`D2:E${daily.length+1}`).setNumberFormat('#,##0');sheets[3].getRange(`C2:F${daily.length+1}`).format.fill='#FFF3CD';
table(sheets[4],['product','source_column','stage_code','stage_name','status','alias_of','predecessors','vendor','variant'],reference,[28,15,42,28,24,44,65,24,22]);
sheets[4].getRange(`G2:G${reference.length+1}`).format.wrapText=true;
w.recalculate();console.log((await w.inspect({kind:'table',range:'Flow_Definition!A38:D46',tableMaxRows:9,tableMaxCols:4,maxChars:1600})).ndjson);
console.log((await w.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!',options:{useRegex:true,maxResults:20},maxChars:500})).ndjson);
for(const [name,range] of [['Instructions','A1:B8'],['Flow_Definition','A1:D9'],['Stage_Schedules','A1:H7'],['Daily_Actuals','A1:F7'],['Column_Reference','A1:E8']]){const png=await w.render({sheetName:name,range,scale:1.4});await fs.writeFile(out+'/'+name+'.png',new Uint8Array(await png.arrayBuffer()));}
const xlsx=await SpreadsheetFile.exportXlsx(w);await xlsx.save(out+'/Production_Process_Upload_v0.4.0.xlsx');await fs.mkdir(root+'/backend/templates',{recursive:true});await fs.copyFile(out+'/Production_Process_Upload_v0.4.0.xlsx',root+'/backend/templates/Production_Process_Upload_v0.4.0.xlsx');console.log('Exported '+defs.length+' definitions and '+alloc.length+' active input rows');
