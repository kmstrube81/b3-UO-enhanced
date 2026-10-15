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

import logging
from mock import Mock
from mockito import mock, when, any as anything
import unittest2 as unittest
from b3.config import XmlConfigParser
from b3.parsers.cod import CodParser

log = logging.getLogger("test")
log.setLevel(logging.INFO)


class CodTestCase(unittest.TestCase):
    """
    Test case that is suitable for testing Cod parser specific features
    """

    @classmethod
    def setUpClass(cls):
        from b3.parsers.q3a.abstractParser import AbstractParser
        from b3.fake import FakeConsole
        AbstractParser.__bases__ = (FakeConsole,)
        # Now parser inheritance hierarchy is :
        # CodParser -> AbstractParser -> FakeConsole -> Parser

        logging.getLogger('output').setLevel(logging.ERROR)

    def setUp(self):
        self.parser_conf = XmlConfigParser()
        self.parser_conf.loadFromString("""<configuration>
                <settings name="server">
                    <set name="game_log"/>
                </settings>
            </configuration>""")
        self.console = CodParser(self.parser_conf)

        self.output_mock = mock()
        # simulate game server actions
        def write(*args, **kwargs):
            pretty_args = map(repr, args) + ["%s=%s" % (k, v) for k, v in kwargs.iteritems()]
            log.info("write(%s)" % ', '.join(pretty_args))
            return self.output_mock.write(*args, **kwargs)
        self.console.write = Mock(wraps=write)

        self.player = self.console.clients.newClient(cid="4", guid="theGuid", name="theName", ip="11.22.33.44")


    def tearDown(self):
        if hasattr(self, "parser"):
            del self.parser.clients
            self.parser.working = False




class Test_parser_API(CodTestCase):

    def test_getPlayerList_without_punkbuster(self):
        # GIVEN
        self.console.PunkBuster = None
        when(self.console).write('status', maxRetries=anything()).thenReturn('''\
map: mp_villa
num score ping guid   name            lastmsg address               qport rate
--- ----- ---- ---------- --------------- ------- --------------------- ------ -----
  0     0    0      0 democlient^7         1650 unknown                 1773  5000
  1     0   55 63281996 BandAid^7              50 11.11.11.11:524        8045 25000
  2     0  157 81554346 hugobongenhielm^7      50 11.11.11.11:524    22481 25000
  3     0  156 86330555 Irish^7                 0 11.11.11.11:9162     14288 25000
  4     0  999 68003079 Ashhole^7             750 11.11.11.11:19978 19033 25000
  5     5   53 318670 bigredtwit^7            011.11.11.11:28966     1259 25000
''')
        # WHEN
        rv = self.console.getPlayerList()
        # THEN
        self.assertDictContainsSubset({
            'slot': '1', 'score': '0', 'ping': '55', 'guid': '63281996', 'name': 'BandAid^7', 'last': '50', 'ip': '11.11.11.11', 'pbid': None
        }, rv.get('1', {}), rv)
        self.assertDictContainsSubset({
            'slot': '2', 'score': '0', 'ping': '157', 'guid': '81554346', 'name': 'hugobongenhielm^7', 'last': '50', 'ip': '11.11.11.11', 'pbid': None
        }, rv.get('2', {}), rv)
        self.assertDictContainsSubset({
            'slot': '3', 'score': '0', 'ping': '156', 'guid': '86330555', 'name': 'Irish^7', 'last': '0', 'ip': '11.11.11.11', 'pbid': None
        }, rv.get('3', {}), rv)
        self.assertDictContainsSubset({
            'slot': '4', 'score': '0', 'ping': '999', 'guid': '68003079', 'name': 'Ashhole^7', 'last': '750', 'ip': '11.11.11.11', 'pbid': None
        }, rv.get('4', {}), rv)
        self.assertDictContainsSubset({
            'slot': '5', 'score': '5', 'ping': '53', 'guid': '318670', 'name': 'bigredtwit^7', 'last': '0', 'ip': '11.11.11.11', 'pbid': None
        }, rv.get('5', {}), rv)



