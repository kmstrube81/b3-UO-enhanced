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

import random

from mock import patch
from b3.plugins.pamx import PamxPlugin
from tests.plugins.pamx import PamxTestCase


class Test_schema(PamxTestCase):

    def test_tables_created(self):
        tables = self.console.storage.getTables()
        for table in ('pamx_teams', 'pamx_team_players', 'pamx_active_match'):
            self.assertIn(table, tables)

    def test_schema_creation_is_idempotent(self):
        self.p.build_database_schema()
        self.console.storage.queryFromFile('@b3/plugins/pamx/sql/sqlite/pamx.sql')

    def test_commands_registered(self):
        for cmd in ('maketeam', 'addplayer', 'match', 'pug', 'pub', 'scrim', 'makecaptain', 'captain', 'draftplayer',
                    'cutplayer'):
            self.assertIn(cmd, self.adminPlugin._commands)


class Test_arguments(PamxTestCase):

    def test_quoted_team(self):
        self.assertEqual(('Easy Company', 'kasey'), PamxPlugin.split_team_arg('"Easy Company" kasey'))

    def test_unquoted_team(self):
        self.assertEqual(('Easy', 'kasey smith'), PamxPlugin.split_team_arg('Easy kasey smith'))

    def test_unclosed_quote(self):
        self.assertIsNone(PamxPlugin.split_team_arg('"Easy Company kasey'))

    def test_empty(self):
        self.assertIsNone(PamxPlugin.split_team_arg(''))
        self.assertIsNone(PamxPlugin.split_team_arg('"" kasey'))


class Test_team_matching(PamxTestCase):

    def test_match_by_id(self):
        team_id = self.make_team('Easy Company')
        self.assertEqual('Easy Company', self.p.find_team(str(team_id))['name'])

    def test_match_by_name_case_insensitive(self):
        self.make_team('Easy Company')
        self.assertEqual('Easy Company', self.p.find_team('easy COMPANY')['name'])

    def test_numeric_id_wins_over_numeric_name(self):
        first = self.make_team('Alpha')
        self.make_team(str(first))  # a team literally named like the id of another one
        self.assertEqual('Alpha', self.p.find_team(str(first))['name'])

    def test_numeric_falls_back_to_name(self):
        self.make_team('Alpha')
        self.make_team('2013')
        self.assertEqual('2013', self.p.find_team('2013')['name'])

    def test_no_match(self):
        self.make_team('Alpha')
        self.admin.says('!addplayer Bravo Guest')
        self.assertIsNotNone(self.admin.getMessageHistoryLike('no team found matching Bravo'))


class Test_maketeam(PamxTestCase):

    def test_create(self):
        self.admin.says('!maketeam Easy Company')
        team = self.p.get_team_by_name('Easy Company')
        self.assertIsNotNone(team)
        self.assertEqual(['team Easy Company created with id %s' % team['id']], self.admin.message_history)
        self.assertEqual((0, 0, 0), (team['wins'], team['losses'], team['draws']))

    def test_create_quoted(self):
        self.admin.says('!maketeam "Easy Company"')
        self.assertIsNotNone(self.p.get_team_by_name('Easy Company'))

    def test_duplicate_case_insensitive(self):
        team_id = self.make_team('Easy Company')
        self.admin.says('!maketeam easy company')
        self.assertEqual(['team Easy Company already exists (id %s)' % team_id], self.admin.message_history)

    def test_invalid_names(self):
        for name in ('bad;name', 'bad\\name', 'x' * 33):
            self.admin.clearMessageHistory()
            self.admin.says('!maketeam %s' % name)
            self.assertIsNotNone(self.admin.getMessageHistoryLike('invalid team name'), name)
            self.assertIsNone(self.p.get_team_by_name(name))

    def test_guest_cannot_use(self):
        self.guest.says('!maketeam Easy Company')
        self.assertIsNone(self.p.get_team_by_name('Easy Company'))


