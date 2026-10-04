"""Preview uses a rolled-back transaction; confirm revalidates the file and database."""
import hashlib
import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import jwt
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from ..auth import get_current_user, record_security_event
from ..config import get_settings
from ..db import get_db, Base
from ..models import BusinessDataRevision, User, ImportBatch, QualityRejectionImportBatch
from ..services.excel_import import import_daily_production_workbook
from ..services.historical_mis_import import import_historical_daily_mis
from ..services.historical_price_import import import_historical_sales_prices
from ..services.quality_import import import_daily_rejection_workbook, import_historical_rejection_workbook
from ..services.file_security import UploadSecurityError, hash_file, safe_original_name, safe_path, save_limited_stream, validate_workbook_file
router=APIRouter(prefix='/import',tags=['import preview'])
KINDS={'daily-production','process-design','stage-schedules','stage-daily','excel','historical-daily-mis','historical-sales-prices','quality-daily','quality-history'}
KIND_SCOPED_HASHES={'daily-production','process-design','stage-schedules','stage-daily'}


def authorize(kind,user):
    if kind not in KINDS:raise HTTPException(404,'Unknown import kind')
    allowed={'QUALITY'} if kind.startswith('quality-') else {'PRODUCTION','PLANNING'} if kind=='stage-daily' else {'PLANNING'}
    if user.role.value!='ADMIN' and user.role.value not in allowed:
        raise HTTPException(403,'Import kind is outside your role')


def fingerprint(db, *, lock=False):
    if db.bind.dialect.name == 'postgresql':
        q = select(BusinessDataRevision.revision).where(BusinessDataRevision.id == 1)
        revision = db.scalar(q.with_for_update() if lock else q)
        trigger_count = db.scalar(text(
            "SELECT count(*) FROM pg_trigger "
            "WHERE tgname LIKE 'revision_%' AND NOT tgisinternal"
        )) or 0
        # Production databases upgraded by Alembic have revision triggers and use
        # the inexpensive monotonic counter. create_all/test/recovery databases do
        # not, so fall through to the conservative content hash instead of allowing
        # a stale preview to be confirmed.
        if revision is not None and trigger_count:
            return str(revision)
    h=hashlib.sha256()
    # Conservative: any relevant business/master change invalidates an earlier preview.
    exclude={'governance_audit','action_reminders','historical_correction_grants','import_batches','quality_rejection_import_batches','business_data_revision','users','user_sessions','security_events'}
    for table in sorted(Base.metadata.tables.values(),key=lambda t:t.name):
        if table.name in exclude:continue
        for row in db.execute(select(table).order_by(*table.primary_key.columns)):
            h.update(json.dumps([table.name,*row],default=str,separators=(',',':')).encode())
    return h.hexdigest()


def run_import(db,path,kind,user,batch_id=None):
    if kind=='daily-production':
        from ..services.daily_production_import import import_daily_production
        return import_daily_production(db,path)
    if kind in {'process-design','stage-schedules','stage-daily'}:
        from ..services.process_flows import import_process_workbook
        return import_process_workbook(db,path,kind)
    if kind=='excel':
        from ..models import ProcessFlowVersion
        if db.scalar(select(ProcessFlowVersion.id).limit(1)):
            return {'errors':['Explicit process flows are configured. Use Stage Daily import with stable stage codes. Historical MIS remains available separately.']}
        return import_daily_production_workbook(db,path)
    if kind=='historical-daily-mis':return import_historical_daily_mis(db,path)
    if kind=='historical-sales-prices':return import_historical_sales_prices(db,path,user.id)
    if kind=='quality-daily':return import_daily_rejection_workbook(db,path,entered_by_id=user.id,batch_id=batch_id)
    return import_historical_rejection_workbook(db,path,batch_id=batch_id)


def counts(stats,kind):
    if kind in {'daily-production','quality-daily','quality-history','process-design','stage-schedules','stage-daily'}:
        return {'new':stats.get('created',stats.get('new',0)),'updated':stats.get('updated',0),'unchanged':stats.get('unchanged',0),'rejected':len(stats.get('errors',[]))}
    prefix='price_rows' if kind=='historical-sales-prices' else 'mis'
    return {'new':stats.get(prefix+'_created',0),'updated':stats.get(prefix+'_updated',0),'unchanged':stats.get(prefix+'_unchanged',0),'rejected':len(stats.get('errors',[]))}


