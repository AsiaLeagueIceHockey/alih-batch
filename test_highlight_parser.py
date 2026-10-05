import unittest

from highlight_parser import (
    highlight_match_key,
    highlight_video_priority,
    normalize_team_name,
    parse_video_title,
)


class HighlightParserTests(unittest.TestCase):
    def test_parses_official_channel_title(self):
        parsed = parse_video_title(
            "【2026.09.27】RED EAGLES vs GRITS | Asia League Highlights |"
        )

        self.assertEqual(
            parsed,
            {
                "date": "2026-09-27",
                "team_a": "EAGLES",
                "team_b": "GRITS",
                "original_title": "【2026.09.27】RED EAGLES vs GRITS | Asia League Highlights |",
            },
        )

    def test_parses_on_the_sports_native_korean_title(self):
        parsed = parse_video_title(
            "하이라이트 | HL안양 vs 레드이글스 홋카이도 | 2026. 10. 3 | "
            "아시아리그 아이스하키 2026-2027"
        )

        self.assertEqual(parsed["date"], "2026-10-03")
        self.assertEqual(parsed["team_a"], "HL ANYANG")
        self.assertEqual(parsed["team_b"], "EAGLES")

    def test_parses_youtube_english_localized_on_the_sports_title(self):
        parsed = parse_video_title(
            "Highlights | HL Anyang vs. Red Eagles Hokkaido | 10/03/2026 | "
            "Asia League Ice Hockey 2026-2027"
        )

        self.assertEqual(parsed["date"], "2026-10-03")
        self.assertEqual(parsed["team_a"], "HL ANYANG")
        self.assertEqual(parsed["team_b"], "EAGLES")

    def test_rejects_invalid_date_and_non_highlight(self):
        self.assertIsNone(parse_video_title("Highlights | HL Anyang vs GRITS | 13/40/2026"))
        self.assertIsNone(parse_video_title("HL Anyang Home Opener Report | 10/03/2026"))

    def test_normalizes_reversed_korean_red_eagles_name(self):
        self.assertEqual(normalize_team_name("레드이글스 홋카이도"), "EAGLES")

    def test_prefers_standard_highlight_and_deduplicates_team_order(self):
        self.assertLess(
            highlight_video_priority({"title": "Asia League Highlights"}),
            highlight_video_priority({"title": "Asia League Highlights | 全得点シーン"}),
        )
        self.assertEqual(
            highlight_match_key(
                {"date": "2026-10-03", "team_a": "HL ANYANG", "team_b": "EAGLES"}
            ),
            highlight_match_key(
                {"date": "2026-10-03", "team_a": "EAGLES", "team_b": "HL ANYANG"}
            ),
        )


if __name__ == "__main__":
    unittest.main()
