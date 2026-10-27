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

import unittest2

from mock import Mock
from mockito import when
from b3.config import XmlConfigParser
from b3.plugins.admin import AdminPlugin
from b3.plugins.pamx import PamxPlugin
from tests import logging_disabled


class PamxTestCase(unittest2.TestCase):

    def setUp(self):
        # create a FakeConsole parser (sqlite in memory storage, dict backed cvars)
        self.parser_conf = XmlConfigParser()
        self.parser_conf.loadFromString(r"""<configuration/>""")
        with logging_disabled():
            from b3.fake import FakeConsole
            self.console = FakeConsole(self.parser_conf)

        with logging_disabled():
            self.adminPlugin = AdminPlugin(self.console, '@b3/conf/plugin_admin.ini')
            self.adminPlugin._commands = {}
            self.adminPlugin.onStartup()

        # make sure the admin plugin obtained by other plugins is our admin plugin
        when(self.console).getPlugin('admin').thenReturn(self.adminPlugin)

        self.console.say = Mock()
        self.console.write = Mock()

        with logging_disabled():
            self.p = PamxPlugin(self.console, '@b3/conf/plugin_pamx.ini')
            self.p.onLoadConfig()
            self.p.onStartup()

        with logging_disabled():
            from b3.fake import FakeClient
            self.admin = FakeClient(console=self.console, name="Admin", guid="11111111", groupBits=16)
            self.guest = FakeClient(console=self.console, name="Guest", guid="22222222", groupBits=0)
            self.admin.connects("0")
            self.guest.connects("1")

    def tearDown(self):
        self.console.storage.shutdown()

    ####################################################################################################################

    def new_player(self, name, guid, cid=None):
        """
        Create a player with a database id; connected on slot cid, or offline when cid is None.
        """
        from b3.fake import FakeClient
        player = FakeClient(console=self.console, name=name, guid=guid, groupBits=0)
        player.connects(cid if cid is not None else '99')
        if cid is None:
            player.disconnects()
        return player

    def make_team(self, name, *players):
        team_id = self.p.create_team(name)
        for player in players:
            self.p.add_team_player(team_id, player.id)
        return team_id

    def team(self, team_id):
        return self.p.get_team_by_id(team_id)

    def cvar(self, name):
        cvar = self.console.cvars.get(name)
        return cvar.getString() if cvar else None

    def said(self):
        return [c[0][0] for c in self.console.say.call_args_list]

    ####################################################################################################################

    def result_line(self, action, side, *players):
        """
        Simulate the parser handling one W; / L; / TIE; line (one EVT_CLIENT_ACTION per player).
        """
        for player in players:
            guid = player if isinstance(player, basestring) else player.guid
            self.console.queueEvent(self.console.getEvent('EVT_CLIENT_ACTION', data={
                'action': action, 'guid': guid, 'name': 'someone', 'team': side, 'map': 'mp_harbor',
                'gametype': 'sd'}, client=None))

    def exit_level(self):
        self.console.queueEvent(self.console.getEvent('EVT_GAME_EXIT', data='executed'))

    def init_game(self):
        self.console.queueEvent(self.console.getEvent('EVT_GAME_ROUND_START', data=self.console.game))
