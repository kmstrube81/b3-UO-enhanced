# -*- coding: utf-8 -*-

# ################################################################### #
#                                                                     #
#  BigBrotherBot(B3) (www.bigbrotherbot.net)                          #
#  Copyright (C) 2005 Michael "ThorN" Thornton                        #
#                                                                     #
#  This program is free software; you can redistribute it and/or      #
#  modify it under the terms of the GNU General Public License        #
#  as published by the Free Software Foundation; either version 2     #
#  of the License, or (at your option) any later version.             #
#                                                                     #
#  This program is distributed in the hope that it will be useful,    #
#  but WITHOUT ANY WARRANTY; without even the implied warranty of     #
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the       #
#  GNU General Public License for more details.                       #
#                                                                     #
#  You should have received a copy of the GNU General Public License  #
#  along with this program; if not, write to the Free Software        #
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA      #
#  02110-1301, USA.                                                   #
#                                                                     #
# ################################################################### #

from b3.plugins.pamx import PamxPlugin
from tests.plugins.pamx import PamxTestCase


class ResultTestCase(PamxTestCase):
    """
    Easy Company (a1, a2) vs Dog Company (b1, b2), set up with !match.
    """

    def setUp(self):
        PamxTestCase.setUp(self)
        self.a1 = self.new_player('A1', '10000001')
        self.a2 = self.new_player('A2', '10000002')
        self.b1 = self.new_player('B1', '20000001')
        self.b2 = self.new_player('B2', '20000002')
        self.pub = self.new_player('Pubber', '30000001')
        self.team_a = self.make_team('Easy Company', self.a1, self.a2)
        self.team_b = self.make_team('Dog Company', self.b1, self.b2)
        self.admin.says('!match "Easy Company" "Dog Company"')
        self.console.say.reset_mock()

    def record(self, team_id):
        t = self.team(team_id)
        return t['wins'], t['losses'], t['draws']

    def assert_not_recorded(self, reason):
        self.assertEqual((0, 0, 0), self.record(self.team_a))
        self.assertEqual((0, 0, 0), self.record(self.team_b))
        self.assertIsNone(self.p.active_match)
        self.assertIsNone(self.p.load_active_match())
        self.assertEqual(1, len(self.said()))
        self.assertIn('match result not recorded: %s' % reason, self.said()[0])


class Test_results(ResultTestCase):

    def test_team1_wins_on_allies(self):
        self.result_line('match_win', 'allies', self.a1, self.a2, self.pub)
        self.result_line('match_loss', 'axis', self.b1, self.b2)
        self.exit_level()
        self.assertEqual((1, 0, 0), self.record(self.team_a))
        self.assertEqual((0, 1, 0), self.record(self.team_b))
        self.assertEqual(['^7match result: ^3Easy Company ^7beat ^3Dog Company'], self.said())
        self.assertIsNone(self.p.active_match)
        self.assertIsNone(self.p.load_active_match())

    def test_team1_loses_on_axis(self):
        # sides swapped at halftime: team1 ends on axis
        self.result_line('match_win', 'allies', self.b1, self.b2)
        self.result_line('match_loss', 'axis', self.a1, self.a2)
        self.exit_level()
        self.assertEqual((0, 1, 0), self.record(self.team_a))
        self.assertEqual((1, 0, 0), self.record(self.team_b))
        self.assertEqual(['^7match result: ^3Dog Company ^7beat ^3Easy Company'], self.said())

    def test_team1_wins_on_axis(self):
        self.result_line('match_win', 'axis', self.a1)
        self.result_line('match_loss', 'allies', self.b2)
        self.exit_level()
        self.assertEqual((1, 0, 0), self.record(self.team_a))
        self.assertEqual((0, 1, 0), self.record(self.team_b))

    def test_tie(self):
        self.result_line('match_draw', 'axis', self.a1, self.a2)
        self.result_line('match_draw', 'allies', self.b1, self.b2)
        self.exit_level()
        self.assertEqual((0, 0, 1), self.record(self.team_a))
        self.assertEqual((0, 0, 1), self.record(self.team_b))
        self.assertEqual(['^7match result: ^3Easy Company ^7and ^3Dog Company ^7drew'], self.said())
        self.assertIsNone(self.p.active_match)

    def test_only_loser_line_has_players(self):
        # winners line had nobody we know: the other side of the losers won
        self.result_line('match_win', 'allies', self.b1)
        self.result_line('match_loss', 'axis', self.a1)
        self.exit_level()
        self.assertEqual((0, 1, 0), self.record(self.team_a))

    def test_recorded_on_next_initgame_without_exitlevel(self):
        self.result_line('match_win', 'allies', self.a1)
        self.result_line('match_loss', 'axis', self.b1)
        self.init_game()
        self.assertEqual((1, 0, 0), self.record(self.team_a))

    def test_player_on_both_rosters_ignored(self):
        self.p.add_team_player(self.team_b, self.a2.id)
        # a2 played for Dog Company: without the exclusion Easy Company would look split
        self.result_line('match_win', 'allies', self.a1)
        self.result_line('match_loss', 'axis', self.a2, self.b1)
        self.exit_level()
        self.assertEqual((1, 0, 0), self.record(self.team_a))
        self.assertEqual((0, 1, 0), self.record(self.team_b))

    def test_no_double_counting(self):
        self.result_line('match_win', 'allies', self.a1)
        self.result_line('match_loss', 'axis', self.b1)
        self.exit_level()
        self.exit_level()
        self.init_game()
        # the next map's result lines are ignored: no active match anymore
        self.result_line('match_win', 'allies', self.a1)
        self.result_line('match_loss', 'axis', self.b1)
        self.exit_level()
        self.assertEqual((1, 0, 0), self.record(self.team_a))
        self.assertEqual((0, 1, 0), self.record(self.team_b))
        self.assertEqual(1, len(self.said()))

    def test_single_statement_update_only_touches_match_teams(self):
        other = self.make_team('Bystanders')
        self.result_line('match_win', 'allies', self.a1)
        self.result_line('match_loss', 'axis', self.b1)
        self.exit_level()
        self.assertEqual((0, 0, 0), self.record(other))