class Test_addplayer(PamxTestCase):

    def setUp(self):
        PamxTestCase.setUp(self)
        self.team_id = self.make_team('Easy Company')
        self.kasey = self.new_player('Kasey', '12345678', cid='2')

    def test_add_connected_player_quoted_team(self):
        self.admin.says('!addplayer "Easy Company" kasey')
        self.assertTrue(self.p.is_on_team(self.team_id, self.kasey.id))
        self.assertEqual(['Kasey added to Easy Company'], self.admin.message_history)

    def test_add_by_team_id(self):
        self.admin.says('!addplayer %s kasey' % self.team_id)
        self.assertTrue(self.p.is_on_team(self.team_id, self.kasey.id))

    def test_add_duplicate(self):
        self.admin.says('!addplayer "Easy Company" kasey')
        self.admin.clearMessageHistory()
        self.admin.says('!addplayer "Easy Company" kasey')
        self.assertEqual(['Kasey is already on Easy Company'], self.admin.message_history)
        cursor = self.p.query("SELECT COUNT(*) AS n FROM pamx_team_players WHERE team_id = %s", [self.team_id])
        self.assertEqual(1, cursor.getRow()['n'])

    def test_add_offline_player_by_db_id(self):
        offline = self.new_player('Offline', '87654321')
        self.assertIsNone(self.console.clients.getByCID('99'))
        self.admin.says('!addplayer "Easy Company" @%s' % offline.id)
        self.assertTrue(self.p.is_on_team(self.team_id, offline.id))

    def test_multiple_matches_lists_candidates(self):
        self.new_player('Kaseyboy', '33333333', cid='3')
        self.admin.says('!addplayer "Easy Company" kase')
        self.assertIsNotNone(self.admin.getMessageHistoryLike('Kasey'))
        self.assertFalse(self.p.is_on_team(self.team_id, self.kasey.id))

    def test_missing_player(self):
        self.admin.says('!addplayer "Easy Company"')
        self.assertEqual(['usage: !addplayer <team> <player>'], self.admin.message_history)


class Test_match(PamxTestCase):

    def setUp(self):
        PamxTestCase.setUp(self)
        self.a1 = self.new_player('A1', '10000001')
        self.a2 = self.new_player('A2', '10000002')
        self.b1 = self.new_player('B1', '20000001')
        self.team_a = self.make_team('Easy Company', self.a1, self.a2)
        self.team_b = self.make_team('Dog Company', self.b1)

    def test_sets_cvars_and_active_match(self):
        self.admin.says('!match "Easy Company" "Dog Company"')
        self.assertEqual('Easy Company', self.cvar('pam_team1_name'))
        self.assertEqual('Dog Company', self.cvar('pam_team2_name'))
        self.assertEqual('10000001;10000002;', self.cvar('pam_team1_roster'))
        self.assertEqual('20000001;', self.cvar('pam_team2_roster'))
        self.assertEqual('na_comp', self.cvar('pam_mode'))
        self.assertEqual({'team1_id': self.team_a, 'team2_id': self.team_b}, self.p.active_match)
        self.assertEqual(self.p.active_match, self.p.load_active_match())  # persisted

    def test_rifles_and_ids(self):
        self.admin.says('!match %s %s RIFLES' % (self.team_a, self.team_b))
        self.assertEqual('na_comp_rifles', self.cvar('pam_mode'))

    def test_mode_change_lets_pam_restart(self):
        self.console.setCvar('pam_mode', 'na_comp_pub')
        self.admin.says('!match "Easy Company" "Dog Company"')
        self.assertFalse(self.console.write.called)

    def test_unchanged_mode_sends_map_restart(self):
        self.console.setCvar('pam_mode', 'na_comp')
        self.admin.says('!match "Easy Company" "Dog Company"')
        self.console.write.assert_called_once_with('map_restart')

    def test_same_team(self):
        self.admin.says('!match "Easy Company" %s' % self.team_a)
        self.assertEqual(['a team cannot play against itself'], self.admin.message_history)
        self.assertIsNone(self.p.active_match)

    def test_bad_third_argument(self):
        self.admin.says('!match "Easy Company" "Dog Company" smgs')
        self.assertEqual(['usage: !match <team1> <team2> [rifles]'], self.admin.message_history)

    def test_guid_zero_and_empty_skipped(self):
        zero = self.new_player('Zero', '0')
        self.p.add_team_player(self.team_b, zero.id)
        self.p.query("UPDATE clients SET guid = '' WHERE id = %s", [self.a2.id]).close()
        self.admin.says('!match "Easy Company" "Dog Company"')
        self.assertEqual('10000001;', self.cvar('pam_team1_roster'))
        self.assertEqual('20000001;', self.cvar('pam_team2_roster'))
        self.assertIsNotNone(self.admin.getMessageHistoryLike('skipped Zero (Dog Company): no valid GUID'))
        self.assertIsNotNone(self.admin.getMessageHistoryLike('skipped A2 (Easy Company): no valid GUID'))

    def test_team_without_valid_guids_warns(self):
        empty = self.make_team('Empty')
        self.admin.says('!match "Easy Company" Empty')
        self.assertIsNotNone(self.admin.getMessageHistoryLike('warning: Empty has no players with a valid GUID'))
        self.assertEqual('', self.cvar('pam_team2_roster'))
        self.assertEqual({'team1_id': self.team_a, 'team2_id': empty}, self.p.active_match)

    def test_roster_too_long_is_refused(self):
        self.p.max_cvar_length = 15  # 2 GUIDs = 18 characters
        self.admin.says('!match "Easy Company" "Dog Company"')
        self.assertEqual(['roster of Easy Company is 18 characters, the limit is 15: match not set'],
                         self.admin.message_history)
        self.assertIsNone(self.cvar('pam_team1_roster'))
        self.assertIsNone(self.cvar('pam_mode'))
        self.assertIsNone(self.p.active_match)

    def test_roster_at_limit_is_accepted(self):
        self.p.max_cvar_length = 18
        self.admin.says('!match "Easy Company" "Dog Company"')
        self.assertEqual('10000001;10000002;', self.cvar('pam_team1_roster'))


class Test_mode_commands(PamxTestCase):

    def setUp(self):
        PamxTestCase.setUp(self)
        a = self.make_team('Alpha', self.new_player('A1', '10000001'))
        b = self.make_team('Bravo', self.new_player('B1', '20000001'))
        self.admin.says('!match Alpha Bravo')
        self.admin.clearMessageHistory()

    def assert_mode(self, command, mode):
        self.admin.says(command)
        self.assertEqual(mode, self.cvar('pam_mode'))
        self.assertIsNone(self.p.active_match)
        self.assertIsNone(self.p.load_active_match())
        self.assertEqual('', self.cvar('pam_team1_roster'))
        self.assertEqual('', self.cvar('pam_team2_name'))
        self.assertIsNotNone(self.admin.getMessageHistoryLike('active match Alpha vs Bravo cancelled'))

    def test_pug(self):
        self.assert_mode('!pug', 'na_comp_pug')

    def test_pug_rifles(self):
        self.assert_mode('!pug rifles', 'na_comp_pug_rifles')

    def test_pub(self):
        self.assert_mode('!pub', 'na_comp_pub')

    def test_pub_rifles(self):
        self.assert_mode('!pub Rifles', 'na_comp_pub_rifles')

    def test_scrim(self):
        self.assert_mode('!scrim', 'na_comp')
        self.assertFalse(self.console.write.called)  # no restart: !scrim only changes the mode

    def test_scrim_rifles(self):
        self.assert_mode('!scrim rifles', 'na_comp_rifles')

    def test_no_active_match(self):
        self.p.clear_active_match()
        self.admin.says('!pub')
        self.assertEqual(['PAM mode set to na_comp_pub'], self.admin.message_history)


class Test_captains(PamxTestCase):

    def setUp(self):
        PamxTestCase.setUp(self)
        self.kasey = self.new_player('Kasey', '12345678', cid='2')

    def captains(self):
        return self.cvar('pam_team1_captain'), self.cvar('pam_team2_captain')

    def test_both_free_random(self):
        with patch.object(random, 'choice', return_value=2) as choice:
            self.admin.says('!makecaptain kasey')
        choice.assert_called_once_with((1, 2))
        self.assertEqual((None, '12345678'), self.captains())
        self.assertEqual(['Kasey is now captain of team 2'], self.admin.message_history)

    def test_both_free_empty_strings(self):
        self.console.setCvar('pam_team1_captain', '')
        self.console.setCvar('pam_team2_captain', '')
        with patch.object(random, 'choice', return_value=1):
            self.admin.says('!makecaptain kasey')
        self.assertEqual(('12345678', ''), self.captains())

    def test_one_free(self):
        self.console.setCvar('pam_team1_captain', '55555555')
        with patch.object(random, 'choice') as choice:
            self.admin.says('!makecaptain kasey')
        self.assertFalse(choice.called)
        self.assertEqual(('55555555', '12345678'), self.captains())

    def test_other_one_free(self):
        self.console.setCvar('pam_team2_captain', '55555555')
        self.admin.says('!makecaptain kasey')
        self.assertEqual(('12345678', '55555555'), self.captains())

    def test_both_taken_overwrites_random(self):
        self.console.setCvar('pam_team1_captain', '55555555')
        self.console.setCvar('pam_team2_captain', '66666666')
        with patch.object(random, 'choice', return_value=1):
            self.admin.says('!makecaptain kasey')
        self.assertEqual(('12345678', '66666666'), self.captains())

    def test_already_captain(self):
        self.console.setCvar('pam_team1_captain', '55555555')
        self.console.setCvar('pam_team2_captain', '12345678')
        with patch.object(random, 'choice', return_value=1):
            self.admin.says('!makecaptain kasey')
        self.assertEqual(('55555555', '12345678'), self.captains())
        self.assertEqual(['Kasey is already captain of team 2'], self.admin.message_history)

    def test_offline_player_refused(self):
        offline = self.new_player('Offline', '87654321')
        self.admin.says('!makecaptain @%s' % offline.id)
        self.assertEqual((None, None), self.captains())
        self.assertEqual(['Offline must be connected to be made captain'], self.admin.message_history)

    def test_guid_zero_refused(self):
        self.new_player('Zero', '0', cid='3')
        self.admin.says('!makecaptain zero')
        self.assertEqual((None, None), self.captains())
        self.assertEqual(['Zero has no valid GUID'], self.admin.message_history)

    def test_captain_self_both_free(self):
        with patch.object(random, 'choice', return_value=1):
            self.guest.says('!captain')
        self.assertEqual(('22222222', None), self.captains())

    def test_captain_self_one_free(self):
        self.console.setCvar('pam_team1_captain', '55555555')
        self.guest.says('!captain')
        self.assertEqual(('55555555', '22222222'), self.captains())

    def test_captain_self_both_taken(self):
        self.console.setCvar('pam_team1_captain', '55555555')
        self.console.setCvar('pam_team2_captain', '66666666')
        with patch.object(random, 'choice') as choice:
            self.guest.says('!captain')
        self.assertFalse(choice.called)
        self.assertEqual(('55555555', '66666666'), self.captains())
        self.assertEqual(['Sorry but both captains have already been assigned'], self.guest.message_history)


class DraftTestCase(PamxTestCase):
    """
    The guest (22222222) captains team 1 ("Guest"), 55555555 captains team 2 (no name set).
    """

    def setUp(self):
        PamxTestCase.setUp(self)
        self.kasey = self.new_player('Kasey', '12345678', cid='2')
        self.console.setCvar('pam_team1_captain', '22222222')
        self.console.setCvar('pam_team2_captain', '55555555')
        self.console.setCvar('pam_team1_name', 'Guest')
        self.console.setCvar('pam_team1_roster', '22222222;')
        self.console.setCvar('pam_team2_roster', '55555555;')

    def rosters(self):
        return self.cvar('pam_team1_roster'), self.cvar('pam_team2_roster')


class Test_draftplayer(DraftTestCase):

    def test_draft_to_own_team(self):
        self.guest.says('!draftplayer kasey')
        self.assertEqual(('22222222;12345678;', '55555555;'), self.rosters())
        self.assertEqual(['Kasey drafted to Guest'], self.guest.message_history)

    def test_team2_captain(self):
        self.console.setCvar('pam_team1_captain', '55555555')
        self.console.setCvar('pam_team2_captain', '22222222')
        self.guest.says('!draftplayer kasey')
        self.assertEqual(('22222222;', '55555555;12345678;'), self.rosters())
        # no pam_team2_name set: falls back to the slot
        self.assertEqual(['Kasey drafted to team 2'], self.guest.message_history)

    def test_empty_roster(self):
        self.console.setCvar('pam_team1_roster', '')
        self.guest.says('!draftplayer kasey')
        self.assertEqual('12345678;', self.cvar('pam_team1_roster'))

    def test_roster_without_trailing_separator(self):
        self.console.setCvar('pam_team1_roster', '22222222')
        self.guest.says('!draftplayer kasey')
        self.assertEqual('22222222;12345678;', self.cvar('pam_team1_roster'))

    def test_offline_player_by_db_id(self):
        offline = self.new_player('Offline', '87654321')
        self.guest.says('!draftplayer @%s' % offline.id)
        self.assertEqual('22222222;87654321;', self.cvar('pam_team1_roster'))

    def test_not_a_captain(self):
        self.console.setCvar('pam_team1_captain', '')
        self.guest.says('!draftplayer kasey')
        self.assertEqual(('22222222;', '55555555;'), self.rosters())
        self.assertEqual(['only a team captain can draft players'], self.guest.message_history)

    def test_captain_of_both_slots_is_captain_of_neither(self):
        self.console.setCvar('pam_team2_captain', '22222222')
        self.guest.says('!draftplayer kasey')
        self.assertEqual(('22222222;', '55555555;'), self.rosters())
        self.assertEqual(['only a team captain can draft players'], self.guest.message_history)

    def test_invalid_captain_guid_never_matches_a_free_slot(self):
        self.console.setCvar('pam_team1_captain', '0')
        nobody = self.new_player('Nobody', '0', cid='3')
        nobody.says('!draftplayer kasey')
        self.assertEqual(('22222222;', '55555555;'), self.rosters())
        self.assertEqual(['only a team captain can draft players'], nobody.message_history)

    def test_already_on_own_roster(self):
        self.console.setCvar('pam_team1_roster', '22222222;12345678;')
        self.guest.says('!draftplayer kasey')
        self.assertEqual('22222222;12345678;', self.cvar('pam_team1_roster'))
        self.assertEqual(['Kasey is already on the Guest roster'], self.guest.message_history)

    def test_already_on_other_roster(self):
        self.console.setCvar('pam_team2_roster', '55555555;12345678;')
        self.guest.says('!draftplayer kasey')
        self.assertEqual(('22222222;', '55555555;12345678;'), self.rosters())
        self.assertEqual(['Kasey is already on the team 2 roster'], self.guest.message_history)

    def test_guid_prefix_is_not_a_match(self):
        self.console.setCvar('pam_team2_roster', '55555555;1234567;123456789;')
        self.guest.says('!draftplayer kasey')
        self.assertEqual('22222222;12345678;', self.cvar('pam_team1_roster'))

    def test_other_captain_refused(self):
        self.console.setCvar('pam_team2_roster', '')
        other = self.new_player('Other', '55555555', cid='3')
        self.guest.says('!draftplayer other')
        self.assertEqual(('22222222;', ''), self.rosters())
        self.assertEqual(['Other is already on the team 2 roster'], self.guest.message_history)

    def test_guid_zero_refused(self):
        self.new_player('Zero', '0', cid='3')
        self.guest.says('!draftplayer zero')
        self.assertEqual('22222222;', self.cvar('pam_team1_roster'))
        self.assertEqual(['Zero has no valid GUID'], self.guest.message_history)

    def test_roster_too_long_refused(self):
        self.p.max_cvar_length = 17
        self.guest.says('!draftplayer kasey')
        self.assertEqual('22222222;', self.cvar('pam_team1_roster'))
        self.assertEqual(['the Guest roster would be 18 characters, the limit is 17: Kasey not drafted'],
                         self.guest.message_history)

    def test_roster_at_limit_accepted(self):
        self.p.max_cvar_length = 18
        self.guest.says('!draftplayer kasey')
        self.assertEqual('22222222;12345678;', self.cvar('pam_team1_roster'))

    def test_missing_player(self):
        self.guest.says('!draftplayer')
        self.assertEqual(['usage: !draftplayer <player>'], self.guest.message_history)


class Test_cutplayer(DraftTestCase):
    """
    Kasey (12345678) and 33333333 drafted to the guest's team 1.
    """

    def setUp(self):
        DraftTestCase.setUp(self)
        self.console.setCvar('pam_team1_roster', '22222222;12345678;33333333;')

    def test_cut_from_own_team(self):
        self.guest.says('!cutplayer kasey')
        self.assertEqual(('22222222;33333333;', '55555555;'), self.rosters())
        self.assertEqual(['Kasey cut from Guest'], self.guest.message_history)

    def test_cut_last_player(self):
        self.console.setCvar('pam_team1_roster', '22222222;12345678;')
        self.guest.says('!cutplayer kasey')
        self.assertEqual('22222222;', self.cvar('pam_team1_roster'))

    def test_guid_without_trailing_separator_is_not_on_roster(self):
        # PAM_CheckRoster needs the trailing ';' too, so PAM doesn't consider this player rostered either
        self.console.setCvar('pam_team1_roster', '22222222;12345678')
        self.guest.says('!cutplayer kasey')
        self.assertEqual('22222222;12345678', self.cvar('pam_team1_roster'))
        self.assertEqual(['Kasey is not on the Guest roster'], self.guest.message_history)

    def test_cut_player_can_be_drafted_by_other_team(self):
        self.guest.says('!cutplayer kasey')
        other = self.new_player('Other', '55555555', cid='3')
        other.says('!draftplayer kasey')
        self.assertEqual(('22222222;33333333;', '55555555;12345678;'), self.rosters())
        self.assertEqual(['Kasey drafted to team 2'], other.message_history)

    def test_cut_offline_player_by_db_id(self):
        offline = self.new_player('Offline', '87654321')
        self.console.setCvar('pam_team1_roster', '22222222;87654321;')
        self.guest.says('!cutplayer @%s' % offline.id)
        self.assertEqual('22222222;', self.cvar('pam_team1_roster'))

    def test_not_a_captain(self):
        self.console.setCvar('pam_team1_captain', '')
        self.guest.says('!cutplayer kasey')
        self.assertEqual('22222222;12345678;33333333;', self.cvar('pam_team1_roster'))
        self.assertEqual(['only a team captain can cut players'], self.guest.message_history)

    def test_cannot_cut_from_other_team(self):
        self.console.setCvar('pam_team1_roster', '22222222;')
        self.console.setCvar('pam_team2_roster', '55555555;12345678;')
        self.guest.says('!cutplayer kasey')
        self.assertEqual(('22222222;', '55555555;12345678;'), self.rosters())
        self.assertEqual(['Kasey is not on the Guest roster'], self.guest.message_history)

    def test_not_on_roster(self):
        self.console.setCvar('pam_team1_roster', '22222222;')
        self.guest.says('!cutplayer kasey')
        self.assertEqual(['Kasey is not on the Guest roster'], self.guest.message_history)

    def test_guid_prefix_is_not_a_match(self):
        self.console.setCvar('pam_team1_roster', '22222222;1234567;123456789;')
        self.guest.says('!cutplayer kasey')
        self.assertEqual('22222222;1234567;123456789;', self.cvar('pam_team1_roster'))
        self.assertEqual(['Kasey is not on the Guest roster'], self.guest.message_history)

    def test_cannot_cut_self(self):
        self.guest.says('!cutplayer guest')
        self.assertEqual('22222222;12345678;33333333;', self.cvar('pam_team1_roster'))
        self.assertEqual(['you are the captain of Guest: you cannot cut yourself'], self.guest.message_history)

    def test_guid_zero_refused(self):
        self.new_player('Zero', '0', cid='3')
        self.guest.says('!cutplayer zero')
        self.assertEqual(['Zero has no valid GUID'], self.guest.message_history)

    def test_missing_player(self):
        self.guest.says('!cutplayer')
        self.assertEqual(['usage: !cutplayer <player>'], self.guest.message_history)
