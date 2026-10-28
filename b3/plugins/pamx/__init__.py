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

__author__ = 'kmstrube81'
__version__ = '1.0'

import b3
import b3.plugin
import b3.events
import os
import random

from b3.functions import getCmd


class PamxPlugin(b3.plugin.Plugin):
    """
    Team rosters, PAM-X match setup and team match results (W/L/D) for CoD:UO + PAM-X.
    """
    requiresParsers = ['cod']
    loadAfterPlugins = ['admin']

    _tables = ('pamx_teams', 'pamx_team_players', 'pamx_active_match')

    # characters that would break `set <cvar> "<value>"` over rcon or PAM's ';' separated cvars
    _bad_name_chars = ('"', '\\', ';')

    # actions the cod parser emits (one per player) for the W; / L; / TIE; lines of CODUO-X endMap()
    _result_actions = ('match_win', 'match_loss', 'match_draw')
    _sides = ('axis', 'allies')

    _default_messages = {
        'team_not_found': '^7no team found matching ^3$team',
        'team_invalid_name': '^7invalid team name: max ^3$max ^7characters, no quotes, backslashes or semicolons',
        'team_exists': '^7team ^3$team ^7already exists (id ^3$id^7)',
        'team_created': '^7team ^3$team ^7created with id ^3$id',
        'player_no_id': '^3$player ^7is not registered in the database yet: try again in a few seconds',
        'player_already_on_team': '^3$player ^7is already on ^3$team',
        'player_added': '^3$player ^7added to ^3$team',
        'match_same_team': '^7a team cannot play against itself',
        'match_guid_skipped': '^7skipped ^3$player ^7($team): no valid GUID',
        'match_no_players': '^1warning: ^3$team ^7has no players with a valid GUID',
        'match_roster_too_long': '^7roster of ^3$team ^7is ^1$length ^7characters, the limit is ^3$max^7: '
                                 'match not set',
        'match_set': '^7match set: ^3$team1 ^7($count1) vs ^3$team2 ^7($count2), mode ^3$mode',
        'mode_set': '^7PAM mode set to ^3$mode',
        'match_cancelled': '^7active match ^3$team1 ^7vs ^3$team2 ^7cancelled: its result will not be recorded',
        'captain_not_connected': '^3$player ^7must be connected to be made captain',
        'captain_invalid_guid': '^3$player ^7has no valid GUID',
        'captain_already': '^3$player ^7is already captain of team ^3$slot',
        'captain_set': '^3$player ^7is now captain of team ^3$slot',
        'captain_both_taken': 'Sorry but both captains have already been assigned',
        'draft_not_captain': '^7only a team captain can draft players',
        'draft_already_on_roster': '^3$player ^7is already on the ^3$team ^7roster',
        'draft_roster_full': '^7the ^3$team ^7roster would be ^1$length ^7characters, the limit is ^3$max^7: '
                             '^3$player ^7not drafted',
        'draft_set': '^3$player ^7drafted to ^3$team',
        'cut_not_captain': '^7only a team captain can cut players',
        'cut_self': '^7you are the captain of ^3$team^7: you cannot cut yourself',
        'cut_not_on_roster': '^3$player ^7is not on the ^3$team ^7roster',
        'cut_set': '^3$player ^7cut from ^3$team',
        'result_win': '^7match result: ^3$winner ^7beat ^3$loser',
        'result_draw': '^7match result: ^3$team1 ^7and ^3$team2 ^7drew',
        'result_not_recorded': '^7match result not recorded: $reason',
    }

    def __init__(self, console, config=None):
        self.adminPlugin = None
        self.max_cvar_length = 255
        self.max_team_name_length = 32
        self.active_match = None    # {'team1_id': int, 'team2_id': int} while a !match is in progress
        self._pending = None        # result lines collected at map end, flushed on ExitLevel / next InitGame
        b3.plugin.Plugin.__init__(self, console, config)

    ####################################################################################################################
    #                                                                                                                  #
    #   STARTUP                                                                                                        #
    #                                                                                                                  #
    ####################################################################################################################

    def onLoadConfig(self):
        """
        Load plugin configuration.
        """
        self.max_cvar_length = self.getSetting('settings', 'max_cvar_length', b3.INT, self.max_cvar_length,
                                               lambda x: int(max(x, 1)))
        self.max_team_name_length = self.getSetting('settings', 'max_team_name_length', b3.INT,
                                                    self.max_team_name_length, lambda x: int(min(max(x, 1), 32)))

    def onStartup(self):
        """
        Initialize plugin.
        """
        self.adminPlugin = self.console.getPlugin('admin')

        # create database tables (if needed)
        self.build_database_schema()

        # register our commands
        if 'commands' in self.config.sections():
            for cmd in self.config.options('commands'):
                level = self.config.get('commands', cmd)
                sp = cmd.split('-')
                alias = None
                if len(sp) == 2:
                    cmd, alias = sp

                func = getCmd(self, cmd)
                if func:
                    self.adminPlugin.registerCommand(self, cmd, level, func, alias)

        # restore a match set before a B3 restart
        self.active_match = self.load_active_match()
        if self.active_match:
            self.info('restored active match: team %(team1_id)s vs team %(team2_id)s' % self.active_match)

        self.registerEvent('EVT_CLIENT_ACTION', self.onAction)
        self.registerEvent('EVT_GAME_EXIT', self.onGameExit)
        self.registerEvent('EVT_GAME_ROUND_START', self.onRoundStart)

        self.debug('plugin started')

    def build_database_schema(self):
        """
        Create the plugin tables if any of them is missing (every statement is CREATE ... IF NOT EXISTS).
        """
        current_tables = self.console.storage.getTables()
        if all(t in current_tables for t in self._tables):
            return
        sql_path_main = b3.getAbsolutePath('@b3/plugins/pamx/sql')
        sql_path = os.path.join(sql_path_main, self.console.storage.protocol, 'pamx.sql')
        self.console.storage.queryFromFile(sql_path)
        self.info('created database tables: %s', ', '.join(self._tables))

    ####################################################################################################################
    #                                                                                                                  #
    #   EVENTS                                                                                                         #
    #                                                                                                                  #
    ####################################################################################################################

    def onAction(self, event):
        """
        Handle EVT_CLIENT_ACTION: collect the per-player match_win / match_loss / match_draw actions the cod parser
        emits for the W; / L; / TIE; lines logged by CODUO-X endMap(). These are the same events xlrstats counts.
        Halftime and round restarts never log those lines, so they never get here.
        """
        if not self.active_match:
            return
        data = event.data
        if not isinstance(data, dict):
            return
        action = (data.get('action') or '').lower()
        side = (data.get('team') or '').lower()
        guid = ('%s' % (data.get('guid') or '')).strip()
        if action not in self._result_actions or side not in self._sides or not guid:
            return
        if self._pending is None:
            self._pending = {'sides': {'axis': set(), 'allies': set()}, 'actions': {}}
        self._pending['sides'][side].add(guid)
        self._pending['actions'].setdefault(side, set()).add(action)

    def onGameExit(self, _):
        """
        Handle EVT_GAME_EXIT: the map is over, record the collected result (if any).
        """
        if self._pending is not None:
            self.record_result()

    def onRoundStart(self, _):
        """
        Handle EVT_GAME_ROUND_START (InitGame, logged on every map load and map_restart):
        flush a result whose ExitLevel line we never saw, then drop a match PAM has cleared without a result.
        """
        if self._pending is not None:
            self.record_result()
            return

        if not self.active_match:
            return

        # PAM empties the roster cvars when a map ends (PAM_Postgame); if they are gone while we still hold a match,
        # that map ended without a result line we could use, so stop tracking it rather than count a later game
        if not self.get_cvar_string('pam_team1_roster') and not self.get_cvar_string('pam_team2_roster'):
            self.warning('active match dropped: PAM cleared the rosters without a result being recorded')
            self.clear_active_match()

    ####################################################################################################################
    #                                                                                                                  #
    #   RESULTS                                                                                                        #
    #                                                                                                                  #
    ####################################################################################################################

    def record_result(self):
        """
        Record the collected end of game result for the active match, or explain why it can't be.
        The active match is cleared either way, so the same match is never counted twice.
        """
        pending, self._pending = self._pending, None
        match = self.active_match
        if not match or pending is None:
            return

        team1 = self.get_team_by_id(match['team1_id'])
        team2 = self.get_team_by_id(match['team2_id'])
        if not team1 or not team2:
            self.result_failed('a team of the match no longer exists')
            return

        reason, result = self.evaluate_result(pending, team1, team2)
        if reason:
            self.result_failed(reason)
            return

        now = self.console.time()
        if result == 'draw':
            self.query("UPDATE pamx_teams SET draws = draws + 1, time_edit = %s WHERE id IN (%s, %s)",
                       [now, int(team1['id']), int(team2['id'])]).close()
            self.info('match result: %s drew with %s', team1['name'], team2['name'])
            self.console.say(self.getMessage('result_draw', {'team1': team1['name'], 'team2': team2['name']}))
        else:
            winner, loser = (team1, team2) if result == 'team1' else (team2, team1)
            # one statement updates both rows, so the result is all-or-nothing on every backend (MyISAM included)
            self.query("UPDATE pamx_teams SET "
                       "wins = wins + CASE WHEN id = %s THEN 1 ELSE 0 END, "
                       "losses = losses + CASE WHEN id = %s THEN 1 ELSE 0 END, "
                       "time_edit = %s WHERE id IN (%s, %s)",
                       [int(winner['id']), int(loser['id']), now, int(winner['id']), int(loser['id'])]).close()
            self.info('match result: %s beat %s', winner['name'], loser['name'])
            self.console.say(self.getMessage('result_win', {'winner': winner['name'], 'loser': loser['name']}))

        self.clear_active_match()

    def evaluate_result(self, pending, team1, team2):
        """
        Work out which side each team played on from the GUIDs in the result lines, and the outcome.
        :return: (reason, None) when no result can be recorded, else (None, 'team1' | 'team2' | 'draw')
        """
        roster1 = set(g for _, _, g in self.get_team_guids(team1['id']) if self.is_valid_guid(g))
        roster2 = set(g for _, _, g in self.get_team_guids(team2['id']) if self.is_valid_guid(g))
        # a player on both rosters tells us nothing about which side is which
        shared = roster1 & roster2
        roster1 -= shared
        roster2 -= shared

        side1 = self.team_side(pending['sides'], roster1)
        side2 = self.team_side(pending['sides'], roster2)
        for team, side in ((team1, side1), (team2, side2)):
            if side is None:
                return 'no rostered players of %s were in the game' % team['name'], None
            if side == 'split':
                return 'rostered players of %s were split across both sides' % team['name'], None
        if side1 == side2:
            return 'both teams had their rostered players on %s' % side1, None

        actions = set()
        for side_actions in pending['actions'].values():
            actions |= side_actions
        if actions == set(['match_draw']):
            return None, 'draw'
        if 'match_draw' in actions:
            return 'the game log reported both a draw and a winner', None

        winners = [s for s, a in pending['actions'].items() if 'match_win' in a]
        losers = [s for s, a in pending['actions'].items() if 'match_loss' in a]
        if len(winners) > 1 or len(losers) > 1 or set(winners) & set(losers):
            return 'the game log reported an inconsistent result', None
        if winners:
            winning_side = winners[0]
        else:
            # only a loser line had players: the other side won
            winning_side = 'allies' if losers[0] == 'axis' else 'axis'
        return None, ('team1' if winning_side == side1 else 'team2')

    @staticmethod
    def team_side(sides, roster):
        """
        :return: 'axis' / 'allies' when the roster's players were all on one side, 'split' when on both, None if absent
        """
        on_axis = bool(roster & sides['axis'])
        on_allies = bool(roster & sides['allies'])
        if on_axis and on_allies:
            return 'split'
        if on_axis:
            return 'axis'
        if on_allies:
            return 'allies'
        return None

    def result_failed(self, reason):
        self.warning('match result not recorded: %s', reason)
        self.console.say(self.getMessage('result_not_recorded', {'reason': reason}))
        self.clear_active_match()

    ####################################################################################################################
    #                                                                                                                  #
    #   STORAGE                                                                                                        #
    #                                                                                                                  #
    ####################################################################################################################

    def query(self, sql, bindata=None):
        """
        Run a parameterized query. Write placeholders as %s; they are rewritten to ? for sqlite,
        whose driver does not accept %s (pymysql and psycopg2 do).
        """
        if bindata is not None and self.console.storage.protocol == 'sqlite':
            sql = sql.replace('%s', '?')
        return self.console.storage.query(sql, bindata)

    def get_team_by_id(self, team_id):
        cursor = self.query("SELECT * FROM pamx_teams WHERE id = %s", [int(team_id)])
        row = None if cursor.EOF else cursor.getRow()
        cursor.close()
        return row

    def get_team_by_name(self, name):
        cursor = self.query("SELECT * FROM pamx_teams WHERE LOWER(name) = LOWER(%s)", [name])
        row = None if cursor.EOF else cursor.getRow()
        cursor.close()
        return row

    def create_team(self, name):
        """
        Insert a new team and return its id.
        """
        now = self.console.time()
        cursor = self.query("INSERT INTO pamx_teams (name, wins, losses, draws, time_add, time_edit) "
                            "VALUES (%s, 0, 0, 0, %s, %s)", [name, now, now])
        team_id = cursor.lastrowid
        cursor.close()
        return team_id

    def is_on_team(self, team_id, client_id):
        cursor = self.query("SELECT id FROM pamx_team_players WHERE team_id = %s AND client_id = %s",
                            [int(team_id), int(client_id)])
        found = not cursor.EOF
        cursor.close()
        return found

    def add_team_player(self, team_id, client_id):
        self.query("INSERT INTO pamx_team_players (team_id, client_id, time_add) VALUES (%s, %s, %s)",
                   [int(team_id), int(client_id), self.console.time()]).close()

    def get_team_guids(self, team_id):
        """
        Return a team's rostered players in roster order (invalid GUIDs included, the caller filters).
        :return: list of (client_id, name, guid)
        """
        cursor = self.query("SELECT c.id, c.name, c.guid FROM pamx_team_players AS p "
                            "INNER JOIN clients AS c ON c.id = p.client_id "
                            "WHERE p.team_id = %s ORDER BY p.id", [int(team_id)])
        players = []
        while not cursor.EOF:
            r = cursor.getRow()
            players.append((int(r['id']), r['name'], ('%s' % r['guid']).strip() if r['guid'] is not None else ''))
            cursor.moveNext()
        cursor.close()
        return players

    def load_active_match(self):
        cursor = self.query("SELECT team1_id, team2_id FROM pamx_active_match WHERE id = 1")
        row = None if cursor.EOF else cursor.getRow()
        cursor.close()
        if not row:
            return None
        return {'team1_id': int(row['team1_id']), 'team2_id': int(row['team2_id'])}

    def save_active_match(self, team1_id, team2_id):
        self.query("DELETE FROM pamx_active_match").close()
        self.query("INSERT INTO pamx_active_match (id, team1_id, team2_id, time_add) VALUES (1, %s, %s, %s)",
                   [int(team1_id), int(team2_id), self.console.time()]).close()
        self.active_match = {'team1_id': int(team1_id), 'team2_id': int(team2_id)}
        self._pending = None

    def clear_active_match(self):
        self.query("DELETE FROM pamx_active_match").close()
        self.active_match = None
        self._pending = None

    ####################################################################################################################
    #                                                                                                                  #
    #   HELPERS                                                                                                        #
    #                                                                                                                  #
    ####################################################################################################################

    @staticmethod
    def split_team_arg(data):
        """
        Split command arguments into (team, rest). A leading double quoted string is the team name
        ("Easy Company" kasey), otherwise the first whitespace separated token is.
        :return: (team, rest) or None when the team is missing or its quote is never closed
        """
        data = (data or '').strip()
        if not data:
            return None
        if data[0] == '"':
            end = data.find('"', 1)
            if end == -1:
                return None
            team = data[1:end].strip()
            rest = data[end + 1:].strip()
        else:
            parts = data.split(None, 1)
            team = parts[0]
            rest = parts[1].strip() if len(parts) > 1 else ''
        if not team:
            return None
        return team, rest

    def find_team(self, handle):
        """
        Find a team: a numeric handle matches the team id first and falls back to the name,
        anything else is a case-insensitive name match.
        """
        handle = handle.strip()
        if handle.isdigit():
            team = self.get_team_by_id(handle)
            if team:
                return team
        return self.get_team_by_name(handle)

    def find_team_prompt(self, handle, client):
        team = self.find_team(handle)
        if not team:
            client.message(self.getMessage('team_not_found', {'team': handle}))
        return team

    def is_valid_team_name(self, name):
        if not name or len(name) > self.max_team_name_length:
            return False
        return not any(c in name for c in self._bad_name_chars)

    @staticmethod
    def is_valid_guid(guid):
        guid = ('%s' % guid).strip() if guid is not None else ''
        return guid not in ('', '0')

    def get_cvar_string(self, name):
        """
        Return a server cvar as a stripped string ('' when it doesn't exist or can't be read).
        """
        try:
            cvar = self.console.getCvar(name)
        except Exception as e:
            self.warning('could not read cvar %s: %s', name, e)
            return ''
        if not cvar:
            return ''
        return (cvar.getString() or '').strip()

    def is_connected(self, client):
        return client.cid is not None and self.console.clients.getByCID(client.cid) is client

    @staticmethod
    def wants_rifles(data):
        return (data or '').strip().lower() == 'rifles'

    @staticmethod
    def usage(client, cmd, args):
        client.message('^7usage: %s%s %s' % (getattr(cmd, 'prefix', '!'), cmd.command, args))

    def set_mode(self, mode, client):
        """
        Switch PAM to a non-match mode: the active match (if any) is cancelled and its PAM team names / rosters
        are cleared, so they stop forcing players onto teams. PAM restarts the map by itself when pam_mode changes.
        """
        if self.active_match:
            team1 = self.get_team_by_id(self.active_match['team1_id'])
            team2 = self.get_team_by_id(self.active_match['team2_id'])
            self.clear_active_match()
            for cvar in ('pam_team1_name', 'pam_team2_name', 'pam_team1_roster', 'pam_team2_roster'):
                self.console.setCvar(cvar, '')
            self.info('active match cancelled by mode change to %s', mode)
            client.message(self.getMessage('match_cancelled', {
                'team1': team1['name'] if team1 else '?', 'team2': team2['name'] if team2 else '?'}))
        self.console.setCvar('pam_mode', mode)
        client.message(self.getMessage('mode_set', {'mode': mode}))

    def make_captain(self, target, client, is_self):
        """
        Assign a connected player to a free PAM captain slot (pam_team1_captain / pam_team2_captain).
        Both free or both taken: a random slot (overwritten if taken), unless the player asked for themselves.
        """
        name = target.name
        if not self.is_connected(target):
            client.message(self.getMessage('captain_not_connected', {'player': name}))
            return
        if not self.is_valid_guid(target.guid):
            self.warning('cannot make %s captain: invalid GUID %r', name, target.guid)
            client.message(self.getMessage('captain_invalid_guid', {'player': name}))
            return
        guid = ('%s' % target.guid).strip()

        current = {1: self.get_cvar_string('pam_team1_captain'), 2: self.get_cvar_string('pam_team2_captain')}
        for slot in (1, 2):
            # PAM treats a GUID in both slots as captain of neither, so never assign the same player twice
            if current[slot] == guid:
                client.message(self.getMessage('captain_already', {'player': name, 'slot': slot}))
                return

        free = [slot for slot in (1, 2) if current[slot] in ('', '0')]
        if len(free) == 1:
            slot = free[0]
        elif not free and is_self:
            client.message(self.getMessage('captain_both_taken'))
            return
        else:
            slot = random.choice((1, 2))

        self.console.setCvar('pam_team%s_captain' % slot, guid)
        self.info('%s (%s) is now captain of team %s (was %r)', name, guid, slot, current[slot])
        client.message(self.getMessage('captain_set', {'player': name, 'slot': slot}))

    def captain_slot(self, guid):
        """
        Return the captain slot (1 or 2) held by a GUID, 0 when none.
        Like PAM_DraftIsCaptain, a GUID in both slots is captain of neither.
        """
        if not self.is_valid_guid(guid):
            return 0
        guid = ('%s' % guid).strip()
        slots = [slot for slot in (1, 2) if self.get_cvar_string('pam_team%s_captain' % slot) == guid]
        return slots[0] if len(slots) == 1 else 0

    @staticmethod
    def in_roster(guid, roster):
        # same test as PAM_CheckRoster: ";<guid>;" anywhere in ";<roster>"
        return (';%s;' % guid) in (';' + roster)

    def roster_team_name(self, slot):
        return self.get_cvar_string('pam_team%s_name' % slot) or 'team %s' % slot

    ####################################################################################################################
    #                                                                                                                  #
    #   COMMANDS                                                                                                       #
    #                                                                                                                  #
    ####################################################################################################################

    def cmd_maketeam(self, data, client, cmd=None):
        """
        <team name> - create a team (use double quotes around names with spaces)
        """
        data = (data or '').strip()
        if data[:1] == '"':
            parsed = self.split_team_arg(data)
            if not parsed or parsed[1]:
                self.usage(client, cmd, '<team name>')
                return
            name = parsed[0]
        else:
            name = data
        if not name:
            self.usage(client, cmd, '<team name>')
            return
        if not self.is_valid_team_name(name):
            client.message(self.getMessage('team_invalid_name', {'max': self.max_team_name_length}))
            return

        existing = self.get_team_by_name(name)
        if existing:
            client.message(self.getMessage('team_exists', {'team': existing['name'], 'id': existing['id']}))
            return

        team_id = self.create_team(name)
        self.info('%s created team %s (id %s)', client.name, name, team_id)
        client.message(self.getMessage('team_created', {'team': name, 'id': team_id}))

    def cmd_addplayer(self, data, client, cmd=None):
        """
        <team> <player> - add a player to a team roster (@<id> works for offline players)
        """
        parsed = self.split_team_arg(data)
        if not parsed or not parsed[1]:
            self.usage(client, cmd, '<team> <player>')
            return
        team_handle, player_handle = parsed

        team = self.find_team_prompt(team_handle, client)
        if not team:
            return

        # name / partial name / slot / @id (offline players come from the clients table)
        target = self.adminPlugin.findClientPrompt(player_handle, client)
        if not target:
            return
        if not target.id:
            client.message(self.getMessage('player_no_id', {'player': target.name}))
            return

        if self.is_on_team(team['id'], target.id):
            client.message(self.getMessage('player_already_on_team', {'player': target.name, 'team': team['name']}))
            return

        self.add_team_player(team['id'], target.id)
        self.info('%s added %s (@%s) to team %s', client.name, target.name, target.id, team['name'])
        client.message(self.getMessage('player_added', {'player': target.name, 'team': team['name']}))

    def cmd_match(self, data, client, cmd=None):
        """
        <team1> <team2> [rifles] - set up a PAM match between two teams and record its result
        """
        first = self.split_team_arg(data)
        second = self.split_team_arg(first[1]) if first else None
        if not second or second[1].lower() not in ('', 'rifles'):
            self.usage(client, cmd, '<team1> <team2> [rifles]')
            return

        team1 = self.find_team_prompt(first[0], client)
        if not team1:
            return
        team2 = self.find_team_prompt(second[0], client)
        if not team2:
            return
        if int(team1['id']) == int(team2['id']):
            client.message(self.getMessage('match_same_team'))
            return

        rosters = []
        for team in (team1, team2):
            guids = []
            for client_id, name, guid in self.get_team_guids(team['id']):
                if not self.is_valid_guid(guid):
                    self.warning('match: skipping %s (@%s) of team %s: invalid GUID %r', name, client_id,
                                 team['name'], guid)
                    client.message(self.getMessage('match_guid_skipped', {'player': name, 'team': team['name']}))
                    continue
                if guid not in guids:
                    guids.append(guid)
            if not guids:
                self.warning('match: team %s has no players with a valid GUID', team['name'])
                client.message(self.getMessage('match_no_players', {'team': team['name']}))

            # PAM matches ";<guid>;" against ";<roster>", so every GUID needs its trailing ';'
            roster = ''.join('%s;' % g for g in guids)
            if len(roster) > self.max_cvar_length:
                client.message(self.getMessage('match_roster_too_long', {
                    'team': team['name'], 'length': len(roster), 'max': self.max_cvar_length}))
                return
            rosters.append((roster, len(guids)))

        mode = 'na_comp_rifles' if self.wants_rifles(second[1]) else 'na_comp'
        mode_unchanged = self.get_cvar_string('pam_mode') == mode

        # names and rosters first: PAM reads the rosters when players (re)connect after the restart
        self.console.setCvar('pam_team1_name', team1['name'])
        self.console.setCvar('pam_team2_name', team2['name'])
        self.console.setCvar('pam_team1_roster', rosters[0][0])
        self.console.setCvar('pam_team2_roster', rosters[1][0])
        self.save_active_match(team1['id'], team2['id'])

        if mode_unchanged:
            # PAM only restarts by itself when pam_mode changes
            self.console.write('map_restart')
        else:
            self.console.setCvar('pam_mode', mode)

        self.info('%s set match %s vs %s (%s)', client.name, team1['name'], team2['name'], mode)
        client.message(self.getMessage('match_set', {'team1': team1['name'], 'count1': rosters[0][1],
                                                     'team2': team2['name'], 'count2': rosters[1][1], 'mode': mode}))

    def cmd_pug(self, data, client, cmd=None):
        """
        [rifles] - switch PAM to pug mode
        """
        self.set_mode('na_comp_pug_rifles' if self.wants_rifles(data) else 'na_comp_pug', client)

    def cmd_pub(self, data, client, cmd=None):
        """
        [rifles] - switch PAM to pub mode
        """
        self.set_mode('na_comp_pub_rifles' if self.wants_rifles(data) else 'na_comp_pub', client)

    def cmd_scrim(self, data, client, cmd=None):
        """
        [rifles] - switch PAM to scrim (comp) mode without teams
        """
        self.set_mode('na_comp_rifles' if self.wants_rifles(data) else 'na_comp', client)

    def cmd_makecaptain(self, data, client, cmd=None):
        """
        <player> - make a connected player a PAM team captain
        """
        if not data or not data.strip():
            self.usage(client, cmd, '<player>')
            return
        target = self.adminPlugin.findClientPrompt(data.strip(), client)
        if target:
            self.make_captain(target, client, is_self=False)

    def cmd_captain(self, data, client, cmd=None):
        """
        - make yourself a PAM team captain
        """
        self.make_captain(client, client, is_self=True)

    def cmd_draftplayer(self, data, client, cmd=None):
        """
        <player> - captains only: add a player who isn't on a roster to your team's PAM roster
        """
        if not data or not data.strip():
            self.usage(client, cmd, '<player>')
            return
        slot = self.captain_slot(client.guid)
        if not slot:
            client.message(self.getMessage('draft_not_captain'))
            return

        target = self.adminPlugin.findClientPrompt(data.strip(), client)
        if not target:
            return
        if not self.is_valid_guid(target.guid):
            self.warning('cannot draft %s: invalid GUID %r', target.name, target.guid)
            client.message(self.getMessage('captain_invalid_guid', {'player': target.name}))
            return
        guid = ('%s' % target.guid).strip()

        rosters = dict((s, self.get_cvar_string('pam_team%s_roster' % s)) for s in (1, 2))
        for s in (1, 2):
            # the other captain belongs to their own team even before PAM puts them on its roster
            if self.in_roster(guid, rosters[s]) or (s != slot and self.captain_slot(guid) == s):
                client.message(self.getMessage('draft_already_on_roster', {
                    'player': target.name, 'team': self.roster_team_name(s)}))
                return

        roster = rosters[slot]
        if roster and not roster.endswith(';'):
            roster += ';'
        roster += '%s;' % guid
        team = self.roster_team_name(slot)
        if len(roster) > self.max_cvar_length:
            client.message(self.getMessage('draft_roster_full', {
                'player': target.name, 'team': team, 'length': len(roster), 'max': self.max_cvar_length}))
            return

        self.console.setCvar('pam_team%s_roster' % slot, roster)
        self.info('%s (captain of team %s) drafted %s (%s)', client.name, slot, target.name, guid)
        client.message(self.getMessage('draft_set', {'player': target.name, 'team': team}))

    def cmd_cutplayer(self, data, client, cmd=None):
        """
        <player> - captains only: remove a player from your team's PAM roster so another team can draft them
        """
        if not data or not data.strip():
            self.usage(client, cmd, '<player>')
            return
        slot = self.captain_slot(client.guid)
        if not slot:
            client.message(self.getMessage('cut_not_captain'))
            return

        target = self.adminPlugin.findClientPrompt(data.strip(), client)
        if not target:
            return
        team = self.roster_team_name(slot)
        if target is client:
            client.message(self.getMessage('cut_self', {'team': team}))
            return
        if not self.is_valid_guid(target.guid):
            self.warning('cannot cut %s: invalid GUID %r', target.name, target.guid)
            client.message(self.getMessage('captain_invalid_guid', {'player': target.name}))
            return
        guid = ('%s' % target.guid).strip()

        roster = self.get_cvar_string('pam_team%s_roster' % slot)
        if not self.in_roster(guid, roster):
            client.message(self.getMessage('cut_not_on_roster', {'player': target.name, 'team': team}))
            return

        # rebuild with every GUID followed by its ';', as PAM_CheckRoster expects
        roster = ''.join('%s;' % g for g in roster.split(';') if g and g != guid)
        self.console.setCvar('pam_team%s_roster' % slot, roster)
        self.info('%s (captain of team %s) cut %s (%s)', client.name, slot, target.name, guid)
        client.message(self.getMessage('cut_set', {'player': target.name, 'team': team}))
