# -*- coding: utf-8 -*-

import re
import time

from mock import Mock
from mockito import when

from b3.config import XmlConfigParser
from b3.events import Event
from b3.extplugins.expquery import ExpqueryPlugin
from tests import B3TestCase
from tests import logging_disabled


DEFAULT_CONFIG = """
<configuration plugin="expquery">
  <settings name="settings">
    <set name="reply_cvar">query_result_%(cid)s</set>
    <set name="not_found_value">0</set>
    <set name="pending_ttl">60</set>
  </settings>
  <settings name="tables">
    <set name="xlr_playerstats">client_id</set>
    <set name="xlr_playercards">player_id</set>
  </settings>
  <settings name="props">
    <set name="exp">xlr_playerstats.exp</set>
    <set name="callsign">xlr_playercards.callsign</set>
  </settings>
</configuration>
"""


class FakeCursor(object):

    def __init__(self, rows=None):
        self._rows = rows or []
        self.EOF = not self._rows

    def getRow(self):
        return dict(self._rows[0]) if self._rows else {}

    def close(self):
        pass


class FakeDB(object):
    """
    Just enough of a MySQL stand-in to run the queries the plugin issues
    (the test SQLite backend uses '?' placeholders, the plugin targets MySQL '%s').
    """
    _re_select = re.compile(r'^SELECT (\w+) FROM (\w+)(?: WHERE (\w+) = %s)? LIMIT 1$')
    _re_update = re.compile(r'^UPDATE (\w+) SET (\w+) = %s WHERE (\w+) = %s$')
    _re_insert = re.compile(r'^INSERT INTO (\w+) \((\w+)(?:, (\w+))?\) VALUES')

    def __init__(self):
        self.columns = {
            'clients': ('id', 'guid'),
            'xlr_playerstats': ('id', 'client_id', 'exp', 'skill'),
            'xlr_playercards': ('player_id', 'callsign', 'background', 'emblem'),
        }
        self.rows = {'clients': [], 'xlr_playerstats': [], 'xlr_playercards': []}
        self.queries = []

    def query(self, sql, bindata=None):
        self.queries.append((sql, bindata))
        m = self._re_select.match(sql)
        if m:
            column, table, key = m.groups()
            if column not in self.columns[table]:
                raise Exception("(1054, Unknown column %s)" % column)
            rows = self.rows[table]
            if key:
                rows = [r for r in rows if r.get(key) == bindata[0]]
            return FakeCursor([{column: r.get(column)} for r in rows[:1]])
        m = self._re_update.match(sql)
        if m:
            table, column, key = m.groups()
            for r in self.rows[table]:
                if r.get(key) == bindata[1]:
                    r[column] = bindata[0]
            return FakeCursor()
        m = self._re_insert.match(sql)
        if m:
            table, key, column = m.groups()
            existing = [r for r in self.rows[table] if r.get(key) == bindata[0]]
            if existing and 'ON DUPLICATE KEY UPDATE' in sql:
                existing[0][column] = bindata[1]
            else:
                self.insert(table, **dict(zip([c for c in (key, column) if c], bindata)))
            return FakeCursor()
        raise AssertionError('unexpected query: %s' % sql)

    def insert(self, table, **row):
        if 'id' in self.columns[table] and 'id' not in row:
            row['id'] = len(self.rows[table]) + 1
        self.rows[table].append(row)
        return row


class ExpqueryTestCase(B3TestCase):

    def setUp(self):
        B3TestCase.setUp(self)
        self.console.createEvent('EVT_EXP_GET', 'EXP property get')
        self.console.createEvent('EVT_EXP_SET', 'EXP property set')
        self.console._guidLength = 6

        self.db = FakeDB()
        self.console.storage = Mock()
        self.console.storage.query = Mock(side_effect=self.db.query)
        self.console.setCvar = Mock()

        # XLRstats stand-in: only the bits the plugin touches
        self.xlrstats = Mock()
        self.xlrstats.playerstats_table = 'xlr_playerstats'
        self.xlrstats.defaultskill = 1000
        self.xlrstats.Kfactor_high = 16

        def save_Stat(stat):
            self.db.insert('xlr_playerstats', client_id=stat.client_id, exp=0, skill=stat.skill)
        self.xlrstats.save_Stat = Mock(side_effect=save_Stat)
        when(self.console).getPlugin('xlrstats').thenReturn(self.xlrstats)

        # a known, authenticated player in slot 4 and their stats row
        self.db.insert('clients', id=1, guid='123456')
        self.db.insert('xlr_playerstats', client_id=1, exp=1234, skill=1000)
        self.client = self.make_client(1, '123456', '4', 'theName')

    def make_client(self, id, guid, cid, name):
        client = Mock(id=id, guid=guid, cid=cid)
        client.name = name
        return client

    def init(self, config=DEFAULT_CONFIG):
        conf = XmlConfigParser()
        conf.loadFromString(config)
        self.p = ExpqueryPlugin(self.console, conf)
        with logging_disabled():
            self.p.onLoadConfig()
            self.p.onStartup()

    def get(self, cid='4', qid='17', prop='exp', guid='123456', client=None):
        self.p.onGet(Event(self.console.getEventID('EVT_EXP_GET'),
                           {'guid': guid, 'cid': cid, 'qid': qid, 'prop': prop, 'name': 'theName'}, client))

    def set(self, value, prop='exp', guid='123456', cid='4', client=None):
        self.p.onSet(Event(self.console.getEventID('EVT_EXP_SET'),
                           {'guid': guid, 'cid': cid, 'prop': prop, 'value': value, 'name': 'theName'}, client))

    def row(self, table, key, value):
        for r in self.db.rows[table]:
            if r.get(key) == value:
                return r
        return None


