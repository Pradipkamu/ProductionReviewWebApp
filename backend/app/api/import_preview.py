"""Preview uses a rolled-back transaction; confirm revalidates the file and database."""
import hashlib
import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import jwt
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from ..auth import get_current_user
from ..config import get_settings
from ..db import get_db, Base
from ..models import User, ImportBatch, QualityRejectionImportBatch
from ..services.excel_import import import_daily_production_workbook
from ..services.historical_mis_import import import_historical_daily_mis
from ..services.historical_price_import import import_historical_sales_prices
from ..services.quality_import import import_daily_rejection_workbook, import_historical_rejection_workbook
router=APIRouter(prefix='/import',tags=['import preview'])
KINDS={'excel','historical-daily-mis','historical-sales-prices','quality-daily','quality-history'}


def authorize(kind,user):
    if kind not in KINDS:raise HTTPException(404,'Unknown import kind')
    if user.role.value!='ADMIN' and user.role.value!=('QUALITY' if kind.startswith('quality-') else 'PLANNING'):
        raise HTTPException(403,'Import kind is outside your role')


def fingerprint(db):
    h=hashlib.sha256()
    # Conservative: any relevant business/master change invalidates an earlier preview.
    exclude={'governance_audit','action_reminders','historical_correction_grants','import_batches','quality_rejection_import_batches'}
    for table in sorted(Base.metadata.tables.values(),key=lambda t:t.name):
        if table.name in exclude:continue
        for row in db.execute(select(table).order_by(*table.primary_key.columns)):
            h.update(json.dumps([table.name,*row],default=str,separators=(',',':')).encode())
    return h.hexdigest()


def run_import(db,path,kind,user,batch_id=None):
    if kind=='excel':return import_daily_production_workbook(db,path)
    if kind=='historical-daily-mis':return import_historical_daily_mis(db,path)
    if kind=='historical-sales-prices':return import_historical_sales_prices(db,path,user.id)
    if kind=='quality-daily':return import_daily_rejection_workbook(db,path,entered_by_id=user.id,batch_id=batch_id)
    return import_historical_rejection_workbook(db,path,batch_id=batch_id)


def counts(stats,kind):
    if kind in {'quality-daily','quality-history'}:
        return {'new':stats.get('created',0),'updated':stats.get('updated',0),'unchanged':stats.get('unchanged',0),'rejected':len(stats.get('errors',[]))}
    prefix='price_rows' if kind=='historical-sales-prices' else 'mis'
    return {'new':stats.get(prefix+'_created',0),'updated':stats.get(prefix+'_updated',0),'unchanged':stats.get(prefix+'_unchanged',0),'rejected':len(stats.get('errors',[]))}


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

