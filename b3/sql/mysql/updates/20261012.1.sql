-- 20261012.1.sql
-- Safe, idempotent migration that:
--   * (re)creates schema_version
--   * adds xlr_playerstats.exp (CODUO-EXP experience total, written by the expquery plugin)
-- This script is designed for MariaDB/MySQL clients and can be re-run safely.

/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;

-- Ensure version table exists
CREATE TABLE IF NOT EXISTS `schema_version` (
  `version`    VARCHAR(16) NOT NULL PRIMARY KEY,
  `applied_at` TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=MyISAM DEFAULT CHARSET=utf8;

-- === Helper pattern: run ALTER only if the target table exists ===============
-- xlr_playerstats (exp)
SET @tbl := 'xlr_playerstats';
SET @exists := (SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_name = @tbl);
SET @sql := IF(@exists > 0,
  'ALTER TABLE `xlr_playerstats`      ADD COLUMN IF NOT EXISTS `exp`         INT UNSIGNED NOT NULL DEFAULT 0',
  'SELECT "skip xlr_playerstats (table not found)"');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Record this migration as applied
INSERT IGNORE INTO `schema_version` (`version`) VALUES ('20261012.1');

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