class Test_exp_events(CodTestCase):
    """
    CODUO-EXP GET/SET log lines.
    """

    def setUp(self):
        CodTestCase.setUp(self)
        # startup() is not run by CodTestCase: create the custom events the same way it does
        self.console.createEvent('EVT_EXP_GET', 'EXP property get')
        self.console.createEvent('EVT_EXP_SET', 'EXP property set')
        self.queueEvent_mock = Mock()
        self.console.queueEvent = self.queueEvent_mock

    def last_event(self):
        self.assertTrue(self.queueEvent_mock.called, 'no event was queued')
        return self.queueEvent_mock.call_args[0][0]

    def test_startup_creates_distinct_events(self):
        self.console.write = Mock(return_value='')
        self.console.getMap = Mock(return_value='mp_harbor')
        self.console.getCvar = Mock(return_value=None)
        self.console.startup()
        ids = [self.console.getEventID(k) for k in ('EVT_EXP_GET', 'EVT_EXP_SET')]
        self.assertNotIn(None, ids)
        self.assertEqual(2, len(set(ids)))

    def test_get_line_parts(self):
        match, action, data, client, target = self.console.getLineParts('GET;theGuid;4;17;exp;the;Name')
        self.assertEqual('get', action)
        self.assertIn('qid', match.re.groupindex)  # not swallowed by the say like regex
        self.assertEqual('theGuid', match.group('guid'))
        self.assertEqual('4', match.group('cid'))
        self.assertEqual('17', match.group('qid'))
        self.assertEqual('exp', match.group('prop'))
        self.assertEqual('the;Name', match.group('name'))

    def test_batched_get_event(self):
        self.console.parseLine('GET;theGuid;4;17;exp,Background,emblem;theName')
        event = self.last_event()
        self.assertEqual(self.console.getEventID('EVT_EXP_GET'), event.type)
        self.assertEqual('exp,background,emblem', event.data['prop'])

    def test_set_line_parts(self):
        match, action, data, client, target = self.console.getLineParts('SET;theGuid;4;exp;1234;theName')
        self.assertEqual('set', action)
        self.assertIn('value', match.re.groupindex)
        self.assertEqual('exp', match.group('prop'))
        self.assertEqual('1234', match.group('value'))
        self.assertEqual('theName', match.group('name'))

    def test_set_non_numeric_value_is_ignored(self):
        # falls through to the say like regex, OnSet must not blow up or emit an event
        self.console.parseLine('SET;theGuid;4;exp;lots;theName')
        self.assertFalse(self.queueEvent_mock.called)

    def test_get_malformed_prop_is_ignored(self):
        self.console.parseLine('GET;theGuid;4;17;bad prop;theName')
        self.assertFalse(self.queueEvent_mock.called)

    def test_get_event(self):
        self.console.parseLine('GET;theGuid;4;17;exp;theName')
        event = self.last_event()
        self.assertEqual(self.console.getEventID('EVT_EXP_GET'), event.type)
        self.assertEqual({'guid': 'theGuid', 'cid': '4', 'qid': '17', 'prop': 'exp', 'name': 'theName'}, event.data)
        self.assertIs(self.player, event.client)

    def test_set_event(self):
        self.console.parseLine('SET;theGuid;4;exp;1234;theName')
        event = self.last_event()
        self.assertEqual(self.console.getEventID('EVT_EXP_SET'), event.type)
        self.assertEqual({'guid': 'theGuid', 'cid': '4', 'prop': 'exp', 'value': '1234', 'name': 'theName'},
                         event.data)
        self.assertIs(self.player, event.client)

    def test_guid_mismatch_has_no_client(self):
        self.console.parseLine('SET;otherGuid;4;exp;1234;someoneElse')
        self.assertIsNone(self.last_event().client)

    def test_unknown_cid_has_no_client(self):
        self.console.parseLine('GET;theGuid;12;17;exp;theName')
        self.assertIsNone(self.last_event().client)

    def test_say_still_parsed_as_say(self):
        self.console.parseLine('say;theGuid;4;theName;hello there')
        event = self.last_event()
        self.assertEqual(self.console.getEventID('EVT_CLIENT_SAY'), event.type)
        self.assertEqual('hello there', event.data)

    def test_sayteam_still_parsed_as_sayteam(self):
        self.console.parseLine('sayteam;theGuid;4;theName;hello team')
        self.assertEqual(self.console.getEventID('EVT_CLIENT_TEAM_SAY'), self.last_event().type)
