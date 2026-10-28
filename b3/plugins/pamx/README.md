# pamx

Team rosters, PAM-X match setup and team match results (wins / losses / draws) for Call of Duty: United Offensive 1.51
running CODUO-X + PAM-X on a `dedicated 2` server.

Load it in `b3.ini`:

```ini
[plugins]
pamx: @b3/conf/plugin_pamx.ini
```

or in `b3.xml`:

```xml
<plugin name="pamx" config="@b3/conf/plugin_pamx.ini" />
```

It needs the `cod` parser and the admin plugin, and works with the MySQL, SQLite and PostgreSQL storage.

## Commands

Team arguments (`<team>`) match a team id first when numeric, then fall back to a case-insensitive name match.
Team names with spaces go in double quotes: `!addplayer "Easy Company" kasey`. Without quotes the first word is the
team and the rest is the player. `!maketeam` also accepts an unquoted multi-word name.

Player arguments use B3's normal lookup: name, partial name, slot number or `@<b3 id>`. `@<b3 id>` also finds players
who are not connected. When several players match, the candidates are listed.

| Command | Default level | What it does |
|---|---|---|
| `!maketeam <team name>` | admin | Create a team (duplicates are rejected regardless of case). Replies with the new id. |
| `!addplayer <team> <player>` | admin | Add a player to a team roster. A player can be on many teams. |
| `!match <team1> <team2> [rifles]` | admin | Set `pam_team1/2_name`, `pam_team1/2_roster` and `pam_mode` (`na_comp` / `na_comp_rifles`), and start recording the match result. |
| `!pug [rifles]` | admin | `pam_mode` = `na_comp_pug` / `na_comp_pug_rifles` |
| `!pub [rifles]` | admin | `pam_mode` = `na_comp_pub` / `na_comp_pub_rifles` |
| `!scrim [rifles]` | admin | `pam_mode` = `na_comp` / `na_comp_rifles`, no teams |
| `!makecaptain <player>` | admin | Make a connected player a PAM captain (`pam_team1_captain` / `pam_team2_captain`). |
| `!captain` | guest | Make yourself a captain. |
| `!draftplayer <player>` | guest | Captains only: add a player to your team's PAM roster (`pam_team1/2_roster`). |
| `!cutplayer <player>` | guest | Captains only: remove a player from your team's PAM roster so another team can draft them. |

`!pug`, `!pub` and `!scrim` cancel an active match (its result is not recorded) and clear the PAM team names and
rosters it set. There is no separate cancel command.

### !match details

- Rosters are the team members' GUIDs, each followed by `;` (`guid1;guid2;`), which is the format PAM's
  `PAM_CheckRoster` looks for. Players with a GUID of `0` or no GUID are skipped with a warning, and you're warned when
  a team has no usable players.
- A roster longer than `max_cvar_length` is refused, never truncated.
- Names and rosters are set before `pam_mode`, because PAM reads the rosters when players (re)connect. PAM restarts the
  map by itself when `pam_mode` changes (`PAM_Restart`). When the mode is already the one `!match` wants, the plugin
  sends `map_restart` so the new rosters are applied.

### Captains

Captains are only used by PAM's draft (the `na_comp_pug*` rule sets), which reads them when the draft starts.

- Both slots free, or both taken: a random slot is assigned (a taken slot is overwritten).
- One slot free: that slot is assigned.
- `!captain` with both slots taken changes nothing and privately replies
  `Sorry but both captains have already been assigned`.
- A player who already holds a slot is never put in the other one too (PAM treats a GUID in both slots as captain of
  neither).
- The player must be connected and have a valid GUID. Empty and `0` count as a free slot.

`!draftplayer <player>` appends the player's GUID to the roster of the slot you captain, the same way a pick in PAM's
draft menu does (`PAM_DraftAddPlayerToRoster`):

- You must hold exactly one captain slot (a GUID in both slots is captain of neither, as in PAM).
- The player needs a valid GUID and must not already be on either roster. The other team's captain counts as being on
  their team. Offline players can be drafted with `@<b3 id>`.
- A roster that would grow past `max_cvar_length` is refused.
- The reply names the team from `pam_team1/2_name` (PAM sets these to the captains' names when the draft starts), or
  `team 1` / `team 2`.
- PAM only reads the rosters when a player connects, so a drafted player is moved onto the team when PAM next runs its
  roster check for them, not instantly. PAM also empties both rosters when its draft starts and at every map end, so
  players drafted before the draft starts are lost.

`!cutplayer <player>` is the reverse, like a cut in PAM's draft menu (`PAM_DraftCutPlayerFromRoster`): it removes the
player's GUID from the roster of the slot you captain, after which either captain can `!draftplayer` them.

- Only your own roster: a player on the other team's roster is reported as not on yours.
- You can't cut yourself.
- Unlike PAM's menu, the player is not moved to spectator. They stay on their current team until they rejoin or are
  drafted and placed by PAM.

## Configuration (`plugin_pamx.ini`)

| Section | Option | Default | Meaning |
|---|---|---|---|
| `settings` | `max_cvar_length` | 255 | Longest roster value `!match` will push. CoD:UO is built on the Quake 3 engine, whose cvar value buffers are 256 bytes, so 255 is safe (about 28 eight-digit GUIDs). |
| `settings` | `max_team_name_length` | 32 | Longest team name (color codes count). Names can't contain `"`, `\` or `;`. |
| `commands` | one per command | see above | Level or group keyword; `command-alias: level` adds an alias. |
| `messages` | one per message | | Texts sent to players, `$variable` placeholders. |

## Database tables

Created on startup when missing (`sql/<backend>/pamx.sql`):

| Table | Columns |
|---|---|
| `pamx_teams` | `id`, `name` (unique, case-insensitive), `wins`, `losses`, `draws`, `time_add`, `time_edit` |
| `pamx_team_players` | `id`, `team_id` → `pamx_teams.id`, `client_id` → `clients.id`, `time_add`; unique on (`team_id`, `client_id`) |
| `pamx_active_match` | one row (`id` = 1): `team1_id`, `team2_id`, `time_add`. The match being recorded, so it survives a B3 restart. |

Rosters store B3 client ids; GUIDs are read from `clients` when `!match` runs.

## How results are recorded

Results are only recorded for a match started with `!match`; with no active match, game ends are ignored.

1. At the end of a map, CODUO-X `endMap()` logs `W;<side>;guid;name;...` and `L;<side>;...`, or `TIE;axis;...` and
   `TIE;allies;...` on a draw. The cod parser turns each player into an `EVT_CLIENT_ACTION` (`match_win`,
   `match_loss`, `match_draw`). These are the same events xlrstats counts. Halftime and between-round
   `map_restart`s log no such lines, so they are never counted.
2. The plugin collects those GUIDs per side and records the result on the `ExitLevel` that follows (or the next
   `InitGame` if `ExitLevel` is missed).
3. Each team's side comes from where its rostered players appear in those lines, so side swaps at halftime don't
   matter. Players on both rosters are ignored.
4. Sanity checks: each team needs at least one rostered player in the lines, all on one side, and the two teams must
   be on opposite sides. Otherwise nothing is recorded and the reason is logged and announced in-game.
5. A win adds a win to the winner and a loss to the loser; a draw adds a draw to both. Both teams are updated in one
   `UPDATE` statement, so the result is all-or-nothing on every backend (including MyISAM, which has no transactions).
6. The active match is cleared after a result or a failed check, so it can never be counted twice. It is also dropped
   at the next `InitGame` if PAM has already emptied the roster cvars (PAM clears them at every map end), so a stale
   match can't be credited with a later game.
