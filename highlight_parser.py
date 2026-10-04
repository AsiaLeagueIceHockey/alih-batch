import re
from datetime import date


# YouTube title aliases -> alih_teams.english_name
YOUTUBE_TO_DB_TEAM_MAP = {
    "hl anyang": "HL ANYANG",
    "hl안양": "HL ANYANG",
    "hl 안양": "HL ANYANG",
    "안양": "HL ANYANG",
    "안양한라": "HL ANYANG",
    "nikko icebucks": "ICEBUCKS",
    "닛코 아이스벅스": "ICEBUCKS",
    "아이스벅스": "ICEBUCKS",
    "닛코": "ICEBUCKS",
    "tohoku freeblades": "FREEBLADES",
    "tohoku free blades": "FREEBLADES",
    "도호쿠 프리블레이즈": "FREEBLADES",
    "프리블레이즈": "FREEBLADES",
    "stars kobe": "STARS",
    "스타즈 고베": "STARS",
    "고베": "STARS",
    "yokohama grits": "GRITS",
    "요코하마 grits": "GRITS",
    "요코하마 그리츠": "GRITS",
    "그리츠": "GRITS",
    "red eagles hokkaido": "EAGLES",
    "red eagles": "EAGLES",
    "홋카이도 레드이글스": "EAGLES",
    "레드이글스 홋카이도": "EAGLES",
    "레드이글스": "EAGLES",
    "anyang": "HL ANYANG",
    "icebucks": "ICEBUCKS",
    "ice bucks": "ICEBUCKS",
    "freeblades": "FREEBLADES",
    "free blades": "FREEBLADES",
    "kobe": "STARS",
    "stars": "STARS",
    "grits": "GRITS",
    "eagles": "EAGLES",
}


def normalize_team_name(name: str) -> str:
    """Convert a team alias from a YouTube title to the DB English name."""
    normalized = re.sub(r"\s+", " ", name.casefold()).strip(" .|-")

    if normalized in YOUTUBE_TO_DB_TEAM_MAP:
        return YOUTUBE_TO_DB_TEAM_MAP[normalized]

    # Prefer longer aliases so generic tokens such as "stars" do not win first.
    for alias in sorted(YOUTUBE_TO_DB_TEAM_MAP, key=len, reverse=True):
        if alias in normalized:
            return YOUTUBE_TO_DB_TEAM_MAP[alias]

    return name.strip()


def is_highlight_video(title: str) -> bool:
    title_lower = title.casefold()
    return "highlight" in title_lower or "하이라이트" in title_lower


def _iso_date(year: str, month: str, day: str) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def _parsed_result(title: str, team_a: str, team_b: str, iso_date: str | None) -> dict | None:
    if not iso_date:
        return None

    return {
        "date": iso_date,
        "team_a": normalize_team_name(team_a),
        "team_b": normalize_team_name(team_b),
        "original_title": title,
    }


def parse_video_title(title: str) -> dict | None:
    """Parse the title formats emitted by the official and ON THE SPORTS channels."""
    if not is_highlight_video(title):
        return None

    normalized_title = re.sub(r"\s+", " ", title).strip()

    official_match = re.search(
        r"【(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})】\s*(.+?)\s+vs\.?\s+(.+?)\s*\|",
        normalized_title,
        re.IGNORECASE,
    )
    if official_match:
        year, month, day, team_a, team_b = official_match.groups()
        return _parsed_result(title, team_a, team_b, _iso_date(year, month, day))

    prefix_match = re.search(
        r"(?:하이라이트|highlights?)\s*\|\s*(.+?)\s+vs\.?\s+(.+?)\s*\|\s*(.+?)(?:\s*\||$)",
        normalized_title,
        re.IGNORECASE,
    )
    if not prefix_match:
        return None

    team_a, team_b, raw_date = prefix_match.groups()
    ymd_match = re.search(r"(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})", raw_date)
    if ymd_match:
        year, month, day = ymd_match.groups()
        return _parsed_result(title, team_a, team_b, _iso_date(year, month, day))

    # YouTube may return an English-localized playlist title even when the
    # channel's native title uses YYYY. M. D.
    mdy_match = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})", raw_date)
    if mdy_match:
        month, day, year = mdy_match.groups()
        return _parsed_result(title, team_a, team_b, _iso_date(year, month, day))

    return None


def highlight_video_priority(video: dict) -> int:
    """Prefer a normal game highlight over an all-goals derivative."""
    title = video.get("title", "").casefold()
    return 1 if "all goals" in title or "全得点" in title else 0


def highlight_match_key(parsed_info: dict) -> tuple[str, tuple[str, str]]:
    teams = tuple(sorted((parsed_info["team_a"], parsed_info["team_b"])))
    return parsed_info["date"], teams
