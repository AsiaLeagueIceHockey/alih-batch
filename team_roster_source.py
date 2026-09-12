"""Pure parser for the official 2026-27 team roster pages."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

from bs4 import BeautifulSoup


POSITIONS = {"GK", "DF", "FW"}
OFFICIAL_CDN_PREFIX = "https://cdn.asiaicehockey.com/"


@dataclass(frozen=True)
class RosterPlayer:
    team_slug: str
    position: str
    jersey_number: int
    name_ja: str
    name_en: str
    photo_source_url: str
    birth_date: str | None
    height_cm: int | None
    weight_kg: int | None
    nationality: str | None
    bio_markdown: str | None

    @property
    def name(self) -> str:
        return self.name_en or self.name_ja

    @property
    def slug(self) -> str:
        ascii_name = unicodedata.normalize("NFKD", self.name_en).encode("ascii", "ignore").decode().lower()
        ascii_name = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")
        if not ascii_name:
            ascii_name = hashlib.sha256(self.name_ja.encode("utf-8")).hexdigest()[:10]
        return f"{self.team_slug}-{self.jersey_number}-{ascii_name}"


def _parse_date(value: str) -> str | None:
    match = re.search(r"(\d{4})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})", value)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    if not 1900 <= year <= 2100 or not 1 <= month <= 12 or not 1 <= day <= 31:
        raise ValueError(f"Invalid birth date: {value}")
    return f"{year:04d}-{month:02d}-{day:02d}"


def _parse_profile(body: str) -> tuple[str | None, int | None, int | None, str | None]:
    birth_date = _parse_date(body)
    height_match = re.search(r"身長\s*[:：]\s*(\d+)\s*cm", body, re.IGNORECASE)
    weight_match = re.search(r"体重\s*[:：]\s*(\d+)\s*kg", body, re.IGNORECASE)
    nationality_match = re.search(r"国籍\s*[:：]\s*([^\n]+)", body)
    return (
        birth_date,
        int(height_match.group(1)) if height_match else None,
        int(weight_match.group(1)) if weight_match else None,
        nationality_match.group(1).strip() if nationality_match else None,
    )


def parse_team_roster(html: str, team_slug: str) -> list[RosterPlayer]:
    soup = BeautifulSoup(html, "html.parser")
    players: list[RosterPlayer] = []

    for section_title in soup.find_all("h4"):
        position = section_title.get_text(" ", strip=True).split(" ", 1)[0].upper()
        if position not in POSITIONS:
            continue

        grid = section_title.find_next_sibling("div")
        if grid is None:
            raise ValueError(f"Missing player grid for {team_slug} {position}")

        for card in grid.select("div.uk-card"):
            image = card.find("img")
            number = card.select_one("p.uk-text-large")
            japanese_name = card.select_one("h3.uk-card-title")
            english_name = card.select_one("p.uk-text-meta")
            body = card.select_one("div.uk-card-body")

            if not image or not number or not japanese_name or not english_name:
                raise ValueError(f"Incomplete roster card for {team_slug} {position}")

            source_url = image.get("data-src") or image.get("src")
            if not source_url or not source_url.startswith(OFFICIAL_CDN_PREFIX):
                raise ValueError(f"Roster image is not from the official CDN: {source_url or '(empty)'}")

            try:
                jersey_number = int(number.get_text(" ", strip=True))
            except ValueError as error:
                raise ValueError(f"Invalid jersey number for {team_slug}: {number.get_text(' ', strip=True)}") from error

            profile_text = body.get_text("\n", strip=True) if body else ""
            birth_date, height_cm, weight_kg, nationality = _parse_profile(profile_text)
            players.append(RosterPlayer(
                team_slug=team_slug,
                position=position,
                jersey_number=jersey_number,
                name_ja=japanese_name.get_text(" ", strip=True),
                name_en=english_name.get_text(" ", strip=True),
                photo_source_url=source_url,
                birth_date=birth_date,
                height_cm=height_cm,
                weight_kg=weight_kg,
                nationality=nationality,
                bio_markdown=profile_text or None,
            ))

    if not players:
        raise ValueError(f"No roster players found for {team_slug}")

    jersey_numbers = [player.jersey_number for player in players]
    if len(jersey_numbers) != len(set(jersey_numbers)):
        raise ValueError(f"Duplicate jersey number found for {team_slug}")
    return players


def validate_roster_set(rosters: Iterable[RosterPlayer], expected_team_slugs: set[str]) -> list[RosterPlayer]:
    players = list(rosters)
    teams = {player.team_slug for player in players}
    if teams != expected_team_slugs:
        raise ValueError(f"Expected roster teams {sorted(expected_team_slugs)}, received {sorted(teams)}")
    if len(players) < 100:
        raise ValueError(f"Roster source is unexpectedly small: {len(players)} players")
    if len({(player.team_slug, player.jersey_number) for player in players}) != len(players):
        raise ValueError("Duplicate team/jersey pair in roster source")
    if any(not player.name_en for player in players):
        raise ValueError("Official roster is missing an English player name")
    return players
