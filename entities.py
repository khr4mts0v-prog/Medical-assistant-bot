import re

def extract_entities(text: str) -> dict:
    t = text.lower()
    entities = {}

    if "экг" in t or "эгк" in t:
        entities["type"] = "ЭКГ"
    if "ээг" in t:
        entities["type"] = "ЭЭГ"

    year = re.search(r"(20\d{2})", t)
    if year:
        entities["year"] = year.group(1)

    for name in ["генри", "макс", "анна"]:
        if name in t:
            entities["patient"] = name.capitalize()

    return entities
