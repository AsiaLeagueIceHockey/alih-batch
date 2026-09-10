import os
import re


def require_target_season() -> str:
    season = os.environ.get("TARGET_SEASON")
    if not season or not re.fullmatch(r"\d{4}-\d{2}", season):
        raise EnvironmentError("TARGET_SEASON must be an explicit YYYY-YY value")
    return season


def write_enabled() -> bool:
    dry_run = os.environ.get("DRY_RUN", "true").lower() != "false"
    allow_write = os.environ.get("ALLOW_WRITE") == "true"
    if not dry_run and not allow_write:
        raise EnvironmentError("Refusing DB write without ALLOW_WRITE=true")
    return not dry_run


def season_marker(season: str) -> str:
    start_year, end_suffix = season.split("-")
    return f"{start_year}-{start_year[:2]}{end_suffix}"
