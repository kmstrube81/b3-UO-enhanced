
#  expquery - B3 plugin
#
#  Bridges CODUO-EXP GSC <-> B3 database for per-player persistent properties.
#
#  The game server logPrints:
#    GET;<guid>;<cid>;<queryID>;<prop>;<name>
#      -> B3 replies via rcon: set query_result_<cid> "<queryID>;<value>"   (not_found_value on any miss)
#    GET;<guid>;<cid>;<queryID>;<prop1>,<prop2>,...;<name>      (batched: one reply for several props)
#      -> set query_result_<cid> "<queryID>;<value1>,<value2>,..."      (same order as requested)
#    SET;<guid>;<cid>;<prop>;<value>;<name>
#      -> B3 writes <table>.<column> = <value>  (absolute total, not a delta)
#
#  <prop> is mapped to a table/column in the plugin config ([props] prop: table.column).
#
#  GSC side contract:
#    * clear query_result_<entnum> before logging a GET
#    * use a unique (incrementing) queryID and keep one query in flight per player
#    * poll the dvar until it starts with "<queryID>;", take the rest, then clear it
#    * on timeout fall back to a default
#    * prefer one batched GET per player: a full server at map start then needs 1 reply per player
#
#  Replies are sent from a worker thread so the B3 event thread never waits on rcon (each rcon write
#  otherwise blocks for the full socket timeout). Pending replies for the same dvar are coalesced:
#  only the newest one is sent, since GSC only waits for its latest queryID.
#
#  The CoD engine ignores an rcon packet arriving within ~500ms of the previous one (any rcon, including
#  B3's own). Replies are therefore spaced reply_interval apart, and a reply the server never answered is
#  resent up to reply_retries times.
#

from __future__ import print_function
import Queue
import re
import select
import socket
import threading
import time

import b3
import b3.plugin

__version__ = '1.0.0'
__author__  = 'kmstrube81'

# identifiers are interpolated into SQL, so they must match this
_RE_IDENT = re.compile(r'^[a-z0-9_]+$', re.IGNORECASE)
_RE_NUMBER = re.compile(r'^-?[0-9]+(?:\.[0-9]+)?$')
_RE_CVAR = re.compile(r'^[a-z0-9_.]+$', re.IGNORECASE)

# engine limit for a dvar value (MAX_CVAR_VALUE_STRING)
_MAX_REPLY_LENGTH = 255

# columns XLRstats rewrites on its own (a GSC SET on these will be overwritten and vice versa)
_XLRSTATS_MANAGED = ('kills', 'deaths', 'teamkills', 'teamdeaths', 'suicides', 'ratio', 'skill', 'assists',
                     'assistskill', 'curstreak', 'winstreak', 'losestreak', 'rounds')

