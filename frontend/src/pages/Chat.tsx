import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, downloadApi } from '../api'

type Person = { id:number; full_name:string; username:string; role?:string; chat_enabled?:boolean }
type Attachment = { id:number; file_name:string; download_url:string; mime_type?:string }
type Message = { id:number; sender_id:number; sender_name:string; body:string; created_at:string; attachments?:Attachment[] }
type Conversation = { id:number; kind:'DIRECT'|'GROUP'; title?:string|null; participants:Person[]; last_message?:Message|null; unread_count:number }

function timeLabel(value?:string|null) {
  if(!value)return ''
  return new Date(value).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})
}
function dateLabel(value?:string|null) {
  if(!value)return ''
  const date=new Date(value)
  const today=new Date()
  const yesterday=new Date(); yesterday.setDate(today.getDate()-1)
  if(date.toDateString()===today.toDateString())return 'Today'
  if(date.toDateString()===yesterday.toDateString())return 'Yesterday'
  return date.toLocaleDateString([], {day:'numeric',month:'short',year:date.getFullYear()===today.getFullYear()?undefined:'numeric'})
}
function conversationLabel(c:Conversation, meId:number) {
  if(c.kind==='GROUP')return c.title||'Group conversation'
  return c.participants.filter(p=>p.id!==meId).map(p=>p.full_name).join(', ')||'Direct conversation'
}
function initials(value:string) {
  return value.trim().split(/\s+/).slice(0,2).map(x=>x[0]||'').join('').toUpperCase()||'PR'
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
  const [reports,setReports]=useState<any[]>([])
  const [showReports,setShowReports]=useState(false)
  const [chatUsers,setChatUsers]=useState<Person[]>([])
  const [filter,setFilter]=useState<'ALL'|'UNREAD'|'GROUPS'>('ALL')

  const refreshConversations=useCallback(async()=>{
    try { const rows=await api<Conversation[]>('/chat/conversations');setItems(rows); }
    catch(e:any){setError(e.message||'Unable to load conversations')}
  },[])
  const refreshMessages=useCallback(async(id:number)=>{
    try { const rows=await api<Message[]>(`/chat/conversations/${id}/messages?limit=60`);setMessages(rows); }
    catch(e:any){setError(e.message||'Unable to load messages')}
  },[])
  useEffect(()=>{refreshConversations();const t=window.setInterval(refreshConversations,7000);return()=>window.clearInterval(t)},[refreshConversations])
  useEffect(()=>{if(me?.role==='ADMIN'){api<any[]>('/chat/admin/reports').then(setReports).catch(()=>{});api<Person[]>('/chat/admin/users').then(setChatUsers).catch(()=>{})}},[me?.role])
  useEffect(()=>{const token=localStorage.getItem('token');if(!token)return;const scheme=window.location.protocol==='https:'?'wss':'ws';const socket=new WebSocket(`${scheme}://${window.location.host}/api/chat/ws?token=${encodeURIComponent(token)}`);socket.onmessage=(event)=>{try{const data=JSON.parse(event.data);if(data.type==='new_message'){refreshConversations();if(selected!==null&&data.conversation_id===selected)refreshMessages(selected);else if('Notification' in window&&Notification.permission==='granted')new Notification('New chat message',{body:data.message?.sender_name+': '+(data.message?.body||'Attachment')})}else{refreshConversations();if(selected!==null&&data.conversation_id===selected)refreshMessages(selected)}}catch{}};return()=>socket.close()},[selected,refreshConversations,refreshMessages])
  useEffect(()=>{if(selected===null){setMessages([]);return}refreshMessages(selected);const t=window.setInterval(()=>refreshMessages(selected),4000);return()=>window.clearInterval(t)},[selected,refreshMessages])
  useEffect(()=>{let active=true;const term=search.trim();const t=window.setTimeout(()=>{api<Person[]>(`/chat/employees?q=${encodeURIComponent(term)}`).then(rows=>{if(active)setPeople(rows)}).catch(e=>{if(active)setError(e.message)})},250);return()=>{active=false;window.clearTimeout(t)}},[search])

  const current=useMemo(()=>items.find(x=>x.id===selected)||null,[items,selected])
  const visibleItems=useMemo(()=>items.filter(c=>filter==='UNREAD'?c.unread_count>0:filter==='GROUPS'?c.kind==='GROUP':true),[items,filter])
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
    try{
      const sent=await api<any>(`/chat/conversations/${selected}/messages`,{method:'POST',body:JSON.stringify({body:draft.trim()||' '})})
      if(attachment){const fd=new FormData();fd.append('file',attachment);await api(`/chat/conversations/${selected}/messages/${sent.id}/attachments`,{method:'POST',body:fd});setAttachment(null)}
      setDraft('');await refreshMessages(selected);await refreshConversations()
    } catch(e:any){setError(e.message)}finally{setBusy(false)}
  }

  return <section className="chat-page chat-whatsapp">
    <header className="page-header chat-page-header"><div><span className="eyebrow">TEAM COMMUNICATION</span><h1>Chats</h1><p>Private employee and group conversations</p></div><button onClick={()=>{setShowPeople(true);setGroupMode(false)}}>＋ New chat</button></header>
    {error&&<div className="error chat-error">{error}<button className="ghost" onClick={()=>setError('')}>Dismiss</button></div>}
    {me?.role==='ADMIN'&&<section className="chat-admin-tools"><button type="button" onClick={()=>setShowReports(v=>!v)}>Admin moderation ({reports.filter(r=>r.status==='OPEN').length} open reports)</button>{showReports&&<div className="chat-report-list">{reports.map(r=><article key={r.id}><b>{r.sender}</b><small>Reported by {r.reporter} · {r.status}</small><p>{r.reason}</p><blockquote>{r.message}</blockquote>{r.status==='OPEN'&&<><button type="button" onClick={async()=>{await api('/chat/admin/messages/'+r.message_id,{method:'DELETE'});await api('/chat/admin/reports/'+r.id,{method:'PATCH',body:JSON.stringify({status:'RESOLVED'})});setReports(await api('/chat/admin/reports'))}}>Remove message & resolve</button><button type="button" className="secondary" onClick={async()=>{await api('/chat/admin/reports/'+r.id,{method:'PATCH',body:JSON.stringify({status:'DISMISSED'})});setReports(await api('/chat/admin/reports'))}}>Dismiss</button></>}</article>)}</div>}<div className="chat-user-access"><b>Employee chat access</b>{chatUsers.map(p=><button type="button" key={p.id} onClick={async()=>{await api('/chat/admin/users/'+p.id+'/chat-access?enabled='+(p.chat_enabled?'false':'true'),{method:'PATCH'});setChatUsers(v=>v.map((x:any)=>x.id===p.id?{...x,chat_enabled:!p.chat_enabled}:x))}}>{(p as any).chat_enabled?'Disable':'Enable'} {p.full_name}</button>)}</div></section>}
    <div className={`chat-workspace chat-wa-workspace ${selected!==null?'thread-open':''} ${showPeople?'people-open':''}`}>
      <aside className="chat-list-panel chat-wa-list">
        {showPeople?<div className="chat-people-view chat-wa-people">
          <div className="chat-wa-list-top"><button className="chat-icon-button" onClick={()=>{setShowPeople(false);setGroupMode(false)}} aria-label="Back to chats">‹</button><div><b>{groupMode?'New group':'New chat'}</b><small>Choose employees to message</small></div></div>
          {groupMode&&<label className="chat-group-title">Group name<input value={groupTitle} onChange={e=>setGroupTitle(e.target.value)} placeholder="Production Team"/></label>}
          <input className="chat-search chat-wa-search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search name or username"/>
          <div className="chat-people-list">{people.map(p=><button key={p.id} className="chat-person" onClick={()=>groupMode?setGroupMembers(v=>v.includes(p.id)?v.filter(x=>x!==p.id):[...v,p.id]):startDirect(p)}>
            <span className="chat-avatar">{initials(p.full_name)}</span><span><b>{p.full_name}</b><small>{p.username} · {p.role||'Employee'}</small></span>
            {groupMode&&<input type="checkbox" checked={groupMembers.includes(p.id)} readOnly/>}
          </button>)}</div>
          <div className="chat-people-actions">{groupMode?<button disabled={busy||!groupTitle.trim()||!groupMembers.length} onClick={createGroup}>Create group ({groupMembers.length})</button>:<button className="secondary" onClick={()=>setGroupMode(true)}>＋ Create group</button>}</div>
        </div>:<>
          <div className="chat-wa-list-top"><div><span className="eyebrow">PRODUCTION REVIEW</span><h2>Chats</h2></div><button className="chat-new-button" onClick={()=>{setShowPeople(true);setGroupMode(false)}} aria-label="New chat">＋</button></div>
          <label className="chat-wa-search-wrap"><span>⌕</span><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search employees"/></label>
          <div className="chat-wa-filters">{(['ALL','UNREAD','GROUPS'] as const).map(x=><button key={x} className={filter===x?'active':''} onClick={()=>setFilter(x)}>{x==='ALL'?'All chats':x==='UNREAD'?'Unread':'Groups'}</button>)}</div>
          <div className="chat-wa-conversations">
            {visibleItems.length===0?<div className="chat-empty-list">{filter==='UNREAD'?'No unread messages.':filter==='GROUPS'?'No group conversations yet.':'No conversations yet. Start a chat with an employee.'}</div>:visibleItems.map(c=>{
              const label=conversationLabel(c,me.id)
              const last=c.last_message
              return <button key={c.id} className={`chat-conversation chat-wa-conversation ${selected===c.id?'selected':''}`} onClick={()=>setSelected(c.id)}>
                <span className={`chat-avatar chat-wa-avatar ${c.kind==='GROUP'?'group':''}`}>{initials(label)}</span>
                <span className="chat-conversation-copy"><b>{label}</b><small>{last?.body|| (last?.attachments?.length?'Attachment':'No messages yet')}</small></span>
                <span className="chat-conversation-meta"><time>{last?dateLabel(last.created_at):''}</time>{c.unread_count>0&&<i>{c.unread_count}</i>}</span>
              </button>
            })}
          </div>
        </>}
      </aside>
      <section className="chat-main-panel chat-wa-main">
        {current?<>
          <div className="chat-thread-heading chat-wa-thread-heading">
            <button className="chat-icon-button chat-back-button" onClick={()=>setSelected(null)} aria-label="Back to chats">‹</button>
            <div className={`chat-avatar chat-wa-avatar ${current.kind==='GROUP'?'group':''}`}>{initials(conversationLabel(current,me.id))}</div>
            <div className="chat-thread-title"><b>{conversationLabel(current,me.id)}</b><small>{current.kind==='GROUP'?current.participants.length+' members':'Employee conversation'}</small></div>
          </div>
          <div className="chat-message-list chat-wa-message-list">
            {messages.map((m,index)=>{
              const mine=m.sender_id===me.id
              const previous=messages[index-1]
              const showDate=!previous||new Date(previous.created_at).toDateString()!==new Date(m.created_at).toDateString()
              return <div key={m.id}>
                {showDate&&<div className="chat-date-divider"><span>{dateLabel(m.created_at)}</span></div>}
                <div className={`chat-message-row chat-wa-message-row ${mine?'mine':''}`}>
                  <div className="chat-bubble chat-wa-bubble">
                    {current.kind==='GROUP'&&!mine&&<small>{m.sender_name}</small>}
                    {m.body?.trim()&&<p>{m.body}</p>}
                    {(m.attachments||[]).map(a=><button className="chat-file-link" key={a.id} type="button" onClick={()=>downloadApi(a.download_url,a.file_name)}>📎 {a.file_name}</button>)}
                    <time>{timeLabel(m.created_at)}{mine&&<span className="chat-read-mark"> ✓</span>}</time>
                    {!mine&&<button className="chat-report-button" type="button" onClick={async()=>{const reason=window.prompt('Why are you reporting this message?');if(reason?.trim())try{await api(`/chat/messages/${m.id}/report`,{method:'POST',body:JSON.stringify({reason:reason.trim()})});setError('Message reported to the administrator.')}catch(e:any){setError(e.message)}}}>Report</button>}
                  </div>
                </div>
              </div>
            })}
          </div>
          <form className="chat-composer chat-wa-composer" onSubmit={send}>
            <label className="chat-attach-label chat-wa-attach" title="Attach photo or document">＋<input type="file" hidden accept=".pdf,.png,.jpg,.jpeg,.webp,.docx,.xlsx,.pptx,.txt,.csv" onChange={e=>setAttachment(e.target.files?.[0]||null)}/></label>
            <div className="chat-wa-compose-field"><textarea value={draft} onChange={e=>setDraft(e.target.value)} placeholder="Message" rows={1} maxLength={10000}/>{attachment&&<small className="chat-wa-selected-file">📎 {attachment.name} <button type="button" onClick={()=>setAttachment(null)}>×</button></small>}</div>
            <button className="chat-wa-send" disabled={busy||!draft.trim()} aria-label="Send message">{busy?'…':'➤'}</button>
          </form>
        </>:<div className="chat-welcome chat-wa-welcome"><div className="chat-welcome-icon">✉</div><h2>Keep your team connected</h2><p>Select a conversation or start a new chat with an employee.</p><button onClick={()=>{setShowPeople(true);setGroupMode(false)}}>Start new chat</button></div>}
      </section>
    </div>
    <div className="chat-footnote">Messages are visible only to conversation participants and authorized system administrators.</div>
  </section>
}
