        path = Path(os.getenv("AI_TRACE_LOG_PATH", "/app/data/ai_trace.log"))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=4, encoding="utf-8", delay=False)
            # Full prompts and model responses can contain medical data. Restrict the
            # active log to the service account (owner read/write only).
            try:
                os.chmod(path, 0o600)
            except OSError: