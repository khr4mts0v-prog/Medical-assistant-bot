def detect_intent(text: str) -> str:
    t = text.lower()

    if any(w in t for w in ["найди", "покажи", "достань"]):
        return "search"

    if any(w in t for w in ["что", "почему", "есть ли", "проанализируй"]):
        return "question"

    if any(w in t for w in ["загрузи", "добавь"]):
        return "upload"

    return "unknown"
