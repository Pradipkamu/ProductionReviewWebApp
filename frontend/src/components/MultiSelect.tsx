import { useEffect, useMemo, useRef, useState } from 'react'

export type MultiSelectOption={value:string,label:string}

export function MultiSelect({value,onChange,options,placeholder='All',searchable=true,className=''}:{
  value:string[],
  onChange:(next:string[])=>void,
  options:MultiSelectOption[],
  placeholder?:string,
  searchable?:boolean,
  className?:string,
}){
  const [open,setOpen]=useState(false)
  const [search,setSearch]=useState('')
  const singleSelect=className.split(/\s+/).includes('manual-search-select')
  function closeMenu(){setOpen(false);setSearch('')}
  const ref=useRef<HTMLDivElement>(null)
  useEffect(()=>{
    function close(e:MouseEvent){if(ref.current&&!ref.current.contains(e.target as Node))closeMenu()}
    document.addEventListener('mousedown',close)
    return()=>document.removeEventListener('mousedown',close)
  },[])
  const filtered=useMemo(()=>{
    const q=search.trim().toLowerCase()
    return q?options.filter(x=>x.label.toLowerCase().includes(q)):options
  },[options,search])
  const selectedLabels=options.filter(x=>value.includes(x.value)).map(x=>x.label)
  const label=value.length===0?placeholder:value.length===1?(selectedLabels[0]||'1 selected'):`${value.length} selected`
  function toggle(v:string){
    if(singleSelect){
      onChange([v])
      closeMenu()
      return
    }
    onChange(value.includes(v)?value.filter(x=>x!==v):[...value,v])
  }
  return <div className={`multi-select ${className}`} ref={ref}>
    <button type="button" className={`multi-select-trigger ${value.length?'active':''}`} onClick={()=>open?closeMenu():setOpen(true)}>
      <span>{label}</span><span className="multi-select-caret">▾</span>
    </button>
    {open&&<div className="multi-select-menu">
      <div className="multi-select-actions"><button type="button" className="secondary small" onClick={()=>{onChange([]);if(singleSelect)closeMenu()}}>All</button><button type="button" className="secondary small" onClick={closeMenu}>Done</button></div>
      {searchable&&(singleSelect||options.length>8)&&<input className="multi-select-search" placeholder="Search…" value={search} onChange={e=>setSearch(e.target.value)}/>} 
      <div className="multi-select-options">{filtered.map(o=><label key={o.value} className="multi-select-option"><input type="checkbox" checked={value.includes(o.value)} onChange={()=>toggle(o.value)}/><span>{o.label}</span></label>)}{filtered.length===0&&<div className="multi-select-empty">No matching items</div>}</div>
    </div>}
  </div>
}
