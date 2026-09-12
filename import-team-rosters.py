"""Import official 2026-27 team rosters and profile photos safely.

Default mode is dry-run. Production writes require TARGET_SEASON, DRY_RUN=false,
ALLOW_WRITE=true, and a service-role key supplied by GitHub Actions.
"""

from __future__ import annotations

import mimetypes
import os
import sys
from pathlib import PurePosixPath

import requests
from supabase import Client, create_client

from season_config import require_target_season, write_enabled
from team_roster_source import RosterPlayer, parse_team_roster, validate_roster_set


TARGET_SEASON = require_target_season()
WRITE_ENABLED = write_enabled()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
BUCKET_NAME = os.environ.get("PLAYER_IMAGE_BUCKET", "player-images")
MAX_IMAGE_BYTES = 10 * 1024 * 1024

TEAM_SOURCES = {
    "eagles": {"url": "https://asiaicehockey.com/team/eagles/player", "english_name": "EAGLES"},
    "blades": {"url": "https://asiaicehockey.com/team/blades/player", "english_name": "FREEBLADES"},
    "icebucks": {"url": "https://asiaicehockey.com/team/icebucks/player", "english_name": "ICEBUCKS"},
    "grits": {"url": "https://asiaicehockey.com/team/grits/player", "english_name": "GRITS"},
    "stars": {"url": "https://asiaicehockey.com/team/stars/player", "english_name": "STARS"},
    "hlanyang": {"url": "https://asiaicehockey.com/team/hlanyang/player", "english_name": "HL ANYANG"},
}


def require_environment() -> None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise EnvironmentError("SUPABASE_URL and SUPABASE_KEY must be set")
    if not WRITE_ENABLED:
        return
    if os.environ.get("ALLOW_IMAGE_UPLOAD") != "true":
        raise EnvironmentError("Refusing image upload without ALLOW_IMAGE_UPLOAD=true")


def request(url: str) -> requests.Response:
    response = requests.get(url, headers={"User-Agent": "alih-batch/2026-27-roster-import"}, timeout=30)
    response.raise_for_status()
    return response


def fetch_rosters() -> list[RosterPlayer]:
    rosters: list[RosterPlayer] = []
    for team_slug, source in TEAM_SOURCES.items():
        response = request(source["url"])
        roster = parse_team_roster(response.text, team_slug)
        print(f"[SOURCE] {team_slug}: {len(roster)} official players")
        rosters.extend(roster)
    return validate_roster_set(rosters, set(TEAM_SOURCES))


def storage_path(player: RosterPlayer) -> str:
    suffix = PurePosixPath(player.photo_source_url.split("?", 1)[0]).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    return f"{TARGET_SEASON}/{player.team_slug}/{player.slug}{suffix}"


def upload_photo(supabase: Client, player: RosterPlayer) -> str:
    response = request(player.photo_source_url)
    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise RuntimeError(f"Unexpected player photo MIME type for {player.name_en}: {content_type or '(empty)'}")
    if not response.content or len(response.content) > MAX_IMAGE_BYTES:
        raise RuntimeError(f"Invalid player photo size for {player.name_en}: {len(response.content)}")

    path = storage_path(player)
    supabase.storage.from_(BUCKET_NAME).upload(
        path=path,
        file=response.content,
        file_options={"content-type": content_type, "upsert": "true", "cache-control": "31536000"},
    )
    return supabase.storage.from_(BUCKET_NAME).get_public_url(path)


def to_db_record(player: RosterPlayer, team_id: int, photo_url: str) -> dict:
    return {
        "season": TARGET_SEASON,
        "team_id": team_id,
        "name": player.name,
        "name_en": player.name_en,
        "name_ja": player.name_ja,
        "jersey_number": player.jersey_number,
        "position": player.position,
        "birth_date": player.birth_date,
        "height_cm": player.height_cm,
        "weight_kg": player.weight_kg,
        "nationality": player.nationality,
        "bio_markdown": player.bio_markdown,
        "slug": player.slug,
        "photo_url": photo_url,
    }


def import_rosters() -> None:
    require_environment()
    players = fetch_rosters()

    if not WRITE_ENABLED:
        print(f"[DRY RUN] Validated {len(players)} official {TARGET_SEASON} players and {len(players)} source photos")
        return

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    teams_result = supabase.table("alih_teams").select("id, english_name").execute()
    team_ids = {team["english_name"]: team["id"] for team in teams_result.data or []}
    if {source["english_name"] for source in TEAM_SOURCES.values()} != set(team_ids) & {source["english_name"] for source in TEAM_SOURCES.values()}:
        raise RuntimeError("One or more official roster teams are missing from alih_teams")

    records = []
    for player in players:
        team_id = team_ids[TEAM_SOURCES[player.team_slug]["english_name"]]
        photo_url = upload_photo(supabase, player)
        records.append(to_db_record(player, team_id, photo_url))

    response = supabase.table("alih_players").upsert(
        records,
        on_conflict="season,team_id,name",
    ).execute()
    if len(response.data or []) != len(records):
        raise RuntimeError(f"Roster upsert count mismatch: expected {len(records)}, received {len(response.data or [])}")
    print(f"[UPDATED] Imported {len(records)} official {TARGET_SEASON} players and photos into {BUCKET_NAME}")


if __name__ == "__main__":
    try:
        import_rosters()
    except Exception as error:
        print(error, file=sys.stderr)
        raise
