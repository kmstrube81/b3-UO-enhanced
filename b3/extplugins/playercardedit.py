
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

    requiresConfigFile = False

    # Defaults (can be overridden in plugin XML)
    _table_name = 'xlr_playercards'
    _min_level  = 0  # 0=guest; raise if you want to restrict
    _callsign_min  = 0
    _callsign_max  = 9999
    _background_min  = 0
    _background_max  = 9999
    _emblem_min  = 0
    _emblem_max  = 9999

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
        # callsign
        try:
            self._callsign_min = self.config.getint('settings', 'callsign_min')
        except Exception:
            pass
        try:
            self._callsign_max = self.config.getint('settings', 'callsign_max')
        except Exception:
            pass

        # background
        try:
            self._background_min = self.config.getint('settings', 'background_min')
        except Exception:
            pass
        try:
            self._background_max = self.config.getint('settings', 'background_max')
        except Exception:
            pass

        # emblem
        try:
            self._emblem_min = self.config.getint('settings', 'emblem_min')
        except Exception:
            pass
        try:
            self._emblem_max = self.config.getint('settings', 'emblem_max')
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
            self, 'editplayercard', self._min_level, self.cmd_editplayercard
        )

        self.registerEvent('EVT_PLAYERCARD_EDIT')
        
        self.debug(
            'PlayercardEdit ready. table=%s, callsign[%d-%d], background[%d-%d], emblem[%d-%d]',
            self._table_name,
            self._callsign_min, self._callsign_max,
            self._background_min, self._background_max,
            self._emblem_min, self._emblem_max
        )
    
     # ---- event hook ---------------------------------------------------------
    def onEvent(self, event):
        if event.type == self.console.getEventID('EVT_PLAYERCARD_EDIT'):
            data = event.data or {}
            client = event.client
            if not client:
                return
            callsign   = data.get('callsign')
            background = data.get('background')
            emblem     = data.get('emblem')
            
            callsign = self._validate_field(callsign, self._callsign_min, self._callsign_max)
            if callsign is None:
                client.message(
                    '^1Invalid callsign.^7 Must be %d-%d.' % (self._callsign_min, self._callsign_max)
                )
                return

            background = self._validate_field(background, self._background_min, self._background_max)
            if background is None:
                client.message(
                    '^1Invalid background.^7 Must be %d-%d.' % (self._background_min, self._background_max)
                )
                return

            emblem = self._validate_field(emblem, self._emblem_min, self._emblem_max)
            if emblem is None:
                client.message(
                    '^1Invalid emblem.^7 Must be %d-%d.' % (self._emblem_min, self._emblem_max)
                )
                return
                
            # perform DB write
            ok = self._do_upsert(client, callsign, background, emblem)
            if ok:
                client.message('^7Playercard updated: ^3callsign={0} ^7background={1} ^7emblem={2}'.format(callsign, background, emblem))
                self.verbose('Updated playercard for client_id=%s -> (%s,%s,%s)', client.id, callsign, background, emblem)
            else:
                client.message('^1Failed to update playercard.')
    
    
    def _validate_field(self, raw_val, minv, maxv):
        """
        parse int and ensure within [minv, maxv]; return None if invalid
        """
        try:
            n = int(raw_val)
        except Exception:
            return None
        if n < minv or n > maxv:
            return None
        return n

    def _do_upsert(self, client, callsign, background, emblem):
        """
        Upsert into xlr_playercard using B3's storage connection.
        Defaults to MySQL/MariaDB ON DUPLICATE KEY UPDATE.
        If mysql_upsert is False, uses REPLACE INTO as a portable fallback (requires PRIMARY KEY on client_id).
        """
        t = self._table_name

        client_id = client.id
        # MySQL/MariaDB preferred path
        sql = (
            "INSERT INTO {t} (player_id, callsign, background, emblem) "
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
            #Push dvars
            try:
                self.console.write('set playercard_%s_background %s' % (client.cid, background))
                self.debug('set playercard_%s_background %s', client.cid, background)
            except Exception, e:
                self.debug('failed to set playercard_%s_background: %s', client.cid, e)

            try:
                self.console.write('set playercard_%s_emblem %s' % (client.cid, emblem))
                self.debug('set playercard_%s_emblem %s', client.cid, emblem)
            except Exception, e:
                self.debug('failed to set playercard_%s_emblem: %s', client.cid, e)

            try:
                self.console.write('set playercard_%s_callsign %s' % (client.cid, callsign))
                self.debug('set playercard_%s_callsign %s', client.cid, callsign)
            except Exception, e:
                self.debug('failed to set playercard_%d_callsign: %s', client.cid, e)
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

        callsign = self._validate_field(raw_callsign, self._callsign_min, self._callsign_max)
        if callsign is None:
            client.message(
                '^1Invalid callsign.^7 Must be %d-%d.' % (self._callsign_min, self._callsign_max)
            )
            return

        background = self._validate_field(raw_background, self._background_min, self._background_max)
        if background is None:
            client.message(
                '^1Invalid background.^7 Must be %d-%d.' % (self._background_min, self._background_max)
            )
            return

        emblem = self._validate_field(raw_emblem, self._emblem_min, self._emblem_max)
        if emblem is None:
            client.message(
                '^1Invalid emblem.^7 Must be %d-%d.' % (self._emblem_min, self._emblem_max)
            )
            return
            
        # perform DB write
        ok = self._do_upsert(client, callsign, background, emblem)
        if ok:
            client.message('^7Playercard updated: ^3callsign={0} ^7background={1} ^7emblem={2}'.format(callsign, background, emblem))
            self.verbose('Updated playercard for client_id=%s -> (%s,%s,%s)', client.id, callsign, background, emblem)
        else:
            client.message('^1Failed to update playercard.')
