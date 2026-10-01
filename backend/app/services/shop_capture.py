"""Local OCR and conservative report parsing. Source text is never silently corrected."""
import re
import subprocess
import tempfile
from datetime import date
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import HTTPException

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 16_000_000


def read_image(data: bytes):
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, 'Image limit is 15 MB')
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format not in {'PNG', 'JPEG', 'WEBP'} or source.width * source.height > MAX_PIXELS:
                raise ValueError('Unsupported format or image too large')
            source.load()
            image = ImageOps.exif_transpose(source).convert('RGB')
        output = BytesIO()
        image.save(output, format='PNG')
        return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, 'Use a valid PNG, JPG or WebP image up to 16 megapixels') from exc


def ocr_image(png: bytes):
    with tempfile.TemporaryDirectory(prefix='shop-ocr-') as tmp:
        path = Path(tmp) / 'report.png'
        path.write_bytes(png)
        try:
            result = subprocess.run(['tesseract', str(path), 'stdout', '-l', 'eng', '--psm', '6'],
                                    capture_output=True, text=True, timeout=45, check=True)
        except FileNotFoundError as exc:
            raise HTTPException(503, 'OCR engine unavailable. Rebuild the backend image with this update.') from exc
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            raise HTTPException(422, 'OCR could not read this image. Try a clear cropped screenshot.') from exc
        text = result.stdout.strip()
        if len(text) > 50000:
            raise HTTPException(422, 'Too much text; split the report into smaller images')
        return text


def parse_report(text: str, pair_order: str = 'unknown'):
    rows = []
    cell = group = lt = ''
    for index, raw in enumerate(text.splitlines()):
        line = raw.replace('*', '').strip()
        if not line:
            continue
        if re.fullmatch(r'M[12]\s*Cell', line, re.I):
            cell = line
            continue
        if re.match(r'(Grab|Block)\s+production', line, re.I):
            group = line.split()[0]
        match = re.match(r'(\d)\)\s*LT', line, re.I)
        if match:
            lt = match[1]
        pair = re.match(r'^(.*?)\s+(\d+)\s*:\s*(\d+)(.*)$', line)
        equal = re.match(r'^(.+?)\s*=\s*(.*)$', line)
        row = dict(source_line=index + 1, source_text=raw, label=line, product_hint=group,
                   actual=None, target=None, warnings=[], splits=[], disposition='pending',
                   machine_id=None, product_id=None, route_operation_id=None,
                   shift_duration_min=None, planned_break_min=None, downtime_min=None,
                   good_count=None, ideal_cycle_time_sec=None, reason='')
        values = None
        if pair:
            parts = re.split(r'\s*-\s*', pair[1].rstrip('- '), maxsplit=1)
            row['label'] = (cell + ' / ' if cell else '') + parts[0]
            row['product_hint'] = parts[1] if len(parts) > 1 else ''
            values = (int(pair[2]), int(pair[3]))
            row['splits'] = [dict(product=m[0], quantity=int(m[1])) for m in re.findall(r',\s*([\w]+)\s*-\s*(\d+)', pair[4])]
        elif equal:
            row['label'] = equal[1].strip()
            if re.search(r'LT\s+(OK|NOK)', row['label'], re.I) and lt:
                row['label'] = 'LT ' + lt + ' / ' + re.sub(r'^\d\)\s*', '', row['label'])
            value = equal[2].strip()
            slash = re.match(r'^(\d+)\s*/\s*(\d+)(?:\s|$|\()', value)
            if slash:
                values = (int(slash[1]), int(slash[2]))
            elif re.match(r'^\d+(?:\s|$|\()', value):
                row['actual'] = int(re.match(r'^\d+', value)[0])
            else:
                row['warnings'].append('Missing quantity' if not value else 'Text / operator assignment; quantity unconfirmed')
        else:
            row['warnings'].append('Unparsed source line; retain for review')
        if values:
            if pair_order == 'unknown':
                row['warnings'].append(f'Confirm pair order: {values[0]} / {values[1]}')
            else:
                row['target'], row['actual'] = values if pair_order == 'target-actual' else values[::-1]
        if row['splits']:
            row['warnings'].append('Mixed-product total: keep pending until separate run times are available')
            if row['actual'] is not None and sum(x['quantity'] for x in row['splits']) != row['actual']:
                row['warnings'].append('Product split does not match total')
        if re.search(r'rework|chamfer|champer', line, re.I):
            row['warnings'].append('Confirm fresh quantity separately from rework / other operations')
        if re.search(r'no plan', line, re.I) and values:
            row['warnings'].append('Resolve target versus no-plan remark')
        rows.append(row)
    day = re.search(r'(\d{2})/(\d{2})/(\d{4})', text)
    report_date = ''
    if day:
        try:
            report_date = date(int(day[3]), int(day[2]), int(day[1])).isoformat()
        except ValueError:
            pass
    hours = re.search(r'(\d+)\s*hours', text, re.I)
    return dict(text=text, pair_order=pair_order, plant='', shop='', production_date=report_date,
                shift='1st shift' if re.search(r'1st\s+shift', text, re.I) else '',
                stated_hours=int(hours[1]) if hours else None, rows=rows)
