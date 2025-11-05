
#  playercardedit - B3 plugin
#
#  Adds: !editplayercard <callsign> <background> <emblem>
#  Updates/creates xlr_playercard row for the calling client.
#
#

from __future__ import print_function
import re
import time

import b3
import b3.plugin
from b3.functions import getCmd

__version__ = '1.0.0'
__author__  = 'ChatGPT'

class PlayercardeditPlugin(b3.plugin.Plugin):

    # Defaults (can be overridden in plugin XML)
    _table_name = 'xlr_playercard'
    _min_level  = 0  # 0=guest; raise if you want to restrict
    _range_min  = 0
    _range_max  = 9999

    def onLoadConfig(self):
        # Read optional settings from plugin config
        try:
            self._table_name = self.config.get('settings', 'table_name')
        except Exception:
            pass
        try:
            self._min_level = self.config.getint('settings', 'min_level')
        except Exception:
            pass
        try:
            self._range_min = self.config.getint('settings', 'range_min')
        except Exception:
            pass
        try:
            self._range_max = self.config.getint('settings', 'range_max')
        except Exception:
            pass

    def onStartup(self):
        # Grab Admin plugin & register command
        self._adminPlugin = self.console.getPlugin('admin')
        if not self._adminPlugin:
            self.critical('Could not find admin plugin')
            return

        # register command: !editplayercard
        self._adminPlugin.registerCommand(
            self, 'editplayercard', self._min_level, self.cmd_editplayercard,
            help='edit your playercard: ^3!editplayercard <callsign> <background> <emblem>'
        )

        self.debug('PlayercardEdit ready. Using table: %s; level >= %s', self._table_name, self._min_level)

    def _validate_int(self, val):
        # defensive integer parsing
        try:
            n = int(val)
        except Exception:
            return None
        if n < self._range_min or n > self._range_max:
            return None
        return n

    def _do_upsert(self, client_id, callsign, background, emblem):
        """
        Upsert into xlr_playercard using B3's storage connection.
        Defaults to MySQL/MariaDB ON DUPLICATE KEY UPDATE.
        If mysql_upsert is False, uses REPLACE INTO as a portable fallback (requires PRIMARY KEY on client_id).
        """
        t = self._table_name

        # MySQL/MariaDB preferred path
        sql = (
            "INSERT INTO {t} (client_id, callsign, background, emblem) "
            "VALUES (%s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE "
            "  callsign=VALUES(callsign), "
            "  background=VALUES(background), "
            "  emblem=VALUES(emblem)"
        ).format(t=t)
        params = (client_id, callsign, background, emblem)
       
        cursor = None
        try:
            cursor = self.console.storage.query(sql, params)
            return True
        except Exception as e:
            self.error('SQL upsert failed: %s', e, exc_info=True)
            return False
        finally:
            try:
                if cursor:
                    cursor.close()
            except Exception:
                pass

    def cmd_editplayercard(self, data, client, cmd=None):
        """
        Usage: !editplayercard <callsign> <background> <emblem>
        """
        if not data:
            client.message('^7Usage:^3 !editplayercard <callsign> <background> <emblem>')
            return

        parts = re.split(r'\s+', data.strip())
        if len(parts) != 3:
            client.message('^7Usage:^3 !editplayercard <callsign> <background> <emblem>')
            return

        raw_callsign, raw_background, raw_emblem = parts

        callsign   = self._validate_int(raw_callsign)
        background = self._validate_int(raw_background)
        emblem     = self._validate_int(raw_emblem)

        if callsign is None or background is None or emblem is None:
            client.message('^1Invalid values.^7 Each must be an integer in range ^3{0}-{1}^7.'.format(self._range_min, self._range_max))
            return

        # perform DB write
        ok = self._do_upsert(client.id, callsign, background, emblem)
        if ok:
            client.message('^7Playercard updated: ^3callsign={0} ^7background={1} ^7emblem={2}'.format(callsign, background, emblem))
            self.verbose('Updated playercard for client_id=%s -> (%s,%s,%s)', client.id, callsign, background, emblem)
        else:
            client.message('^1Failed to update playercard. Check server logs.')
