-- 2025-10-02 — Add preferred_name to clients, create xlr_playercards for banner settings
-- Safe to run multiple times.

-- Ensure version table exists
CREATE TABLE IF NOT EXISTS `schema_version` (
  `version`    VARCHAR(16) NOT NULL PRIMARY KEY,
  `applied_at` TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=MyISAM DEFAULT CHARSET=utf8;

-- 1) preferred_name on clients
ALTER TABLE `clients`
  ADD COLUMN IF NOT EXISTS `preferred_name` VARCHAR(64) NULL AFTER `name`;

-- 2) Player cards table (per-player banner options)
CREATE TABLE IF NOT EXISTS `xlr_playercards` (
  `player_id`  INT UNSIGNED NOT NULL,
  `background` SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  `emblem`     SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  `callsign`   SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`player_id`)
) ENGINE=MyISAM DEFAULT CHARSET=utf8;

-- 3) Optional: seed existing players to zeroed banner if you want (comment out if not desired)
 INSERT IGNORE INTO xlr_playercards (player_id, background, emblem, callsign)
  SELECT id, 0, 7, 30 FROM clients;

-- Record this migration as applied
INSERT IGNORE INTO `schema_version` (`version`) VALUES ('20251002.1');
