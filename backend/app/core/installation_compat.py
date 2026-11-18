from pathlib import Path

from pydantic import AliasChoices

# Remove after installations have switched settings and backed up their database.
PREVIOUS_PREFIX = "HEDGELAB_"


def migrated_setting(name: str) -> AliasChoices:
    return AliasChoices(name, PREVIOUS_PREFIX + name.removeprefix("HIVE_"))


def require_database_choice(default_path: Path, database_url: str) -> None:
    previous_path = default_path.with_name(PREVIOUS_PREFIX.removesuffix("_").lower() + ".db")
    if database_url == f"sqlite:///{default_path.as_posix()}" and not default_path.exists() and previous_path.is_file():
        raise ValueError(
            "An existing database needs an explicit DATABASE_URL or a verified copy at the HIVE default. "
            "See the README migration instructions."
        )
