"""Full data-directory backup and restore.

A backup is just a zip of the entire data root (conversations, settings,
provider/MCP configs, the encrypted secrets blob, the Fernet key file) dropped
into `backups/` inside that same data root, named with a UTC timestamp so
backups sort chronologically and never collide.

Restore extracts a backup zip back into the data root. Because the zip can
come from an untrusted source (uploaded via the API), extraction is guarded
against zip-slip: every member's resolved path must stay inside the data
root, or the whole restore is aborted before anything is written.
"""
from __future__ import annotations

import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from local_ai_workspace.storage.paths import backups_dir, get_data_root

logger = logging.getLogger(__name__)


def create_backup() -> Path:
    """Zip the entire data directory (excluding the backups dir itself, to
    avoid backups-of-backups) into a new timestamped zip under backups/."""
    data_root = get_data_root()
    backup_dir = backups_dir()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = backup_dir / f"backup-{timestamp}.zip"

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in data_root.rglob("*"):
            if not path.is_file():
                continue
            try:
                path.relative_to(backup_dir)
                continue  # skip anything already inside backups/
            except ValueError:
                pass
            arcname = path.relative_to(data_root)
            zf.write(path, arcname)

    logger.info("Created backup: %s", dest)
    return dest


def _safe_extract_path(data_root: Path, member_name: str) -> Path:
    """Resolve a zip member's target path and ensure it stays within
    data_root, raising ValueError (zip-slip) if it would escape."""
    target = (data_root / member_name).resolve()
    data_root_resolved = data_root.resolve()
    if target != data_root_resolved and data_root_resolved not in target.parents:
        raise ValueError(f"Unsafe path in backup archive (zip-slip attempt): {member_name}")
    return target


def restore_backup(path: str | Path) -> int:
    """Extract a backup zip into the data root, overwriting existing files.

    Validates every entry stays inside the data root before writing anything
    (zip-slip protection). Returns the number of files restored.

    Raises FileNotFoundError if the archive doesn't exist, ValueError if the
    archive contains an unsafe path or isn't a valid zip.
    """
    archive_path = Path(path)
    if not archive_path.exists():
        raise FileNotFoundError(f"Backup file not found: {archive_path}")

    data_root = get_data_root()

    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            members = zf.infolist()
            # Validate every member first, so a bad entry aborts before any
            # write happens.
            targets: list[tuple[zipfile.ZipInfo, Path]] = []
            for member in members:
                target = _safe_extract_path(data_root, member.filename)
                targets.append((member, target))

            restored = 0
            for member, target in targets:
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    dst.write(src.read())
                restored += 1
    except zipfile.BadZipFile as e:
        raise ValueError(f"Not a valid backup archive: {e}") from e

    logger.info("Restored %d files from backup: %s", restored, archive_path)
    return restored


def list_backups() -> list[Path]:
    return sorted(backups_dir().glob("backup-*.zip"))