class ExpqueryPlugin(b3.plugin.Plugin):

    requiresConfigFile = False

    # Defaults (can be overridden in plugin XML)
    _reply_cvar      = 'query_result_%(cid)s'
    _not_found_value = '0'
    _pending_ttl     = 60
    _reply_timeout   = 0.3    # seconds to wait for the server to acknowledge a reply
    _reply_interval  = 0.55   # minimum seconds between replies (engine drops rcon within ~500ms of the last)
    _reply_retries   = 3      # resends of a reply the server did not acknowledge
    _async_replies   = True
    _playerstats_table = 'xlr_playerstats'

    def __init__(self, console, config=None):
        b3.plugin.Plugin.__init__(self, console, config)
        self._tables  = {'xlr_playerstats': 'client_id', 'xlr_playercards': 'player_id'}  # table -> key column
        self._props   = {}   # prop -> (table, column)
        self._pending = {}   # (guid, prop) -> (value, timestamp)
        self._xlrstats = None
        self._replies = {}   # cvar -> (newest reply text waiting to be sent, attempt)
        self._last_send = 0.0
        self._replies_lock = threading.Lock()
        self._reply_queue = Queue.Queue()
        self._reply_thread = None

    def onLoadConfig(self):
        # Read optional settings from plugin config
        try:
            self._reply_cvar = self.config.get('settings', 'reply_cvar')
        except Exception:
            pass
        try:
            self._not_found_value = self.config.get('settings', 'not_found_value')
        except Exception:
            pass
        try:
            self._pending_ttl = self.config.getint('settings', 'pending_ttl')
        except Exception:
            pass
        try:
            self._reply_timeout = max(0.01, self.config.getfloat('settings', 'reply_timeout'))
        except Exception:
            pass
        try:
            self._reply_interval = max(0.0, self.config.getfloat('settings', 'reply_interval'))
        except Exception:
            pass
        try:
            self._reply_retries = max(0, self.config.getint('settings', 'reply_retries'))
        except Exception:
            pass
        try:
            self._async_replies = self.config.getboolean('settings', 'async_replies')
        except Exception:
            pass

        # tables: table -> key column (references clients.id)
        try:
            tables = dict(self.config.items('tables'))
        except Exception:
            tables = None
        if tables:
            self._tables = {}
            for table, key in tables.items():
                key = (key or '').strip()
                if not _RE_IDENT.match(table) or not _RE_IDENT.match(key):
                    self.error('invalid table mapping %s: %s (ignored)', table, key)
                    continue
                self._tables[table] = key

        # props: prop -> table.column
        self._props = {}
        try:
            props = self.config.items('props')
        except Exception:
            props = []
        for prop, target in props:
            prop = prop.lower()
            parts = (target or '').strip().split('.')
            if not _RE_IDENT.match(prop) or len(parts) != 2 or \
                    not _RE_IDENT.match(parts[0]) or not _RE_IDENT.match(parts[1]):
                self.error('invalid prop mapping %s: %s (expected table.column)', prop, target)
                continue
            if parts[0] not in self._tables:
                self.error('prop %s maps to table %s which is not listed in [tables] (ignored)', prop, parts[0])
                continue
            self._props[prop] = (parts[0], parts[1])

    def onStartup(self):
        # XLRstats is optional: only used to create missing xlr_playerstats rows the way it does itself
        self._xlrstats = self.console.getPlugin('xlrstats')
        if self._xlrstats:
            self._playerstats_table = self._xlrstats.playerstats_table

        self.registerEvent('EVT_EXP_GET', self.onGet)
        self.registerEvent('EVT_EXP_SET', self.onSet)
        self.registerEvent('EVT_CLIENT_AUTH', self.onAuth)

        # make sure every mapped column exists (e.g. the migration has been run)
        for prop, (table, column) in self._props.items():
            try:
                cursor = self.console.storage.query('SELECT %s FROM %s LIMIT 1' % (column, table))
                cursor.close()
            except Exception, e:
                self.error('prop %s disabled: cannot read %s.%s: %s', prop, table, column, e)
                del self._props[prop]
                continue
            if table == self._playerstats_table and column in _XLRSTATS_MANAGED:
                self.warning('prop %s maps to %s.%s which XLRstats also updates: '
                             'values will overwrite each other', prop, table, column)

        if self._async_replies and not self._reply_thread:
            self._reply_thread = threading.Thread(target=self._reply_worker, name='expquery-replies')
            self._reply_thread.setDaemon(True)
            self._reply_thread.start()

        self.debug('Expquery ready. reply_cvar=%s, reply_timeout=%ss, reply_interval=%ss, reply_retries=%s, '
                   'async=%s, props=%s', self._reply_cvar, self._reply_timeout, self._reply_interval,
                   self._reply_retries, self._async_replies,
                   ', '.join('%s=%s.%s' % (p, t, c) for p, (t, c) in sorted(self._props.items())))

    def onStop(self, event):
        self._reply_queue.put(None)

    def onExit(self, event):
        self._reply_queue.put(None)

    # ---- event hooks ---------------------------------------------------------
    def onGet(self, event):
        data = event.data or {}
        props = [p for p in (data.get('prop') or '').split(',') if p]
        values = dict.fromkeys(props)

        known = [p for p in props if p in self._props]
        for p in props:
            if p not in self._props:
                self.debug('GET for unknown prop %s', p)

        if known:
            client_id = self._resolve(event.client, data.get('guid'))
            if client_id is not None:
                values.update(self._read(known, client_id))

        self._reply(data.get('cid'), data.get('qid'), [values[p] for p in props])

    def onSet(self, event):
        data = event.data or {}
        prop = data.get('prop')
        value = data.get('value')
        guid = data.get('guid')

        target = self._props.get(prop)
        if not target:
            self.debug('SET for unknown prop %s', prop)
            return
        if value is None or not _RE_NUMBER.match(str(value)):
            self.debug('SET %s with non-numeric value %r', prop, value)
            return

        client_id = self._resolve(event.client, guid)
        if client_id is None:
            # not authenticated yet: hold the value until EVT_CLIENT_AUTH (absolute values: last write wins)
            if self._valid_guid(guid):
                self._pending[(guid.upper(), prop)] = (value, time.time())
                self.verbose('SET %s=%s for guid %s queued until authentication', prop, value, guid)
            else:
                self.debug('SET %s=%s dropped: invalid guid %r', prop, value, guid)
            return

        self._write(target, client_id, value, event.client)

    def onAuth(self, event):
        client = event.client
        if not self._pending:
            return

        now = time.time()
        for key, (value, stamp) in self._pending.items():
            if now - stamp > self._pending_ttl:
                self.debug('dropping expired pending SET %s', key)
                del self._pending[key]

        if not client or not client.guid or client.id is None:
            return

        guid = client.guid.upper()
        for (pguid, prop), (value, stamp) in self._pending.items():
            if pguid != guid:
                continue
            del self._pending[(pguid, prop)]
            target = self._props.get(prop)
            if target:
                self.verbose('flushing pending SET %s=%s for %s', prop, value, client.name)
                self._write(target, client.id, value, client)

    # ---- helpers -------------------------------------------------------------
    def _valid_guid(self, guid):
        min_length = getattr(self.console, '_guidLength', 1)
        return bool(guid) and guid != '0' and len(guid) >= min_length

    def _resolve(self, client, guid):
        """
        Return the clients.id for the event: the authenticated client if the parser matched one,
        otherwise a lookup by guid (covers returning players during the authentication window).
        """
        if client and client.id is not None:
            return client.id
        if not self._valid_guid(guid):
            return None
        cursor = None
        try:
            cursor = self.console.storage.query('SELECT id FROM clients WHERE guid = %s LIMIT 1', (guid,))
            if cursor and not cursor.EOF:
                return cursor.getRow()['id']
        except Exception, e:
            self.error('client lookup for guid %s failed: %s', guid, e, exc_info=True)
        finally:
            if cursor:
                cursor.close()
        return None

    def _read(self, props, client_id):
        """
        Read the given (known) props for a player: one query per table.
        Return a dict prop -> value (props without a row are left out).
        """
        by_table = {}
        for prop in props:
            table, column = self._props[prop]
            by_table.setdefault(table, []).append((prop, column))

        values = {}
        for table, wanted in by_table.items():
            columns = []
            for prop, column in wanted:
                if column not in columns:
                    columns.append(column)
            cursor = None
            try:
                cursor = self.console.storage.query('SELECT %s FROM %s WHERE %s = %%s LIMIT 1'
                                                    % (', '.join(columns), table, self._tables[table]), (client_id,))
                if cursor and not cursor.EOF:
                    row = cursor.getRow()
                    for prop, column in wanted:
                        values[prop] = row.get(column)
            except Exception, e:
                self.error('GET %s.(%s) failed: %s', table, ', '.join(columns), e, exc_info=True)
            finally:
                if cursor:
                    cursor.close()
        return values

    def _write(self, target, client_id, value, client=None):
        table, column = target
        key = self._tables[table]
        try:
            if table == self._playerstats_table:
                self._ensure_playerstats(client_id, client)
                sql = 'UPDATE %s SET %s = %%s WHERE %s = %%s' % (table, column, key)
            else:
                sql = ('INSERT INTO {t} ({k}, {c}) VALUES (%s, %s) '
                       'ON DUPLICATE KEY UPDATE {c}=VALUES({c})').format(t=table, k=key, c=column)
            cursor = self.console.storage.query(sql, (client_id, value) if table != self._playerstats_table
                                                else (value, client_id))
            cursor.close()
            self.verbose('SET %s.%s = %s for client_id=%s', table, column, value, client_id)
            return True
        except Exception, e:
            self.error('SET %s.%s = %s for client_id=%s failed: %s', table, column, value, client_id, e, exc_info=True)
            return False

    def _ensure_playerstats(self, client_id, client=None):
        """
        Make sure an xlr_playerstats row exists, using XLRstats' own insert path so defaults match.
        Bypasses XLRstats' minlevel check: EXP is tracked for every player.
        """
        cursor = self.console.storage.query('SELECT id FROM %s WHERE client_id = %%s LIMIT 1'
                                            % self._playerstats_table, (client_id,))
        try:
            if cursor and not cursor.EOF:
                return
        finally:
            if cursor:
                cursor.close()

        if not self._xlrstats:
            cursor = self.console.storage.query('INSERT INTO %s (client_id) VALUES (%%s)'
                                                % self._playerstats_table, (client_id,))
            cursor.close()
            return

        from b3.plugins.xlrstats import PlayerStats
        stats = PlayerStats()
        stats._new = True
        stats.skill = self._xlrstats.defaultskill
        stats.Kfactor = self._xlrstats.Kfactor_high
        stats.client_id = client_id
        self._xlrstats.save_Stat(stats)
        self.debug('created %s row for client_id=%s', self._playerstats_table, client_id)

    def _format(self, value):
        # GSC treats every value as an integer: round to the nearest one (float, Decimal or numeric string)
        if value is None:
            value = self._not_found_value
        try:
            value = int(round(float(value)))
        except (TypeError, ValueError):
            self.debug('non-numeric value %r replaced by %s', value, self._not_found_value)
            value = self._not_found_value
        return str(value).replace('"', '').replace(';', '').replace(',', '')

    def _reply(self, cid, qid, values):
        qid = str(qid).replace('"', '').replace(';', '')
        text = '%s;%s' % (qid, ','.join(self._format(v) for v in values))
        if len(text) > _MAX_REPLY_LENGTH:
            self.warning('reply for query %s is %s chars (dvar limit %s): request fewer props per GET',
                         qid, len(text), _MAX_REPLY_LENGTH)
        try:
            cvar = self._reply_cvar % {'cid': cid}
        except Exception:
            cvar = self._reply_cvar
        if not _RE_CVAR.match(cvar):
            self.error('invalid reply cvar name %r', cvar)
            return

        if not self._async_replies:
            self._send(cvar, text)
            return

        # coalesce: if a reply for this dvar is still waiting, replace it instead of queueing another send
        # (GSC keeps one query in flight per player, so it has stopped waiting for the older one)
        with self._replies_lock:
            older = self._replies.get(cvar)
            self._replies[cvar] = (text, 0)
        if older is None:
            self._reply_queue.put(cvar)
        else:
            self.debug('dropping unsent reply %s for %s (newer query %s)', older[0], cvar, text)

    def _reply_worker(self):
        while True:
            cvar = self._reply_queue.get()
            if cvar is None:
                break
            with self._replies_lock:
                item = self._replies.pop(cvar, None)
            if item is None:
                continue
            text, attempt = item

            # the engine ignores rcon arriving too soon after the previous packet
            wait = self._last_send + self._reply_interval - time.time()
            if wait > 0:
                time.sleep(wait)
            delivered = self._send(cvar, text)
            self._last_send = time.time()
            if delivered:
                continue

            if attempt >= self._reply_retries:
                self.warning('reply %s = %s not acknowledged by the server after %s attempts: giving up',
                             cvar, text, attempt + 1)
                continue
            with self._replies_lock:
                if cvar in self._replies:
                    # a newer query for this slot is already waiting: send that instead
                    self.debug('not resending reply %s for %s (newer query %s)', text, cvar, self._replies[cvar][0])
                    continue
                self._replies[cvar] = (text, attempt + 1)
            self.debug('reply %s = %s not acknowledged: resending (attempt %s)', cvar, text, attempt + 2)
            # back of the queue: other players' replies are not held up by the retry
            self._reply_queue.put(cvar)

    def _send(self, cvar, text):
        """
        Set the reply dvar. Return False if the server did not acknowledge the rcon packet.
        """
        cmd = self.console.getCommand('set', name=cvar, value=text) or 'set %s "%s"' % (cvar, text)
        try:
            output = self.console.output
            if isinstance(getattr(output, 'socket', None), socket.socket):
                delivered = self._rcon_set(output, cmd)
            else:
                # not a q3a rcon (or a test double): no way to tell, assume it arrived
                self.console.write(cmd, maxRetries=1, socketTimeout=self._reply_timeout)
                delivered = True
        except Exception, e:
            self.error('failed to set %s: %s', cvar, e)
            return False
        if delivered:
            self.debug('reply %s = %s', cvar, text)
        return delivered

    def _rcon_set(self, output, cmd):
        """
        Send one rcon command and report whether the server answered it.
        B3's own write() returns '' both for an empty answer (a successful set) and for no answer
        at all (packet ignored by the engine), so the socket is read directly here.
        """
        if self.console.encoding:
            cmd = output.encode_data(cmd, 'RCON')
        with output.lock:
            sock = output.socket
            # discard anything left over (e.g. a late answer to an earlier command)
            while select.select([sock], [], [], 0)[0]:
                if not sock.recv(4096):
                    break
            self.console.verbose('RCON sending (%s:%s) %r', output.host[0], output.host[1], cmd)
            sock.send(output.rconsendstring % (output.password, cmd))
            readables = select.select([sock], [], [], self._reply_timeout)[0]
            if not readables:
                return False
            while readables:
                if not sock.recv(4096):
                    break
                readables = select.select([sock], [], [], 0.05)[0]
            return True