def digest(path):return hash_file(path)

@router.post('/preview/{kind}')
def preview(kind:str,request:Request,file:UploadFile=File(...),db:Session=Depends(get_db),user:User=Depends(get_current_user)):
    authorize(kind,user)
    settings=get_settings()
    original=safe_original_name(file.filename,'workbook.xlsx')
    ext=Path(original).suffix.lower()
    if ext not in {'.xlsx','.xlsm'}:
        raise HTTPException(422,'Use a valid .xlsx or .xlsm workbook')
    root=Path(settings.upload_dir)/'previews';root.mkdir(parents=True,exist_ok=True)
    # Remove expired temporary previews; original committed imports remain retained.
    import time
    for old in root.iterdir():
        if old.is_file() and old.stat().st_mtime<time.time()-86400:
            old.unlink(missing_ok=True)
    upload_id=uuid.uuid4().hex;path=root/(upload_id+ext)
    try:
        _,sha=save_limited_stream(file.file,path,settings.import_max_mb*1024*1024)
        validate_workbook_file(path,original,settings.office_max_uncompressed_mb*1024*1024)
    except UploadSecurityError as exc:
        path.unlink(missing_ok=True)
        record_security_event(db,request,'UPLOAD_REJECTED',success=False,user=user,detail=f'Workbook {kind}: {exc.detail}')
        db.commit()
        raise HTTPException(exc.status_code,exc.detail) from exc
    batch_sha=hashlib.sha256((kind+':'+sha).encode()).hexdigest() if kind in KIND_SCOPED_HASHES else sha
    batch_model=QualityRejectionImportBatch if kind.startswith('quality-') else ImportBatch
    previous=db.scalar(select(batch_model).where(batch_model.file_sha256==batch_sha))
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
            'count_scope':('Customer MIS rows plus stage actual rows; parent dispatch is reconciled, not added twice to MIS.' if kind=='daily-production' else 'Primary MIS, price or rejection business rows; supporting master/process counts are shown in stats.')}
    if errors:path.unlink(missing_ok=True);return result
    claims={'sub':str(user.id),'purpose':'import-preview','kind':kind,'upload_id':upload_id,'filename':original,'ext':ext,
            'sha':sha,'batch_sha':batch_sha,'fingerprint':original_fp,'exp':datetime.now(timezone.utc)+timedelta(minutes=30)}
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
    ext=claims.get('ext','.xlsx')
    if ext not in {'.xlsx','.xlsm'}:raise HTTPException(409,'Invalid preview file type')
    path=Path(get_settings().upload_dir)/'previews'/(claims['upload_id']+ext)
    if not path.is_file() or digest(path)!=claims['sha']:raise HTTPException(409,'Preview file is missing or changed')
    batch_model=QualityRejectionImportBatch if kind.startswith('quality-') else ImportBatch
    previous=db.scalar(select(batch_model).where(batch_model.file_sha256==claims.get('batch_sha',claims['sha'])))
    if previous:raise HTTPException(409,'Workbook was already confirmed')
    if fingerprint(db,lock=True)!=claims['fingerprint']:raise HTTPException(409,'Data changed after preview; preview again before confirming')
    try:
        batch=batch_model(file_name=claims['filename'],file_sha256=claims.get('batch_sha',claims['sha']),imported_by_id=user.id,status='RUNNING')
        if kind.startswith('quality-'):batch.import_type='DAILY' if kind=='quality-daily' else 'HISTORICAL'
        db.add(batch);db.flush()
        stats=run_import(db,path,kind,user,batch.id if kind.startswith('quality-') else None)
        if stats.get('errors'):raise HTTPException(422,stats['errors'])
        stats['import_kind']=kind;stats['file_sha256']=claims['sha']
        batch.status='COMPLETED';batch.stats_json=json.dumps(stats,default=str)
        db.commit();db.refresh(batch)
    except HTTPException:db.rollback();raise
    except Exception as exc:db.rollback();raise HTTPException(422,f'Import failed: {exc}') from exc
    # Retain the confirmed workbook outside the expiring previews directory.
    target=safe_path(get_settings().upload_dir,claims['upload_id']+'_'+safe_original_name(claims['filename'],'workbook.xlsx'))
    shutil.move(str(path),str(target))
    return {'status':'imported','import_batch_id':batch.id,'counts':counts(stats,kind),'message':'Preview confirmed; all rows committed together','stats':stats}
