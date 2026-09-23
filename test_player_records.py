import unittest

from player_records import normalize_player_name, reconcile_goalie_records, reconcile_player_records


class PlayerRecordReconciliationTests(unittest.TestCase):
    def test_normalizes_official_name_punctuation(self):
        self.assertEqual(normalize_player_name("MORROW, Joe"), normalize_player_name("MORROW Joe"))

    def test_uses_roster_identity_for_stat_update(self):
        source = [{
            "team_id": 1,
            "jersey_number": 70,
            "name": "MORROW, Joe",
            "position": "D",
            "games_played": 3,
            "points": 3,
            "goals": 0,
            "assists": 3,
            "shots": 6,
            "plus_minus": "3/2",
            "pim": 4,
        }]
        roster = [{"team_id": 1, "jersey_number": 70, "name": "MORROW Joe"}]

        updates, report = reconcile_player_records(source, roster, "2026-27")
        self.assertEqual(
            updates,
            [{
                "season": "2026-27",
                "team_id": 1,
                "name": "MORROW Joe",
                "jersey_number": 70,
                "position": "D",
                "games_played": 3,
                "points": 3,
                "goals": 0,
                "assists": 3,
                "shots": 6,
                "plus_minus": "3/2",
                "pim": 4,
            }],
        )
        self.assertEqual(report["matched"], 1)
        self.assertEqual(report["new"], 0)

    def test_preserves_missing_roster_profiles(self):
        source = [self._record(1, 70, "MORROW, Joe")]
        roster = [
            {"team_id": 1, "jersey_number": 70, "name": "MORROW Joe"},
            {"team_id": 1, "jersey_number": 82, "name": "OHTSU Yusei"},
        ]

        _, report = reconcile_player_records(source, roster, "2026-27")
        self.assertEqual(report["missing_from_source"], 1)
        self.assertEqual(report["missing_names"], ["OHTSU Yusei"])

    def test_inserts_a_guarded_new_official_player(self):
        source = [self._record(1, 70, "MORROW, Joe"), self._record(1, 18, "BAE,Sangho")]
        roster = [{"team_id": 1, "jersey_number": 70, "name": "MORROW Joe"}]

        updates, report = reconcile_player_records(source, roster, "2026-27")
        self.assertEqual(report["new"], 1)
        self.assertEqual(updates[1]["name"], "BAE,Sangho")
        self.assertEqual(updates[1]["jersey_number"], 18)

    def test_updates_jersey_and_position_for_existing_player(self):
        source = [self._record(3, 4, "TOKO,Yutaka")]
        roster = [{"team_id": 3, "jersey_number": 44, "name": "TOKO Yutaka"}]

        updates, _ = reconcile_player_records(source, roster, "2026-27")
        self.assertEqual(updates[0]["jersey_number"], 4)
        self.assertEqual(updates[0]["position"], "D")

    def test_allows_duplicate_source_jersey_when_names_match_roster(self):
        source = [
            self._record(6, 72, "ISHIDA,Seiya"),
            self._record(6, 72, "HOU,Yuyang"),
        ]
        roster = [
            {"team_id": 6, "jersey_number": 17, "name": "ISHIDA Seiya"},
            {"team_id": 6, "jersey_number": 92, "name": "Hou Yuyang"},
        ]

        _, report = reconcile_player_records(source, roster, "2026-27")
        self.assertEqual(report["matched"], 2)

    def test_matches_minor_spelling_drift_on_unique_jersey(self):
        source = [self._record(4, 14, "OSAWA,Yuto")]
        roster = [{"team_id": 4, "jersey_number": 14, "name": "OHSAWA Yuto"}]

        updates, report = reconcile_player_records(source, roster, "2026-27")
        self.assertEqual(report["matched"], 1)
        self.assertEqual(updates[0]["name"], "OHSAWA Yuto")

    def test_matches_split_given_name_without_jersey(self):
        source = [self._record(1, 31, "CHUN,Jong Hun")]
        roster = [{"team_id": 1, "jersey_number": None, "name": "CHUN Jonghun"}]

        updates, report = reconcile_player_records(source, roster, "2026-27")
        self.assertEqual(report["matched"], 1)
        self.assertEqual(updates[0]["name"], "CHUN Jonghun")

    def test_matches_unique_high_similarity_name_without_jersey(self):
        source = [self._record(4, 14, "OSAWA,Yuto")]
        roster = [{"team_id": 4, "jersey_number": None, "name": "OHSAWA Yuto"}]

        updates, report = reconcile_player_records(source, roster, "2026-27")
        self.assertEqual(report["matched"], 1)
        self.assertEqual(updates[0]["name"], "OHSAWA Yuto")

    def test_fails_closed_on_large_roster_drift(self):
        source = [self._record(1, number, f"New Player {number}") for number in range(1, 7)]
        roster = [{"team_id": 1, "jersey_number": 70, "name": "MORROW Joe"}]

        with self.assertRaisesRegex(RuntimeError, "exceeds the guarded update threshold"):
            reconcile_player_records(source, roster, "2026-27")

    def test_adds_a_guarded_new_goalie(self):
        source = [{
            "team_id": 3,
            "jersey_number": 33,
            "name": "ITO,Takayuki",
            "play_time": "00:00",
            "shots_against": 0,
            "goals_against": 0,
            "saves": 0,
            "save_pct": 0.0,
            "goals_against_average": 0.0,
            "gkc": 0.0,
        }]

        updates, report = reconcile_goalie_records(source, [], "2026-27")
        self.assertEqual(report["new_names"], ["ITO,Takayuki"])
        self.assertEqual(updates[0]["position"], "G")
        self.assertEqual(updates[0]["jersey_number"], 33)

    def test_matches_goalie_with_split_given_name(self):
        source = [{
            "team_id": 1,
            "jersey_number": 31,
            "name": "CHUN,Jong Hun",
            "play_time": "60:00",
            "shots_against": 30,
            "goals_against": 2,
            "saves": 28,
            "save_pct": 93.33,
            "goals_against_average": 2.0,
            "gkc": 0.0,
        }]
        roster = [{"team_id": 1, "jersey_number": None, "name": "CHUN Jonghun"}]

        updates, report = reconcile_goalie_records(source, roster, "2026-27")
        self.assertEqual(report["matched"], 1)
        self.assertEqual(report["new"], 0)
        self.assertEqual(updates[0]["name"], "CHUN Jonghun")

    @staticmethod
    def _record(team_id, jersey_number, name):
        return {
            "team_id": team_id,
            "jersey_number": jersey_number,
            "name": name,
            "position": "D",
            "games_played": 0,
            "points": 0,
            "goals": 0,
            "assists": 0,
            "shots": 0,
            "plus_minus": "0/0",
            "pim": 0,
        }


if __name__ == "__main__":
    unittest.main()
