-- ============================================================
-- JyotishVeda — Refactored Database Schema
-- Minimal SPs (Consolidated) & No Unused Reference Tables
-- ============================================================

CREATE DATABASE IF NOT EXISTS jyotishveda
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE jyotishveda;

-- ------------------------------------------------------------
-- Tables
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
  id            CHAR(36)      NOT NULL PRIMARY KEY,
  email         VARCHAR(255)  NOT NULL UNIQUE,
  password_hash VARCHAR(255)  NOT NULL,
  full_name     VARCHAR(150)  NOT NULL,
  role          ENUM('user','admin') NOT NULL DEFAULT 'user',
  is_active     TINYINT(1)    NOT NULL DEFAULT 1,
  address       VARCHAR(255)  NULL,
  latitude      DECIMAL(9,6)  NULL,
  longitude     DECIMAL(9,6)  NULL,
  created_at    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_users_email (email)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_profiles (
  id                CHAR(36)      NOT NULL PRIMARY KEY,
  user_id           CHAR(36)      NOT NULL,
  full_name         VARCHAR(150)  NOT NULL,
  gender            ENUM('male','female','other') NOT NULL,
  birth_date        DATE          NOT NULL,
  birth_time        TIME          NOT NULL,
  birth_place       VARCHAR(255)  NOT NULL,
  latitude          DECIMAL(9,6)  NOT NULL,
  longitude         DECIMAL(9,6)  NOT NULL,
  timezone_offset   DECIMAL(4,2)  NOT NULL,
  focus_areas       JSON          NULL,
  notes             TEXT          NULL,
  horoscope_system  ENUM('vedic','western') NOT NULL DEFAULT 'vedic',
  is_premium        TINYINT(1)    NOT NULL DEFAULT 0,
  relation_label    VARCHAR(50)   NOT NULL DEFAULT 'Self',
  created_at        TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at        TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_profiles_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_profiles_user (user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS numerology_reports (
  id                CHAR(36)      NOT NULL PRIMARY KEY,
  profile_id        CHAR(36)      NOT NULL,
  user_id           CHAR(36)      NOT NULL,
  mulank            INT           NOT NULL,
  bhagyank          INT           NOT NULL,
  namank_chaldean   INT           NOT NULL,
  namank_pythagorean INT          NOT NULL,
  report_json       JSON          NOT NULL,
  created_at        TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_numerology_profile FOREIGN KEY (profile_id) REFERENCES user_profiles(id) ON DELETE CASCADE,
  CONSTRAINT fk_numerology_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_numerology_profile (profile_id),
  INDEX idx_numerology_user (user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS matchmaking_reports (
  id                  CHAR(36)      NOT NULL PRIMARY KEY,
  user_id             CHAR(36)      NOT NULL,
  partner1_name       VARCHAR(150)  NOT NULL,
  partner1_birth_date DATE          NOT NULL,
  partner2_name       VARCHAR(150)  NOT NULL,
  partner2_birth_date DATE          NOT NULL,
  total_score         DECIMAL(4,1)  NOT NULL,
  max_score           DECIMAL(4,1)  NOT NULL DEFAULT 36.0,
  manglik_status      VARCHAR(50)   NULL,
  report_json         JSON          NOT NULL,
  created_at          TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_match_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_match_user (user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS ai_sessions (
  id            CHAR(36)      NOT NULL PRIMARY KEY,
  user_id       CHAR(36)      NOT NULL,
  profile_id    CHAR(36)      NOT NULL,
  tradition     VARCHAR(30)   NOT NULL DEFAULT 'parashari',
  title         VARCHAR(150)  NOT NULL DEFAULT 'New Consultation',
  created_at    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_ai_session_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_ai_session_profile FOREIGN KEY (profile_id) REFERENCES user_profiles(id) ON DELETE CASCADE,
  INDEX idx_ai_session_user (user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS ai_messages (
  id            CHAR(36)      NOT NULL PRIMARY KEY,
  seq           BIGINT        NOT NULL AUTO_INCREMENT,
  session_id    CHAR(36)      NOT NULL,
  role          ENUM('user','assistant') NOT NULL,
  content       TEXT          NOT NULL,
  created_at    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_ai_message_seq (seq),
  CONSTRAINT fk_ai_message_session FOREIGN KEY (session_id) REFERENCES ai_sessions(id) ON DELETE CASCADE,
  INDEX idx_ai_message_session (session_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS blogs (
  id            INT           NOT NULL AUTO_INCREMENT PRIMARY KEY,
  title         VARCHAR(255)  NOT NULL,
  content       LONGTEXT      NOT NULL,
  preview       VARCHAR(500)  NULL,
  image_url     VARCHAR(500)  NULL,
  category      VARCHAR(100)  NULL,
  sub_category  VARCHAR(100)  NULL,
  status        ENUM('Published', 'Draft') NOT NULL DEFAULT 'Draft',
  tags          JSON          NULL,
  meta_title    VARCHAR(255)  NULL,
  meta_keywords JSON          NULL,
  pinned        TINYINT(1)    NOT NULL DEFAULT 0,
  created_at    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS blog_categories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  parent_id INT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (parent_id) REFERENCES blog_categories(id) ON DELETE CASCADE,
  UNIQUE(parent_id, name)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS system_logs (
    id CHAR(36) PRIMARY KEY,
    level ENUM('info', 'warning', 'error') NOT NULL,
    message TEXT NOT NULL,
    module VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    id CHAR(36) PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    currency VARCHAR(10) DEFAULT 'INR',
    status ENUM('success', 'failed', 'pending') NOT NULL,
    payment_method VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ------------------------------------------------------------
-- Consolidated Master Stored Procedures
-- ------------------------------------------------------------

DELIMITER //

-- 1. User Operations
CREATE PROCEDURE IF NOT EXISTS sp_user_ops(
    IN p_action VARCHAR(20), 
    IN p_id CHAR(36), 
    IN p_email VARCHAR(255), 
    IN p_password_hash VARCHAR(255), 
    IN p_full_name VARCHAR(150),
    IN p_address VARCHAR(255),
    IN p_latitude DECIMAL(9,6),
    IN p_longitude DECIMAL(9,6)
)
BEGIN
    IF p_action = 'create' THEN
        INSERT INTO users (id, email, password_hash, full_name, address, latitude, longitude) 
        VALUES (p_id, p_email, p_password_hash, p_full_name, p_address, p_latitude, p_longitude);
        SELECT id, email, full_name, role, address, latitude, longitude, created_at FROM users WHERE id = p_id;
    ELSEIF p_action = 'get_by_email' THEN
        SELECT id, email, password_hash, full_name, role, is_active, address, latitude, longitude FROM users WHERE email = p_email;
    ELSEIF p_action = 'get_by_id' THEN
        SELECT id, email, full_name, role, is_active, address, latitude, longitude, created_at FROM users WHERE id = p_id;
    ELSEIF p_action = 'update' THEN
        UPDATE users SET full_name = p_full_name WHERE id = p_id;
        SELECT id, email, full_name, role, address, latitude, longitude, created_at FROM users WHERE id = p_id;
    END IF;
END //

-- 2. Profile Operations
CREATE PROCEDURE IF NOT EXISTS sp_profile_ops(
    IN p_action VARCHAR(20), 
    IN p_id CHAR(36), IN p_user_id CHAR(36), IN p_full_name VARCHAR(150), IN p_gender VARCHAR(10), 
    IN p_birth_date DATE, IN p_birth_time TIME, IN p_birth_place VARCHAR(255), IN p_latitude DECIMAL(9,6), 
    IN p_longitude DECIMAL(9,6), IN p_timezone_offset DECIMAL(4,2), IN p_focus_areas JSON, IN p_notes TEXT, 
    IN p_horoscope_system VARCHAR(10), IN p_relation_label VARCHAR(50)
)
BEGIN
    IF p_action = 'create' THEN
        INSERT INTO user_profiles (id, user_id, full_name, gender, birth_date, birth_time, birth_place, latitude, longitude, timezone_offset, focus_areas, notes, horoscope_system, relation_label) 
        VALUES (p_id, p_user_id, p_full_name, p_gender, p_birth_date, p_birth_time, p_birth_place, p_latitude, p_longitude, p_timezone_offset, p_focus_areas, p_notes, p_horoscope_system, p_relation_label);
        SELECT * FROM user_profiles WHERE id = p_id;
    ELSEIF p_action = 'get_all' THEN
        SELECT * FROM user_profiles WHERE user_id = p_user_id ORDER BY created_at DESC;
    ELSEIF p_action = 'get_one' THEN
        SELECT * FROM user_profiles WHERE id = p_id AND user_id = p_user_id;
    ELSEIF p_action = 'update' THEN
        UPDATE user_profiles SET full_name=p_full_name, gender=p_gender, birth_date=p_birth_date, birth_time=p_birth_time, birth_place=p_birth_place, latitude=p_latitude, longitude=p_longitude, timezone_offset=p_timezone_offset, focus_areas=p_focus_areas, notes=p_notes, horoscope_system=p_horoscope_system, relation_label=p_relation_label WHERE id = p_id AND user_id = p_user_id;
        SELECT * FROM user_profiles WHERE id = p_id AND user_id = p_user_id;
    ELSEIF p_action = 'delete' THEN
        DELETE FROM user_profiles WHERE id = p_id AND user_id = p_user_id;
        SELECT ROW_COUNT() AS deleted_count;
    END IF;
END //

-- 3. Numerology Operations
CREATE PROCEDURE IF NOT EXISTS sp_numerology_ops(
    IN p_action VARCHAR(20), IN p_id CHAR(36), IN p_profile_id CHAR(36), IN p_user_id CHAR(36), 
    IN p_mulank INT, IN p_bhagyank INT, IN p_namank_chaldean INT, IN p_namank_pythagorean INT, IN p_report_json JSON
)
BEGIN
    IF p_action = 'save' THEN
        INSERT INTO numerology_reports (id, profile_id, user_id, mulank, bhagyank, namank_chaldean, namank_pythagorean, report_json) 
        VALUES (p_id, p_profile_id, p_user_id, p_mulank, p_bhagyank, p_namank_chaldean, p_namank_pythagorean, p_report_json);
        SELECT * FROM numerology_reports WHERE id = p_id;
    ELSEIF p_action = 'get' THEN
        SELECT * FROM numerology_reports WHERE profile_id = p_profile_id AND user_id = p_user_id ORDER BY created_at DESC LIMIT 1;
    END IF;
END //

-- 4. Matchmaking Operations
CREATE PROCEDURE IF NOT EXISTS sp_matchmaking_ops(
    IN p_action VARCHAR(20), IN p_id CHAR(36), IN p_user_id CHAR(36), IN p_partner1_name VARCHAR(150), 
    IN p_partner1_birth_date DATE, IN p_partner2_name VARCHAR(150), IN p_partner2_birth_date DATE, 
    IN p_total_score DECIMAL(4,1), IN p_max_score DECIMAL(4,1), IN p_manglik_status VARCHAR(50), IN p_report_json JSON
)
BEGIN
    IF p_action = 'create' THEN
        INSERT INTO matchmaking_reports (id, user_id, partner1_name, partner1_birth_date, partner2_name, partner2_birth_date, total_score, max_score, manglik_status, report_json) 
        VALUES (p_id, p_user_id, p_partner1_name, p_partner1_birth_date, p_partner2_name, p_partner2_birth_date, p_total_score, p_max_score, p_manglik_status, p_report_json);
        SELECT * FROM matchmaking_reports WHERE id = p_id;
    ELSEIF p_action = 'get_all' THEN
        SELECT id, user_id, partner1_name, partner1_birth_date, partner2_name, partner2_birth_date, total_score, max_score, manglik_status, created_at FROM matchmaking_reports WHERE user_id = p_user_id ORDER BY created_at DESC;
    ELSEIF p_action = 'get_one' THEN
        SELECT * FROM matchmaking_reports WHERE id = p_id AND user_id = p_user_id;
    END IF;
END //

-- 5. AI Operations
CREATE PROCEDURE IF NOT EXISTS sp_ai_ops(
    IN p_action VARCHAR(20), IN p_id CHAR(36), IN p_user_id CHAR(36), IN p_profile_id CHAR(36), 
    IN p_tradition VARCHAR(30), IN p_title VARCHAR(150), IN p_role VARCHAR(10), IN p_content TEXT
)
BEGIN
    IF p_action = 'create_session' THEN
        INSERT INTO ai_sessions (id, user_id, profile_id, tradition, title) VALUES (p_id, p_user_id, p_profile_id, p_tradition, p_title);
        SELECT * FROM ai_sessions WHERE id = p_id;
    ELSEIF p_action = 'get_sessions' THEN
        SELECT s.*, (SELECT COUNT(*) FROM ai_messages m WHERE m.session_id = s.id) AS message_count FROM ai_sessions s WHERE s.user_id = p_user_id ORDER BY s.updated_at DESC;
    ELSEIF p_action = 'get_session' THEN
        SELECT * FROM ai_sessions WHERE id = p_id AND user_id = p_user_id;
    ELSEIF p_action = 'rename_session' THEN
        UPDATE ai_sessions SET title = p_title WHERE id = p_id AND user_id = p_user_id;
        SELECT * FROM ai_sessions WHERE id = p_id AND user_id = p_user_id;
    ELSEIF p_action = 'touch_session' THEN
        UPDATE ai_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = p_id;
    ELSEIF p_action = 'delete_session' THEN
        DELETE FROM ai_sessions WHERE id = p_id AND user_id = p_user_id;
        SELECT ROW_COUNT() AS deleted_count;
    ELSEIF p_action = 'create_message' THEN
        INSERT INTO ai_messages (id, session_id, role, content) VALUES (p_id, p_id, p_role, p_content);
        SELECT * FROM ai_messages WHERE id = p_id;
    ELSEIF p_action = 'get_messages' THEN
        SELECT * FROM ai_messages WHERE session_id = p_id ORDER BY seq ASC;
    END IF;
END //

-- 6. Blog Operations
CREATE PROCEDURE IF NOT EXISTS sp_blog_ops(
    IN p_action VARCHAR(20), IN p_id INT, IN p_title VARCHAR(255), IN p_content LONGTEXT, 
    IN p_preview VARCHAR(500), IN p_image_url VARCHAR(500), IN p_category VARCHAR(100), 
    IN p_sub_category VARCHAR(100), IN p_status VARCHAR(20), IN p_tags JSON, IN p_pinned TINYINT(1)
)
BEGIN
    IF p_action = 'create' THEN
        INSERT INTO blogs (title, content, preview, image_url, category, sub_category, status, tags, pinned) VALUES (p_title, p_content, p_preview, p_image_url, p_category, p_sub_category, p_status, p_tags, p_pinned);
        SELECT * FROM blogs WHERE id = LAST_INSERT_ID();
    ELSEIF p_action = 'get_all' THEN
        SELECT * FROM blogs ORDER BY pinned DESC, created_at DESC;
    ELSEIF p_action = 'get_one' THEN
        SELECT * FROM blogs WHERE id = p_id;
    ELSEIF p_action = 'update' THEN
        UPDATE blogs SET title=p_title, content=p_content, preview=p_preview, image_url=p_image_url, category=p_category, sub_category=p_sub_category, status=p_status, tags=p_tags, pinned=p_pinned WHERE id = p_id;
        SELECT * FROM blogs WHERE id = p_id;
    ELSEIF p_action = 'delete' THEN
        DELETE FROM blogs WHERE id = p_id;
    END IF;
END //

-- 7. Blog Category Operations
CREATE PROCEDURE IF NOT EXISTS sp_category_ops(
    IN p_action VARCHAR(20), IN p_id INT, IN p_name VARCHAR(100), IN p_parent_id INT
)
BEGIN
    IF p_action = 'create_cat' THEN
        INSERT INTO blog_categories (name, parent_id) VALUES (p_name, NULL);
        SELECT * FROM blog_categories WHERE id = LAST_INSERT_ID();
    ELSEIF p_action = 'get_cats' THEN
        SELECT * FROM blog_categories WHERE parent_id IS NULL ORDER BY name ASC;
    ELSEIF p_action = 'delete' THEN
        DELETE FROM blog_categories WHERE id = p_id;
        SELECT ROW_COUNT() AS deleted_count;
    ELSEIF p_action = 'create_subcat' THEN
        INSERT INTO blog_categories (parent_id, name) VALUES (p_parent_id, p_name);
        SELECT id, parent_id AS category_id, name, created_at FROM blog_categories WHERE id = LAST_INSERT_ID();
    ELSEIF p_action = 'get_subcats' THEN
        SELECT id, parent_id AS category_id, name, created_at FROM blog_categories WHERE parent_id IS NOT NULL ORDER BY parent_id ASC, name ASC;
    END IF;
END //

-- Admin and System Logs (From earlier)
CREATE PROCEDURE IF NOT EXISTS sp_get_admin_data(IN p_data_type VARCHAR(50))
BEGIN
    IF p_data_type = 'dashboard_stats' THEN
        SELECT 
            (SELECT COUNT(*) FROM users WHERE role = 'user') AS total_users,
            (SELECT COUNT(*) FROM users WHERE DATE(created_at) = CURRENT_DATE() AND role = 'user') AS new_users_today,
            (SELECT COUNT(DISTINCT user_id) FROM user_profiles WHERE is_premium = 1) AS premium_subscribers,
            (SELECT COUNT(*) FROM blogs) AS total_blogs;
    ELSEIF p_data_type = 'users' THEN
        SELECT id, email, full_name, role, is_active, created_at FROM users WHERE role = 'user' ORDER BY created_at DESC;
    ELSEIF p_data_type = 'ai_logs' THEN
        SELECT s.user_id, s.tradition, m.role, m.content, m.created_at FROM ai_messages m JOIN ai_sessions s ON m.session_id = s.id ORDER BY m.created_at DESC LIMIT 100;
    ELSEIF p_data_type = 'system_logs' THEN
        SELECT id, level, message, module, created_at FROM system_logs ORDER BY created_at DESC LIMIT 100;
    ELSEIF p_data_type = 'revenue_stats' THEN
        SELECT 
            IFNULL(SUM(CASE WHEN status = 'success' THEN amount ELSE 0 END), 0) AS total_revenue,
            IFNULL(SUM(CASE WHEN status = 'success' AND MONTH(created_at) = MONTH(CURRENT_DATE()) AND YEAR(created_at) = YEAR(CURRENT_DATE()) THEN amount ELSE 0 END), 0) AS monthly_revenue,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS total_successful,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS total_failed FROM transactions;
    ELSEIF p_data_type = 'transactions' THEN
        SELECT t.id, t.amount, t.currency, t.status, t.payment_method, t.created_at, u.full_name, u.email FROM transactions t JOIN users u ON t.user_id = u.id ORDER BY t.created_at DESC LIMIT 200;
    END IF;
END //

CREATE PROCEDURE IF NOT EXISTS sp_manage_user(IN p_action VARCHAR(20), IN p_user_id CHAR(36), IN p_value VARCHAR(50))
BEGIN
    IF p_action = 'update_role' THEN
        UPDATE users SET role = p_value WHERE id = p_user_id;
    ELSEIF p_action = 'update_status' THEN
        UPDATE users SET is_active = CAST(p_value AS UNSIGNED) WHERE id = p_user_id;
    ELSEIF p_action = 'delete' THEN
        DELETE FROM user_profiles WHERE user_id = p_user_id;
        DELETE FROM ai_sessions WHERE user_id = p_user_id;
        DELETE FROM transactions WHERE user_id = p_user_id;
        DELETE FROM users WHERE id = p_user_id;
    END IF;
END //

CREATE PROCEDURE IF NOT EXISTS sp_add_system_log(
    IN p_id CHAR(36), IN p_level ENUM('info', 'warning', 'error'), IN p_message TEXT, IN p_module VARCHAR(100)
)
BEGIN
    INSERT INTO system_logs (id, level, message, module) VALUES (p_id, p_level, p_message, p_module);
END //
DELIMITER ;


-- ==========================================
-- ZODIAC SIGNS (Fixed Mathematical/Cosmic Facts)
-- ==========================================
CREATE TABLE IF NOT EXISTS zodiac_signs (
    id VARCHAR(20) PRIMARY KEY,
    name VARCHAR(30) NOT NULL,
    sanskrit VARCHAR(30) NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    element VARCHAR(20) NOT NULL,
    modality VARCHAR(20) NOT NULL,
    ruling_planet VARCHAR(20) NOT NULL,
    tropical_dates VARCHAR(50) NOT NULL,
    sidereal_dates VARCHAR(50) NOT NULL,
    motto VARCHAR(100) NOT NULL,
    chinese_archetype VARCHAR(100) NOT NULL,
    nakshatras VARCHAR(255) NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

DELIMITER //

DROP PROCEDURE IF EXISTS sp_zodiac_ops;
CREATE PROCEDURE sp_zodiac_ops(
    IN p_action VARCHAR(50),
    IN p_id VARCHAR(20)
)
BEGIN
    IF p_action = 'get_all' THEN
        SELECT * FROM zodiac_signs ORDER BY 
        CASE id
            WHEN 'aries' THEN 1 WHEN 'taurus' THEN 2 WHEN 'gemini' THEN 3 WHEN 'cancer' THEN 4
            WHEN 'leo' THEN 5 WHEN 'virgo' THEN 6 WHEN 'libra' THEN 7 WHEN 'scorpio' THEN 8
            WHEN 'sagittarius' THEN 9 WHEN 'capricorn' THEN 10 WHEN 'aquarius' THEN 11 WHEN 'pisces' THEN 12
            ELSE 99 END;
    END IF;
    
    IF p_action = 'get_one' THEN
        SELECT * FROM zodiac_signs WHERE id = p_id;
    END IF;
END //

DELIMITER ;

-- =========================================================
-- Knowledge Graph (Nodes and Relationships)
-- =========================================================

CREATE TABLE IF NOT EXISTS nodes (
    id VARCHAR(50) PRIMARY KEY,
    type VARCHAR(30) NOT NULL,
    title VARCHAR(255) NOT NULL,
    title_native VARCHAR(255),
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_node_type (type),
    INDEX idx_node_title (title)
);

CREATE TABLE IF NOT EXISTS relationships (
    id INT AUTO_INCREMENT PRIMARY KEY,
    source_id VARCHAR(50) NOT NULL,
    target_id VARCHAR(50) NOT NULL,
    label VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE,
    INDEX idx_source (source_id),
    INDEX idx_target (target_id)
);

-- Note: In older MySQL versions, IF NOT EXISTS might not work for ADD COLUMN.
-- Make sure this column is added:
-- ALTER TABLE nodes ADD COLUMN properties JSON NULL;

DELIMITER //
CREATE PROCEDURE IF NOT EXISTS sp_get_nodes(
    IN p_type VARCHAR(30),
    IN p_search VARCHAR(255)
)
BEGIN
    SELECT
        id, type, title, title_native, description, created_at, updated_at, properties
    FROM nodes
    WHERE
        (p_type IS NULL OR p_type = '' OR p_type = 'ALL' OR type = p_type)
        AND
        (p_search IS NULL OR p_search = '' OR LOWER(title) LIKE CONCAT('%', LOWER(p_search), '%') OR LOWER(title_native) LIKE CONCAT('%', LOWER(p_search), '%'))
    ORDER BY title;
END //
DELIMITER ;

DELIMITER //
CREATE PROCEDURE IF NOT EXISTS sp_get_node(
    IN p_node_id VARCHAR(50)
)
BEGIN
    SELECT id, type, title, title_native, description, created_at, updated_at, properties
    FROM nodes
    WHERE id = p_node_id;
END //
DELIMITER ;

DELIMITER //
CREATE PROCEDURE IF NOT EXISTS sp_get_node_relationships(
    IN p_node_id VARCHAR(50)
)
BEGIN
    SELECT
        r.id, r.label, r.source_id, r.target_id, n.title AS target_title, n.type AS target_type
    FROM relationships r
    JOIN nodes n ON n.id = r.target_id
    WHERE r.source_id = p_node_id
    ORDER BY r.id;
END //
DELIMITER ;

DELIMITER //
CREATE PROCEDURE IF NOT EXISTS sp_get_stats()
BEGIN
    SELECT
        (SELECT COUNT(*) FROM nodes) AS nodes,
        (SELECT COUNT(*) FROM relationships) AS relationships;
END //
DELIMITER ;

-- ============================================================
-- 25-YEAR VEDIC DESTINY ROADMAP TABLES & PROCEDURES
-- ============================================================

CREATE TABLE IF NOT EXISTS `user_roadmaps` (
  `id` VARCHAR(100) NOT NULL PRIMARY KEY,
  `user_id` VARCHAR(100) NOT NULL,
  `profile_name` VARCHAR(150) DEFAULT NULL,
  `birth_date` VARCHAR(50) DEFAULT NULL,
  `selected_horizon` VARCHAR(50) NOT NULL DEFAULT '0-5 Years',
  `horizons_generated_json` JSON DEFAULT NULL,
  `milestones_data` JSON NOT NULL,
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX `idx_user_roadmap` (`user_id`, `selected_horizon`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

DELIMITER //
CREATE PROCEDURE IF NOT EXISTS `sp_upsert_user_roadmap`(
    IN p_id VARCHAR(100),
    IN p_user_id VARCHAR(100),
    IN p_profile_name VARCHAR(150),
    IN p_birth_date VARCHAR(50),
    IN p_horizon VARCHAR(50),
    IN p_horizons_json JSON,
    IN p_milestones_json JSON
)
BEGIN
    INSERT INTO `user_roadmaps` (
        `id`, `user_id`, `profile_name`, `birth_date`, `selected_horizon`, `horizons_generated_json`, `milestones_data`
    ) VALUES (
        p_id, p_user_id, p_profile_name, p_birth_date, p_horizon, p_horizons_json, p_milestones_json
    )
    ON DUPLICATE KEY UPDATE
        `profile_name` = VALUES(`profile_name`),
        `birth_date` = VALUES(`birth_date`),
        `selected_horizon` = VALUES(`selected_horizon`),
        `horizons_generated_json` = VALUES(`horizons_generated_json`),
        `milestones_data` = VALUES(`milestones_data`),
        `updated_at` = CURRENT_TIMESTAMP;
END //
DELIMITER ;

DELIMITER //
CREATE PROCEDURE IF NOT EXISTS `sp_get_user_roadmap`(
    IN p_user_id VARCHAR(100)
)
BEGIN
    SELECT * FROM `user_roadmaps` 
    WHERE `user_id` = p_user_id 
    ORDER BY `updated_at` DESC 
    LIMIT 1;
END //
DELIMITER ;