class Test_config(ExpqueryTestCase):

    def test_default_mapping(self):
        self.init()
        self.assertEqual({'exp': ('xlr_playerstats', 'exp'), 'callsign': ('xlr_playercards', 'callsign')},
                         self.p._props)
        self.assertEqual('query_result_%(cid)s', self.p._reply_cvar)

    def test_invalid_identifier_rejected(self):
        self.init(DEFAULT_CONFIG.replace('xlr_playerstats.exp', 'xlr_playerstats.exp;DROP TABLE clients'))
        self.assertNotIn('exp', self.p._props)

    def test_unknown_table_rejected(self):
        self.init(DEFAULT_CONFIG.replace('xlr_playercards.callsign', 'xlr_unknown.callsign'))
        self.assertNotIn('callsign', self.p._props)

    def test_missing_column_disables_prop(self):
        self.db.columns['xlr_playerstats'] = ('id', 'client_id', 'skill')
        self.init()
        self.assertNotIn('exp', self.p._props)
        self.assertIn('callsign', self.p._props)


class Test_get(ExpqueryTestCase):

    def setUp(self):
        ExpqueryTestCase.setUp(self)
        self.init()

    def test_existing_row(self):
        self.get(client=self.client)
        self.console.setCvar.assert_called_once_with('query_result_4', '17;1234')

    def test_integral_float_has_no_decimals(self):
        self.row('xlr_playerstats', 'client_id', 1)['exp'] = 1234.0
        self.get(client=self.client)
        self.console.setCvar.assert_called_once_with('query_result_4', '17;1234')

    def test_resolves_by_guid_when_not_authenticated(self):
        self.get(client=None)
        self.console.setCvar.assert_called_once_with('query_result_4', '17;1234')

    def test_unknown_prop(self):
        self.get(prop='nope', client=self.client)
        self.console.setCvar.assert_called_once_with('query_result_4', '17;0')

    def test_unknown_player(self):
        self.get(guid='999999', client=None)
        self.console.setCvar.assert_called_once_with('query_result_4', '17;0')

    def test_missing_row(self):
        self.db.insert('clients', id=2, guid='654321')
        self.get(guid='654321', client=None)
        self.console.setCvar.assert_called_once_with('query_result_4', '17;0')

    def test_slots_use_separate_dvars(self):
        self.db.insert('clients', id=2, guid='654321')
        self.db.insert('xlr_playerstats', client_id=2, exp=50, skill=1000)
        self.get(cid='4', qid='1', client=self.client)
        self.get(cid='9', qid='2', guid='654321')
        self.assertEqual([('query_result_4', '1;1234'), ('query_result_9', '2;50')],
                         [c[0] for c in self.console.setCvar.call_args_list])


class Test_set(ExpqueryTestCase):

    def setUp(self):
        ExpqueryTestCase.setUp(self)
        self.init()

    def test_absolute_update(self):
        self.set('500', client=self.client)
        self.assertEqual('500', self.row('xlr_playerstats', 'client_id', 1)['exp'])
        self.set('750', client=self.client)
        self.assertEqual('750', self.row('xlr_playerstats', 'client_id', 1)['exp'])
        self.get(client=self.client)
        self.console.setCvar.assert_called_once_with('query_result_4', '17;750')

    def test_creates_missing_playerstats_row_via_xlrstats(self):
        self.db.insert('clients', id=2, guid='654321')
        guest = self.make_client(2, '654321', '5', 'guest')
        self.set('300', guid='654321', cid='5', client=guest)
        self.assertEqual(1, self.xlrstats.save_Stat.call_count)
        row = self.row('xlr_playerstats', 'client_id', 2)
        self.assertEqual('300', row['exp'])
        self.assertEqual(1000, row['skill'])

    def test_creates_missing_playerstats_row_without_xlrstats(self):
        when(self.console).getPlugin('xlrstats').thenReturn(None)
        self.init()
        self.db.insert('clients', id=2, guid='654321')
        self.set('300', guid='654321', client=None)
        self.assertEqual('300', self.row('xlr_playerstats', 'client_id', 2)['exp'])

    def test_playercards_upsert(self):
        self.set('7', prop='callsign', client=self.client)
        self.assertEqual('7', self.row('xlr_playercards', 'player_id', 1)['callsign'])
        self.set('9', prop='callsign', client=self.client)
        self.assertEqual(1, len(self.db.rows['xlr_playercards']))
        self.assertEqual('9', self.row('xlr_playercards', 'player_id', 1)['callsign'])

    def test_unknown_prop_ignored(self):
        before = len(self.db.queries)
        self.set('1', prop='nope', client=self.client)
        self.assertEqual(before, len(self.db.queries))

    def test_invalid_guid_dropped(self):
        self.set('1', guid='0', client=None)
        self.assertEqual({}, self.p._pending)

    def test_new_player_queued_until_auth(self):
        self.set('100', guid='777777', client=None)
        self.set('200', guid='777777', client=None)  # last write wins
        self.assertEqual(1, len(self.p._pending))

        self.db.insert('clients', id=3, guid='777777')
        newbie = self.make_client(3, '777777', '6', 'newbie')
        self.p.onAuth(Event(self.console.getEventID('EVT_CLIENT_AUTH'), None, newbie))
        self.assertEqual({}, self.p._pending)
        self.assertEqual('200', self.row('xlr_playerstats', 'client_id', 3)['exp'])

    def test_pending_expires(self):
        self.set('100', guid='777777', client=None)
        key = list(self.p._pending)[0]
        self.p._pending[key] = ('100', time.time() - 120)
        self.p.onAuth(Event(self.console.getEventID('EVT_CLIENT_AUTH'), None, self.client))
        self.assertEqual({}, self.p._pending)