class Test_sanity_checks(ResultTestCase):

    def test_team1_split_across_sides(self):
        self.result_line('match_win', 'allies', self.a1, self.b1)
        self.result_line('match_loss', 'axis', self.a2, self.b2)
        self.exit_level()
        self.assert_not_recorded('rostered players of Easy Company were split across both sides')

    def test_team2_split_across_sides(self):
        self.result_line('match_win', 'allies', self.a1, self.b1)
        self.result_line('match_loss', 'axis', self.a2, self.b2)
        self.p.query("DELETE FROM pamx_team_players WHERE client_id = %s", [self.a2.id]).close()
        self.exit_level()
        self.assert_not_recorded('rostered players of Dog Company were split across both sides')

    def test_team1_absent(self):
        self.result_line('match_win', 'allies', self.pub)
        self.result_line('match_loss', 'axis', self.b1)
        self.exit_level()
        self.assert_not_recorded('no rostered players of Easy Company were in the game')

    def test_team2_absent(self):
        self.result_line('match_win', 'allies', self.a1)
        self.result_line('match_loss', 'axis', self.pub)
        self.exit_level()
        self.assert_not_recorded('no rostered players of Dog Company were in the game')

    def test_both_teams_on_same_side(self):
        self.result_line('match_win', 'allies', self.a1, self.b1)
        self.result_line('match_loss', 'axis', self.pub)
        self.exit_level()
        self.assert_not_recorded('both teams had their rostered players on allies')

    def test_draw_and_winner_reported(self):
        self.result_line('match_draw', 'allies', self.a1)
        self.result_line('match_loss', 'axis', self.b1)
        self.exit_level()
        self.assert_not_recorded('the game log reported both a draw and a winner')


class Test_no_result(ResultTestCase):

    def test_no_active_match_ignored(self):
        self.admin.says('!pub')
        self.console.say.reset_mock()
        self.result_line('match_win', 'allies', self.a1)
        self.result_line('match_loss', 'axis', self.b1)
        self.exit_level()
        self.assertEqual((0, 0, 0), self.record(self.team_a))
        self.assertEqual((0, 0, 0), self.record(self.team_b))
        self.assertEqual([], self.said())

    def test_halftime_not_counted(self):
        # halftime / round restarts: CODUO-X logs RW;/RL; (not handled here) and map_restart logs InitGame
        self.result_line('round_win', 'allies', self.a1)
        self.result_line('round_loss', 'axis', self.b1)
        self.init_game()
        self.init_game()
        self.assertEqual({'team1_id': self.team_a, 'team2_id': self.team_b}, self.p.active_match)
        self.assertEqual((0, 0, 0), self.record(self.team_a))
        self.assertEqual([], self.said())

    def test_mode_change_exitlevel_not_counted(self):
        # PAM_Restart exitLevel()s after !match changed pam_mode: no result lines, match stays active
        self.exit_level()
        self.init_game()
        self.assertEqual({'team1_id': self.team_a, 'team2_id': self.team_b}, self.p.active_match)

    def test_ffa_lines_ignored(self):
        self.result_line('match_win', '', self.a1)
        self.exit_level()
        self.assertIsNotNone(self.p.active_match)
        self.assertEqual((0, 0, 0), self.record(self.team_a))

    def test_match_dropped_when_pam_cleared_rosters(self):
        # map ended without a result line we saw: PAM_Postgame emptied the rosters
        self.console.setCvar('pam_team1_roster', '')
        self.console.setCvar('pam_team2_roster', '')
        self.init_game()
        self.assertIsNone(self.p.active_match)
        self.assertIsNone(self.p.load_active_match())

    def test_active_match_survives_b3_restart(self):
        restarted = PamxPlugin(self.console, '@b3/conf/plugin_pamx.ini')
        restarted.onLoadConfig()
        restarted.onStartup()
        self.assertEqual({'team1_id': self.team_a, 'team2_id': self.team_b}, restarted.active_match)
