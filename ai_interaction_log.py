    """Store only the user prompt and final visible answer, encrypted at rest."""
    try:
        tenancy.init()
        payload = json.dumps({"query": str(query or "")[:1200], "answer": str(answer or "")}, ensure_ascii=False).encode("utf-8")
        encrypted = tenancy.cipher().encrypt(payload)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with tenancy.connect() as conn: