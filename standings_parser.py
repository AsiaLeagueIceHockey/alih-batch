from bs4 import BeautifulSoup


# Official source names mapped to the stable english_name values in alih_teams.
HTML_TO_DB_TEAM_MAP = {
    "HL ANYANG": "HL ANYANG",
    "HL ANYANG ICE HOCKEY CLUB": "HL ANYANG",
    "RED EAGLES HOKKAIDO": "EAGLES",
    "NIKKO ICEBUCKS": "ICEBUCKS",
    "YOKOHAMA GRITS": "GRITS",
    "TOHOKU FREEBLADES": "FREEBLADES",
    "STARS KOBE": "STARS",
}


def parse_standings_html(html_content, target_season, team_id_map, updated_at):
    soup = BeautifulSoup(html_content, "html.parser")
    start_year, end_suffix = target_season.split("-")
    expected_season_marker = f"{start_year}-{start_year[:2]}{end_suffix}"
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if expected_season_marker not in title:
        raise RuntimeError(f"Source does not identify {target_season}: {title}")

    rk_header = soup.find("th", string="RK")
    if not rk_header:
        raise RuntimeError("Could not find standings table (RK header not found)")

    standings_table = rk_header.find_parent("table")
    standings = []

    for row in standings_table.find_all("tr"):
        if row.find("th"):
            continue

        cols = row.find_all("td")
        if not cols:
            continue
        if len(cols) != 11:
            raise RuntimeError(
                f"Expected 11 standings columns, received {len(cols)}: {row.get_text(' ', strip=True)}"
            )

        source_team_name = cols[1].get_text(" ", strip=True)
        db_team_name = HTML_TO_DB_TEAM_MAP.get(source_team_name)
        if not db_team_name:
            raise RuntimeError(f"No DB mapping for official standings team '{source_team_name}'")

        team_id = team_id_map.get(db_team_name)
        if not team_id:
            raise RuntimeError(f"No team_id found for '{db_team_name}' in alih_teams")

        try:
            goals_for_text, goals_against_text = cols[9].get_text(" ", strip=True).split(" - ")
            standings.append({
                "season": target_season,
                "team_id": team_id,
                "rank": int(cols[0].get_text(strip=True)),
                "games_played": int(cols[2].get_text(strip=True)),
                "win_60min": int(cols[3].get_text(strip=True)),
                "win_ot": int(cols[4].get_text(strip=True)),
                "win_pss": int(cols[5].get_text(strip=True)),
                "lose_pss": int(cols[6].get_text(strip=True)),
                "lose_ot": int(cols[7].get_text(strip=True)),
                "lose_60min": int(cols[8].get_text(strip=True)),
                "goals_for": int(goals_for_text),
                "goals_against": int(goals_against_text),
                "points": int(cols[10].get_text(strip=True)),
                "updated_at": updated_at,
            })
        except (TypeError, ValueError) as error:
            raise RuntimeError(
                f"Error parsing standings row: {error} | {row.get_text(' ', strip=True)}"
            ) from error

    team_ids = [row["team_id"] for row in standings]
    if not 2 <= len(standings) <= 6 or len(set(team_ids)) != len(team_ids):
        raise RuntimeError(
            f"Expected two to six uniquely mapped active teams, received {len(standings)}"
        )

    return standings
