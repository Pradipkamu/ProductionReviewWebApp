import { useEffect, useRef, useState } from 'react'

type AppError = {
  message: string
  status?: number
  path?: string
  details?: string
}

export default function GlobalErrorModal() {
  const [error, setError] = useState<AppError | null>(null)
  const [showDetails, setShowDetails] = useState(false)
  const lastKey = useRef('')

  useEffect(() => {
    const onError = (event: Event) => {
      const detail = (event as CustomEvent).detail || {}
      const next: AppError = {
        message: typeof detail.message === 'string' && detail.message.trim()
          ? detail.message
          : 'The request could not be completed. Please try again.',
        status: typeof detail.status === 'number' ? detail.status : undefined,
        path: typeof detail.path === 'string' ? detail.path : undefined,
        details: typeof detail.details === 'string' ? detail.details : undefined,
      }
      const key = [next.message, next.status, next.path].join('|')
      if (key === lastKey.current && error) return
      lastKey.current = key
      setShowDetails(false)
      setError(next)
    }
    window.addEventListener('app:api-error', onError)
    return () => window.removeEventListener('app:api-error', onError)
  }, [error])

  useEffect(() => {
    if (!error) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [error])

  function close() {
    setError(null)
    lastKey.current = ''
    setShowDetails(false)
  }

  if (!error) return null
  const statusLabel = error.status ? `HTTP ${error.status}` : 'Request error'

  return <div role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) close() }}
    style={{position:'fixed',inset:0,zIndex:3000,background:'rgba(15,23,42,.58)',display:'grid',placeItems:'center',padding:20}}>
    <section role="alertdialog" aria-modal="true" aria-labelledby="app-error-title" aria-describedby="app-error-message"
      style={{width:'min(520px,100%)',background:'var(--panel, #fff)',color:'var(--text, #172033)',border:'1px solid var(--border, #d7deea)',borderRadius:16,boxShadow:'0 24px 80px rgba(0,0,0,.28)',overflow:'hidden'}}>
      <div style={{display:'flex',alignItems:'center',gap:12,padding:'18px 20px',borderBottom:'1px solid var(--border, #d7deea)'}}>
        <span aria-hidden="true" style={{width:38,height:38,borderRadius:12,display:'grid',placeItems:'center',background:'#fee2e2',color:'#b91c1c',fontSize:22,fontWeight:800}}>!</span>
        <div style={{flex:1,minWidth:0}}>
          <h2 id="app-error-title" style={{margin:0,fontSize:18}}>Unable to complete request</h2>
          <span style={{fontSize:12,color:'var(--muted, #64748b)'}}>{statusLabel}</span>
        </div>
        <button type="button" className="secondary small" onClick={close} aria-label="Close error dialog">✕</button>
      </div>
      <div style={{padding:'20px'}}>
        <p id="app-error-message" style={{margin:'0 0 14px',lineHeight:1.55,overflowWrap:'anywhere'}}>{error.message}</p>
        {(error.path || error.details) && <div style={{marginBottom:14}}>
          <button type="button" className="secondary small" onClick={()=>setShowDetails(value=>!value)} aria-expanded={showDetails}>
            {showDetails ? 'Hide technical details' : 'View technical details'}
          </button>
          {showDetails && <pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere',maxHeight:180,overflow:'auto',padding:12,marginTop:10,borderRadius:8,background:'var(--panel-soft, #f3f6fa)',fontSize:12}}>
            {[error.path && `Request: ${error.path}`,error.details].filter(Boolean).join('\n')}
          </pre>}
        </div>}
        <div style={{display:'flex',justifyContent:'flex-end'}}>
          <button type="button" onClick={close}>Close</button>
        </div>
      </div>
    </section>
  </div>
}
