import re
from rapidfuzz import fuzz
from datetime import datetime

def normalize_name(text: str):
    return re.sub(r"[^а-яё]", "", text.lower()).capitalize()

def extract_date_from_text(text: str):
    match = re.search(r"\d{2}[.\-/]\d{2}[.\-/]\d{4}", text)
    if match:
        return match.group(0).replace(".", "-").replace("/", "-")
    return None

def is_duplicate(doc, docs):
    for d in docs:
        if d["type"] == doc["type"] and d["date"] == doc["date"]:
            score = fuzz.token_set_ratio(
                " ".join(d["keywords"]),
                " ".join(doc["keywords"])
            )
            if score > 40:
                return True
    return False
