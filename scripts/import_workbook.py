#!/usr/bin/env python3
"""CLI helper for importing an existing Daily Production Review workbook."""
import argparse
import os
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))

from app.db import Base, SessionLocal, engine
from app.seed import seed_defaults
from app.services.excel_import import import_daily_production_workbook

p=argparse.ArgumentParser()
p.add_argument('workbook')
args=p.parse_args()
Base.metadata.create_all(engine)
with SessionLocal() as db:
    seed_defaults(db)
    print(import_daily_production_workbook(db,args.workbook))
