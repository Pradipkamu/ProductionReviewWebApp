import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, downloadApi } from '../api'

type Person = { id:number; full_name:string; username:string; role?:string }
type Message = { id:number; sender_id:number; sender_name:string; body:string; created_at:string }
type Conversation = { id:number; kind:'DIRECT'|'GROUP'; title?:string|null; participants:Person[]; last_message?:Message|null; unread_count:number }

function timeLabel(value?:string|null) {
  if(!value)return ''
  return new Date(value).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})
}
function conversationLabel(c:Conversation, meId:number) {
  if(c.kind==='GROUP')return c.title||'Group conversation'
  return c.participants.filter(p=>p.id!==meId).map(p=>p.full_name).join(', ')||'Direct conversation'
}

export default function Chat({me}:{me:any}) {
  const [items,setItems]=useState<Conversation[]>([])
  const [selected,setSelected]=useState<number|null>(null)
  const [messages,setMessages]=useState<Message[]>([])
  const [draft,setDraft]=useState('')
  const [people,setPeople]=useState<Person[]>([])
  const [search,setSearch]=useState('')
  const [showPeople,setShowPeople]=useState(false)
  const [groupMode,setGroupMode]=useState(false)
  const [groupTitle,setGroupTitle]=useState('')
  const [groupMembers,setGroupMembers]=useState<number[]>([])
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [attachment,setAttachment]=useState<File|null>(null)

  const refreshConversations=useCallback(async()=>{
    try { const rows=await api<Conversation[]>('/chat/conversations');setItems(rows); }
    catch(e:any){setError(e.message||'Unable to load conversations')}
  },[])
  const refreshMessages=useCallback(async(id:number)=>{
    try { const rows=await api<Message[]>(`/chat/conversations/${id}/messages?limit=60`);setMessages(rows); }
    catch(e:any){setError(e.message||'Unable to load messages')}
  },[])
  useEffect(()=>{refreshConversations();const t=window.setInterval(refreshConversations,7000);return()=>window.clearInterval(t)},[refreshConversations])
  useEffect(()=>{const token=localStorage.getItem('token');if(!token)return;const scheme=window.location.protocol==='https:'?'wss':'ws';const socket=new WebSocket(`${scheme}://${window.location.host}/api/chat/ws?token=${encodeURIComponent(token)}`);socket.onmessage=(event)=>{try{const data=JSON.parse(event.data);if(data.type==='new_message'){refreshConversations();if(data.conversation_id===selected)refreshMessages(selected);else if('Notification' in window&&Notification.permission==='granted')new Notification('New chat message',{body:data.message?.sender_name+': '+(data.message?.body||'Attachment')})}else{refreshConversations();if(data.conversation_id===selected)refreshMessages(selected)}}catch{}};return()=>socket.close()},[selected,refreshConversations,refreshMessages])
  useEffect(()=>{if(selected===null){setMessages([]);return}refreshMessages(selected);const t=window.setInterval(()=>refreshMessages(selected),4000);return()=>window.clearInterval(t)},[selected,refreshMessages])
  useEffect(()=>{let active=true;const term=search.trim();const t=window.setTimeout(()=>{api<Person[]>(`/chat/employees?q=${encodeURIComponent(term)}`).then(rows=>{if(active)setPeople(rows)}).catch(e=>{if(active)setError(e.message)})},250);return()=>{active=false;window.clearTimeout(t)}},[search])

  const current=useMemo(()=>items.find(x=>x.id===selected)||null,[items,selected])
  async function startDirect(person:Person){
    setBusy(true);setError('')
    try{const c=await api<Conversation>('/chat/conversations/direct',{method:'POST',body:JSON.stringify({user_id:person.id})});await refreshConversations();setSelected(c.id);setShowPeople(false);setSearch('')}
    catch(e:any){setError(e.message)}finally{setBusy(false)}
  }
  async function createGroup(){
    if(!groupTitle.trim()||!groupMembers.length)return
    setBusy(true);setError('')
    try{const c=await api<Conversation>('/chat/conversations/group',{method:'POST',body:JSON.stringify({title:groupTitle.trim(),user_ids:groupMembers})});await refreshConversations();setSelected(c.id);setGroupMode(false);setGroupTitle('');setGroupMembers([]);setShowPeople(false)}
    catch(e:any){setError(e.message)}finally{setBusy(false)}
  }
  async function send(e:React.FormEvent){
    e.preventDefault();if(!selected||!draft.trim()||busy)return
    setBusy(true);setError('')
    try{const sent=await api<any>(`/chat/conversations/${selected}/messages`,{method:'POST',body:JSON.stringify({body:draft.trim()})});if(attachment){const fd=new FormData();fd.append('file',attachment);await api(`/chat/conversations/${selected}/messages/${sent.id}/attachments`,{method:'POST',body:fd});setAttachment(null)}setDraft('');await refreshMessages(selected);await refreshConversations()}
    catch(e:any){setError(e.message)}finally{setBusy(false)}
  }

  return <section className="chat-page">
    <header className="page-header"><div><span className="eyebrow">TEAM COMMUNICATION</span><h1>Chat</h1><p>Message any employee or create a group conversation.</p></div><button onClick={()=>{setShowPeople(v=>!v);setGroupMode(false)}}>＋ New chat</button></header>
    {error&&<div className="error chat-error">{error}<button className="ghost" onClick={()=>setError('')}>Dismiss</button></div>}
    <div className="chat-workspace">
      <aside className="chat-list-panel">
        <div className="chat-panel-heading"><b>Conversations</b><span>{items.length}</span></div>
        {items.length===0?<div className="chat-empty-list">No conversations yet. Start a chat with an employee.</div>:items.map(c=><button key={c.id} className={`chat-conversation ${selected===c.id?'selected':''}`} onClick={()=>setSelected(c.id)}>
          <span className="chat-avatar">{(c.kind==='GROUP'?(c.title||'G'):conversationLabel(c,me.id)).slice(0,1).toUpperCase()}</span>
          <span className="chat-conversation-copy"><b>{conversationLabel(c,me.id)}</b><small>{c.last_message?.body||'No messages yet'}</small></span>
          <span className="chat-conversation-meta">{timeLabel(c.last_message?.created_at)}{c.unread_count>0&&<i>{c.unread_count}</i>}</span>
        </button>)}
      </aside>
      <section className="chat-main-panel">
        {showPeople?<div className="chat-people-view">
          <div className="chat-panel-heading"><b>{groupMode?'Create group':'Start a conversation'}</b><button className="ghost" onClick={()=>{setShowPeople(false);setGroupMode(false)}}>Close</button></div>
          {groupMode&&<label className="chat-group-title">Group name<input value={groupTitle} onChange={e=>setGroupTitle(e.target.value)} placeholder="e.g. Production Team"/></label>}
          <input className="chat-search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search employee name or username"/>
          <div className="chat-people-list">{people.map(p=><button key={p.id} className="chat-person" onClick={()=>groupMode?setGroupMembers(v=>v.includes(p.id)?v.filter(x=>x!==p.id):[...v,p.id]):startDirect(p)}>
            <span className="chat-avatar">{p.full_name.slice(0,1).toUpperCase()}</span><span><b>{p.full_name}</b><small>{p.username} · {p.role||'Employee'}</small></span>
            {groupMode&&<input type="checkbox" checked={groupMembers.includes(p.id)} readOnly/>}
          </button>)}</div>
          <div className="chat-people-actions">{groupMode?<button disabled={busy||!groupTitle.trim()||!groupMembers.length} onClick={createGroup}>Create group ({groupMembers.length})</button>:<button className="secondary" onClick={()=>setGroupMode(true)}>＋ Create group instead</button>}</div>
        </div>:current?<>
          <div className="chat-thread-heading"><div className="chat-avatar">{conversationLabel(current,me.id).slice(0,1).toUpperCase()}</div><div><b>{conversationLabel(current,me.id)}</b><small>{current.kind==='GROUP'?current.participants.length+' members':'Direct conversation'}</small></div></div>
          <div className="chat-message-list">{messages.map((m:any)=><div key={m.id} className={`chat-message-row ${m.sender_id===me.id?'mine':''}`}><div className="chat-bubble"><small>{m.sender_id===me.id?'You':m.sender_name}</small><p>{m.body}</p>{(m.attachments||[]).map((a:any)=><button className="chat-file-link" key={a.id} type="button" onClick={()=>downloadApi(a.download_url,a.file_name)}>📎 {a.file_name}</button>)}<time>{timeLabel(m.created_at)}</time></div></div>)}</div>
          <form className="chat-composer" onSubmit={send}><textarea value={draft} onChange={e=>setDraft(e.target.value)} placeholder="Write a message…" rows={2} maxLength={10000}/><label className="chat-attach-label">＋<input type="file" hidden accept=".pdf,.png,.jpg,.jpeg,.webp,.docx,.xlsx,.pptx,.txt,.csv" onChange={e=>setAttachment(e.target.files?.[0]||null)}/></label>{attachment&&<small>{attachment.name}</small>}<button disabled={busy||!draft.trim()}>Send</button></form>
        </>:<div className="chat-welcome"><div className="chat-welcome-icon">✉</div><h2>Your team conversations</h2><p>Select a conversation or start a new chat with any employee.</p><button onClick={()=>setShowPeople(true)}>Start new chat</button></div>}
      </section>
    </div>
    <div className="chat-footnote">Messages are visible only to conversation participants and authorized system administrators.</div>
  </section>
}
