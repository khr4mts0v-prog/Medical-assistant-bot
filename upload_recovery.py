"""Safe cleanup helpers for staged document uploads."""
from pathlib import Path


def cleanup_unqueued_upload(staged_path, sidecar_path, queued):
    """Delete temporary artifacts only when the upload was not queued.

    Once queued, the encrypted staged file and its sidecar are recovery state;
    deleting either can make /retry_save impossible after a later exception.
    Returns True when cleanup was attempted, False when artifacts were retained.
    """
    if queued:
        return False
    for value in (staged_path, sidecar_path):
        try:
            Path(value).unlink(missing_ok=True)
        except OSError:
            # Cleanup is best-effort; the original processing error is primary.
            pass
    return True
