import { MultiSelect } from './MultiSelect'

export type ScopeValues = {
  plant: string[]
  productGroup: string[]
  customerId: string[]
  productId: string[]
}

export function appendScope(q: URLSearchParams, v: ScopeValues){
  if(v.plant.length) q.set('plant', v.plant.join(','))
  if(v.productGroup.length) q.set('product_group', v.productGroup.join(','))
  if(v.customerId.length) q.set('customer_id', v.customerId.join(','))
  if(v.productId.length) q.set('product_id', v.productId.join(','))
  return q
}

export function ScopeFilters({value,onChange,options,products,showProduct=true,showLabels=false}:{
  value:ScopeValues,
  onChange:(v:ScopeValues)=>void,
  options:any,
  products:any[],
  showProduct?:boolean,
  showLabels?:boolean,
}){
  function set<K extends keyof ScopeValues>(key:K,val:ScopeValues[K]){
    const next={...value,[key]:val}
    // Parent scope changes can make a previous part selection invalid.
    if(key!=='productId') next.productId=[]
    onChange(next)
  }
  const filteredProducts=products.filter(p=>(!value.plant.length||value.plant.includes(String(p.plant||'')))&&(!value.productGroup.length||value.productGroup.includes(String(p.product_group||'')))&&(!value.customerId.length||value.customerId.includes(String(p.customer_id))))
  return <div className={`scope-filters ${showLabels?'oee-scope-filter-grid':''}`}>
    {showLabels?<div className="oee-scope-filter"><span>Plant</span><MultiSelect value={value.plant} onChange={v=>set('plant',v)} placeholder="All Plants" options={(options?.plants||[]).map((x:string)=>({value:String(x),label:String(x)}))}/></div>:<MultiSelect value={value.plant} onChange={v=>set('plant',v)} placeholder="All Plants" options={(options?.plants||[]).map((x:string)=>({value:String(x),label:String(x)}))}/>}
    {showLabels?<div className="oee-scope-filter"><span>Customer</span><MultiSelect value={value.customerId} onChange={v=>set('customerId',v)} placeholder="All Customers" options={(options?.customers||[]).map((x:any)=>({value:String(x.id),label:x.name}))}/></div>:<MultiSelect value={value.customerId} onChange={v=>set('customerId',v)} placeholder="All Customers" options={(options?.customers||[]).map((x:any)=>({value:String(x.id),label:x.name}))}/>}
    {showLabels?<div className="oee-scope-filter"><span>Type / Group</span><MultiSelect value={value.productGroup} onChange={v=>set('productGroup',v)} placeholder="All Types / Groups" options={(options?.product_groups||[]).map((x:string)=>({value:String(x),label:String(x)}))}/></div>:<MultiSelect value={value.productGroup} onChange={v=>set('productGroup',v)} placeholder="All Types / Groups" options={(options?.product_groups||[]).map((x:string)=>({value:String(x),label:String(x)}))}/>}
    {showProduct&&(showLabels?<div className="oee-scope-filter"><span>Part</span><MultiSelect value={value.productId} onChange={v=>set('productId',v)} placeholder="All Parts" searchable options={filteredProducts.map((p:any)=>({value:String(p.id),label:p.name}))}/></div>:<MultiSelect value={value.productId} onChange={v=>set('productId',v)} placeholder="All Parts" searchable options={filteredProducts.map((p:any)=>({value:String(p.id),label:p.name}))}/>)}
  </div>
}
