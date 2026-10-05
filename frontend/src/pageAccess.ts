export type NavItem = { key:string, to:string, label:string, required?:boolean }

export const navItems:NavItem[] = [
  {key:'insights',to:'/insights',label:'Exceptions / Data Quality'},
  {key:'diagnostics',to:'/diagnostics',label:'System Diagnostics'},
  {key:'account',to:'/account',label:'Security / Users',required:true},
  {key:'governance',to:'/governance',label:'Month Close / Audit'},
  {key:'daily_review',to:'/',label:'Daily Review'},
  {key:'mis',to:'/mis',label:'MIS'},
  {key:'schedule',to:'/schedule',label:'Schedule / Price / Calendar'},
  {key:'machine_master',to:'/machine-master',label:'Machine Master'},
  {key:'capacity',to:'/capacity',label:'Capacity / Manpower'},
  {key:'process',to:'/process',label:'Process Monitor'},
  {key:'process_actuals',to:'/process-actuals',label:'Process Actuals / Edit'},
  {key:'quality',to:'/quality',label:'Quality / Rejection'},
  {key:'casting_quality',to:'/casting-quality',label:'Casting Quality'},
  {key:'customer_quality',to:'/customer-quality',label:'Customer Quality'},
  {key:'reports',to:'/reports',label:'Compliance Reports'},
  {key:'management_reports',to:'/management-reports',label:'Management Reports'},
  {key:'actions',to:'/actions',label:'Actions'},
  {key:'vendor',to:'/vendor',label:'Vendor WIP'},
  {key:'oee',to:'/oee',label:'Machine / OEE'},
  {key:'analytics',to:'/analytics',label:'Analytics'},
  {key:'masters',to:'/masters',label:'Masters'},
  {key:'import',to:'/import',label:'Excel Import'},
]

const legacyRestrictions:Record<string,string[]> = {
  diagnostics:['ADMIN','MANAGEMENT'],
  governance:['ADMIN','MANAGEMENT'],
  import:['ADMIN','PLANNING','QUALITY','PRODUCTION'],
}

export function canViewPage(me:any,pageKey:string){
  if(me?.role==='ADMIN'||pageKey==='account')return true
  if(Array.isArray(me?.page_access))return me.page_access.includes(pageKey)
  return !legacyRestrictions[pageKey]||legacyRestrictions[pageKey].includes(me?.role)
}

export function firstVisiblePath(me:any){
  return navItems.find(item=>canViewPage(me,item.key))?.to||'/account'
}