@router.post('/preview/{kind}')
def preview(kind:str,file:UploadFile=File(...),db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    authorize(kind,user)
    if not file.filename or not file.filename.lower().endswith(('.xlsx','.xlsm')):raise HTTPException(422,'Use .xlsx or .xlsm')
    root=Path(get_settings().upload_dir)/'previews';root.mkdir(parents=True,exist_ok=True)
    # Remove expired temporary previews; original committed imports remain retained.
    import time
    for old in root.glob('*.xlsx'):
        if old.stat().st_mtime<time.time()-86400:old.unlink(missing_ok=True)
    upload_id=uuid.uuid4().hex;path=root/(upload_id+'.xlsx')
    size=0
    with path.open('wb') as output:
        while chunk:=file.file.read(1024*1024):
            size+=len(chunk)
            if size>32*1024*1024:path.unlink(missing_ok=True);raise HTTPException(413,'Workbook limit is 32 MB')
            output.write(chunk)
    sha=digest(path)
    batch_model=QualityRejectionImportBatch if kind.startswith('quality-') else ImportBatch
    previous=db.scalar(select(batch_model).where(batch_model.file_sha256==sha))
    if previous:
        path.unlink(missing_ok=True)
        return {'status':'already_imported','import_batch_id':previous.id,'counts':{'new':0,'updated':0,'unchanged':0,'rejected':0},'message':'Exact workbook already imported'}
    from ..services.import_validation import validate_historical_rows
    errors=validate_historical_rows(db,path,kind)
    if errors:
        path.unlink(missing_ok=True)
        return {'status':'rejected','counts':{'new':0,'updated':0,'unchanged':0,'rejected':len(set(x.split(':')[0] for x in errors))},'errors':errors,'warnings':[],'can_confirm':False}
    original_fp=fingerprint(db)
    try:
        stats=run_import(db,path,kind,user)
        db.flush()
    except Exception as exc:
        db.rollback();path.unlink(missing_ok=True)
        return {'status':'rejected','counts':{'new':0,'updated':0,'unchanged':0,'rejected':1},'errors':[str(getattr(exc,'detail',exc))], 'warnings':[], 'can_confirm':False}
    finally:
        db.rollback()
        db.info.pop('grant_in_use',None)
    c=counts(stats,kind);errors=stats.get('errors',[])
    result={'status':'preview','counts':c,'errors':errors,'warnings':stats.get('warnings',[]),'stats':stats,'can_confirm':not errors,
            'count_scope':'Primary MIS, price or rejection business rows; supporting master/process counts are shown in stats.'}
    if errors:path.unlink(missing_ok=True);return result
    claims={'sub':str(user.id),'purpose':'import-preview','kind':kind,'upload_id':upload_id,'filename':Path(file.filename).name,
            'sha':sha,'fingerprint':original_fp,'exp':datetime.now(timezone.utc)+timedelta(minutes=30)}
    result['preview_token']=jwt.encode(claims,get_settings().secret_key,algorithm='HS256')
    return result

class Confirm(BaseModel):
    preview_token:str

@router.post('/confirm')
def confirm(payload:Confirm,db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    try:
        claims=jwt.decode(payload.preview_token,get_settings().secret_key,algorithms=['HS256'])
        if claims.get('purpose')!='import-preview' or claims['sub']!=str(user.id):raise ValueError('Wrong user')
        uuid.UUID(claims['upload_id'])
    except Exception as exc:raise HTTPException(409,'Invalid or expired preview; preview workbook again') from exc
    kind=claims['kind'];authorize(kind,user)
    if db.bind.dialect.name=='postgresql':db.execute(text('SELECT pg_advisory_xact_lock(2163001)'))
    path=Path(get_settings().upload_dir)/'previews'/(claims['upload_id']+'.xlsx')
    if not path.is_file() or digest(path)!=claims['sha']:raise HTTPException(409,'Preview file is missing or changed')
    batch_model=QualityRejectionImportBatch if kind.startswith('quality-') else ImportBatch
    previous=db.scalar(select(batch_model).where(batch_model.file_sha256==claims['sha']))
    if previous:raise HTTPException(409,'Workbook was already confirmed')
    if fingerprint(db)!=claims['fingerprint']:raise HTTPException(409,'Data changed after preview; preview again before confirming')
    try:
        batch=batch_model(file_name=claims['filename'],file_sha256=claims['sha'],imported_by_id=user.id,status='RUNNING')
        if kind.startswith('quality-'):batch.import_type='DAILY' if kind=='quality-daily' else 'HISTORICAL'
        db.add(batch);db.flush()
        stats=run_import(db,path,kind,user,batch.id if kind.startswith('quality-') else None)
        if stats.get('errors'):raise HTTPException(422,stats['errors'])
        batch.status='COMPLETED';batch.stats_json=json.dumps(stats,default=str)
        db.commit();db.refresh(batch)
    except HTTPException:db.rollback();raise
    except Exception as exc:db.rollback();raise HTTPException(422,f'Import failed: {exc}') from exc
    # Retain the confirmed workbook outside the expiring previews directory.
    target=Path(get_settings().upload_dir)/(claims['upload_id']+'_'+claims['filename'])
    shutil.move(str(path),str(target))
    return {'status':'imported','import_batch_id':batch.id,'counts':counts(stats,kind),'message':'Preview confirmed; all rows committed together','stats':stats}
