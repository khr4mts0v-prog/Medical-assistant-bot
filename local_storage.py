"""Local file storage scoped by family and patient; files stay under DATA_ROOT."""
import os
from pathlib import Path
from utils import safe_name

DATA_ROOT = Path(os.getenv("LOCAL_STORAGE_PATH", "/app/data/documents")).resolve()

def _component(value: str) -> str:
    # safe_name is app-defined; additionally reject empty and dot-like components.
    result = safe_name(str(value or "")).strip(". ")
    if not result or result in {".", ".."}:
        raise ValueError("Invalid storage path component")
    return result[:120]

def document_dir(family_id: int, patient: str) -> Path:
    fid = int(family_id)
    if fid <= 0:
        raise ValueError("Invalid family id")
    root = DATA_ROOT
    target = (root / f"family_{fid}" / _component(patient)).resolve()
    if root != target and root not in target.parents:
        raise ValueError("Storage path escapes local storage root")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        target.chmod(0o700)
    except OSError:
        pass
    return target

def save_file(family_id: int, patient: str, filename: str, source: Path) -> Path:
    name = Path(filename).name
    if name != filename or name in {"", ".", ".."}:
        raise ValueError("Invalid filename")
    target_dir = document_dir(family_id, patient)
    target = (target_dir / name).resolve()
    if target_dir.resolve() not in target.parents:
        raise ValueError("Storage path escapes patient directory")
    # Exclusive creation avoids silently overwriting an existing original.
    # Once xb succeeds, this invocation owns the new path. Clean it up on any
    # subsequent failure, including source/destination close errors. Never
    # unlink a path when exclusive creation itself failed.
    created = False
    try:
        with source.open("rb") as src:
            dst = target.open("xb")
            created = True
            with dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
    except BaseException:
        if created:
            # Preserve the original I/O exception even if cleanup also fails.
            try:
                target.unlink()
            except OSError:
                pass
        raise
    try:
        target.chmod(0o600)
    except OSError:
        # Do not leave a potentially over-permissive medical file behind when
        # private permissions cannot be enforced.
        try:
            target.unlink()
        except OSError:
            pass
        raise
    return target
