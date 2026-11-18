"""Create a verified SQLite snapshot at a new path without modifying the source."""

import argparse
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic


def migrate_database(source: Path, destination: Path, *, allow_existing_violations: bool = False) -> int:
    source = source.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Destination already exists; choose a new path.")

    deadline = monotonic() + 120

    def check_deadline(status: int, remaining: int, total: int) -> None:
        if monotonic() > deadline:
            raise TimeoutError("SQLite backup timed out; stop writers and retry.")

    with NamedTemporaryFile(dir=destination.parent, suffix=".db", delete=False) as file:
        temporary = Path(file.name)
    try:
        with (
            closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original,
            closing(sqlite3.connect(temporary)) as snapshot,
        ):
            original.execute("BEGIN")
            existing_violations = set(original.execute("PRAGMA foreign_key_check"))
            if existing_violations and not allow_existing_violations:
                raise ValueError(
                    "Source already contains foreign-key violations. Review the source or use "
                    "--allow-existing-foreign-key-violations to preserve them explicitly."
                )
            original.backup(snapshot, pages=512, progress=check_deadline)
            if snapshot.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Database integrity check failed.")
            if set(snapshot.execute("PRAGMA foreign_key_check")) != existing_violations:
                raise ValueError("Foreign-key relationships changed during the copy.")
            tables = {name for name, in snapshot.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
            if not {"accounts", "assets"} <= tables:
                raise ValueError("Source does not contain the expected HIVE portfolio tables.")
            snapshot.execute("PRAGMA journal_mode=DELETE")
        # Publish the verified copy with no overwrite, including if another caller races us.
        if os.name == "nt":
            temporary.rename(destination)
        else:
            destination.hardlink_to(temporary)
        return len(existing_violations)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Path to your existing SQLite database")
    parser.add_argument("destination", type=Path, help="New database path")
    parser.add_argument("--allow-existing-foreign-key-violations", action="store_true")
    args = parser.parse_args()
    try:
        violations = migrate_database(args.source, args.destination, allow_existing_violations=args.allow_existing_foreign_key_violations)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"HIVE migration failed: {error}\n")
    print("HIVE database snapshot verified. The original database remains in place.")
    if violations:
        print(f"Warning: {violations} pre-existing foreign-key violations were preserved unchanged.")


if __name__ == "__main__":
    main()
