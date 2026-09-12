import unittest

from team_roster_source import parse_team_roster


FIXTURE = """
<h4>GK <small>GOAL KEEPER</small></h4>
<div><div class="uk-card"><div class="uk-card-media-top">
<img data-src="https://cdn.asiaicehockey.com/wp-content/uploads/2026/09/GK_1_TEST.jpg" />
</div><div class="uk-card-header"><p class="uk-text-large">1</p>
<h3 class="uk-card-title">テスト 太郎</h3><p class="uk-text-meta">TEST Taro</p></div>
<div class="uk-card-body">生年月日: 2000/1/2<br/>身長: 180cm / 体重: 80kg<br/>国籍: 日本</div></div></div>
"""


class TeamRosterSourceTests(unittest.TestCase):
    def test_parses_official_roster_card(self):
        players = parse_team_roster(FIXTURE, "eagles")
        self.assertEqual(len(players), 1)
        player = players[0]
        self.assertEqual(player.position, "GK")
        self.assertEqual(player.jersey_number, 1)
        self.assertEqual(player.name_en, "TEST Taro")
        self.assertEqual(player.birth_date, "2000-01-02")
        self.assertEqual(player.height_cm, 180)
        self.assertEqual(player.weight_kg, 80)
        self.assertEqual(player.slug, "eagles-1-test-taro")

    def test_rejects_non_official_photo_host(self):
        with self.assertRaisesRegex(ValueError, "not from the official CDN"):
            parse_team_roster(FIXTURE.replace("https://cdn.asiaicehockey.com", "https://invalid.example"), "eagles")


if __name__ == "__main__":
    unittest.main()
