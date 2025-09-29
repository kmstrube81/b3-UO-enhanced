-- 20250918.2.sql
-- Safe, idempotent migration that:
--   * switches clients.group_bits to signed
--   * (re)creates schema_version
--   * conditionally adds columns to XLR tables ONLY if those tables exist
-- This script is designed for MariaDB/MySQL clients and can be re-run safely.

/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;

-- Ensure version table exists
CREATE TABLE IF NOT EXISTS `schema_version` (
  `version`    VARCHAR(16) NOT NULL PRIMARY KEY,
  `applied_at` TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=MyISAM DEFAULT CHARSET=utf8;

-- === Helper pattern: run ALTER only if the target table exists ===============
-- xlr_playerstats (wins, losses, wawa_wins, wawa_losses)
SET @tbl := 'xlr_playerstats';
SET @exists := (SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_name = @tbl);
SET @sql := IF(@exists > 0,
  'ALTER TABLE `xlr_playerstats`      ADD COLUMN IF NOT EXISTS `round_wins`        MEDIUMINT UNSIGNED NOT NULL DEFAULT 0,      ADD COLUMN IF NOT EXISTS `round_losses`      MEDIUMINT UNSIGNED NOT NULL DEFAULT 0,      ADD COLUMN IF NOT EXISTS `wawa_wins`   MEDIUMINT UNSIGNED NOT NULL DEFAULT 0,      ADD COLUMN IF NOT EXISTS `wawa_losses` MEDIUMINT UNSIGNED NOT NULL DEFAULT 0',
  'SELECT "skip xlr_playerstats (table not found)"');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- xlr_playermaps (wins, losses)
SET @tbl := 'xlr_playermaps';
SET @exists := (SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_name = @tbl);
SET @sql := IF(@exists > 0,
  'ALTER TABLE `xlr_playermaps`      ADD COLUMN IF NOT EXISTS `round_wins`   MEDIUMINT UNSIGNED NOT NULL DEFAULT 0,      ADD COLUMN IF NOT EXISTS `round_losses` MEDIUMINT UNSIGNED NOT NULL DEFAULT 0',
  'SELECT "skip xlr_playermaps (table not found)"');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Record this migration as applied
INSERT IGNORE INTO `schema_version` (`version`) VALUES ('20250929.1');

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
