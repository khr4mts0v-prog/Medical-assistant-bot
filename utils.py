import datetime
import re
from pathlib import Path

def safe_name(value, limit=80):
    value = re.sub(r"[^\w.-]+", "_", (value or "").strip(), flags=re.UNICODE)
    return re.sub(r"_+", "_", value).strip("._-")[:limit] or "document"

def format_filename(patient_name, doc_type, date_str, extension):
    ext = (Path(extension or "").suffix or extension or "bin").lstrip(".").lower()
    return f"{safe_name(patient_name,45)}_{safe_name(doc_type,45)}_{safe_name(date_str or 'date-unknown',20)}.{ext}"

def normalize_extension(filename):
    return Path(filename or "").suffix.lower().lstrip(".") or "bin"

def parse_date_from_text(text):
    patterns = [
        r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\b",
        r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2})\b",
        r"\b(\d{4})-(\d{2})-(\d{2})\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text or ""):
            a,b,c = match.groups()
            try:
                if len(a)==4: year,month,day=map(int,(a,b,c))
                else:
                    day,month,year=map(int,(a,b,c))
                    if year<100: year+=2000
                return datetime.date(year,month,day).strftime("%d-%m-%Y")
            except ValueError:
                pass
    return "не определена"
