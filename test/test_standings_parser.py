import unittest

from standings_parser import parse_standings_html


TEAM_IDS = {
    "HL ANYANG": 1,
    "EAGLES": 2,
    "FREEBLADES": 3,
    "GRITS": 4,
    "ICEBUCKS": 5,
    "STARS": 6,
}


def standings_fixture(anyang_name="HL ANYANG"):
    teams = [
        (1, "RED EAGLES HOKKAIDO", 11, 7, 1, 0, 1, 0, 2, "38 - 28", 24),
        (2, "NIKKO ICEBUCKS", 11, 5, 0, 2, 0, 0, 4, "40 - 30", 19),
        (3, anyang_name, 8, 5, 0, 0, 0, 0, 3, "32 - 24", 15),
        (4, "TOHOKU FREEBLADES", 8, 5, 0, 0, 0, 0, 3, "25 - 22", 15),
        (5, "YOKOHAMA GRITS", 8, 3, 0, 0, 1, 1, 3, "23 - 25", 11),
        (6, "STARS KOBE", 10, 0, 0, 0, 0, 0, 10, "18 - 47", 0),
    ]
    rows = "".join(
        "<tr>" + "".join(f"<td>{value}</td>" for value in team) + "</tr>"
        for team in teams
    )
    return f"""
        <html>
          <head><title>Asia League Ice Hockey 2026-2027 / Regular | Standings</title></head>
          <body><table><tr><th>RK</th></tr>{rows}</table></body>
        </html>
    """


class StandingsParserTest(unittest.TestCase):
    def test_maps_current_official_hl_anyang_name(self):
        rows = parse_standings_html(
            standings_fixture(),
            "2026-27",
            TEAM_IDS,
            "2026-10-22T00:00:00+00:00",
        )

        anyang = next(row for row in rows if row["team_id"] == TEAM_IDS["HL ANYANG"])
        self.assertEqual(anyang["rank"], 3)
        self.assertEqual(anyang["games_played"], 8)
        self.assertEqual(anyang["points"], 15)
        self.assertEqual(anyang["goals_for"], 32)
        self.assertEqual(anyang["goals_against"], 24)

    def test_keeps_legacy_hl_anyang_name_compatible(self):
        rows = parse_standings_html(
            standings_fixture("HL ANYANG ICE HOCKEY CLUB"),
            "2026-27",
            TEAM_IDS,
            "2026-10-22T00:00:00+00:00",
        )

        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[2]["team_id"], TEAM_IDS["HL ANYANG"])

    def test_fails_closed_for_an_unknown_team_name(self):
        with self.assertRaisesRegex(RuntimeError, "No DB mapping"):
            parse_standings_html(
                standings_fixture("ANYANG UNKNOWN"),
                "2026-27",
                TEAM_IDS,
                "2026-10-22T00:00:00+00:00",
            )


if __name__ == "__main__":
    unittest.main()
