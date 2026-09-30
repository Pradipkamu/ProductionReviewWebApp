#!/usr/bin/env python3
"""API-only import helper: preview first, optionally confirm; never writes DB directly."""
import argparse
import getpass
import json
import os
import urllib.request
import urllib.error
import uuid
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('workbook',type=Path)
p.add_argument('--kind',default='excel',choices=['excel','historical-daily-mis','historical-sales-prices','quality-daily','quality-history'])
p.add_argument('--api',default='http://localhost:8000/api')
p.add_argument('--username',default='admin')
p.add_argument('--confirm',action='store_true',help='Confirm the reviewed preview in this invocation')
p.add_argument('--reason',default='')
p.add_argument('--correction-id',default='')
args=p.parse_args()


def call(path,data,headers):
    req=urllib.request.Request(args.api.rstrip('/')+path,data=data,headers=headers,method='POST')
    try:
        with urllib.request.urlopen(req,timeout=300) as response:return json.load(response)
    except urllib.error.HTTPError as exc:
        raise SystemExit(exc.read().decode()) from exc


token=os.environ.get('PMS_API_TOKEN')
if not token:
    result=call('/auth/login',json.dumps({'username':args.username,'password':getpass.getpass('Password: ')}).encode(),{'Content-Type':'application/json'})
    if result['user'].get('must_change_password'):raise SystemExit('Change initial password in the web app first.')
    token=result['access_token']
headers={'Authorization':'Bearer '+token}
if args.reason:headers['X-Change-Reason']=args.reason
if args.correction_id:headers['X-Correction-ID']=args.correction_id
boundary=uuid.uuid4().hex
name=args.workbook.name.replace('"','').replace('\r','').replace('\n','')
body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n'.encode()+args.workbook.read_bytes()+f'\r\n--{boundary}--\r\n'.encode())
result=call('/import/preview/'+args.kind,body,{**headers,'Content-Type':'multipart/form-data; boundary='+boundary})
print(json.dumps({k:v for k,v in result.items() if k!='preview_token'},indent=2,default=str))
if args.confirm and result.get('can_confirm'):
    confirmed=call('/import/confirm',json.dumps({'preview_token':result['preview_token']}).encode(),{**headers,'Content-Type':'application/json'})
    print(json.dumps(confirmed,indent=2,default=str))
