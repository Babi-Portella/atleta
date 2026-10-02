-- Banco exclusivo do laboratório. Não altera athletes/measurements da API existente.
CREATE DATABASE IF NOT EXISTS athlete_lab CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;
USE athlete_lab;

CREATE TABLE IF NOT EXISTS mqtt_users (
  username VARCHAR(64) PRIMARY KEY,
  client_id VARCHAR(64) NOT NULL UNIQUE,
  password_hash VARCHAR(100) NOT NULL,
  is_superuser BOOLEAN NOT NULL DEFAULT FALSE,
  enabled BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS mqtt_acl (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(64) NOT NULL,
  permission ENUM('allow','deny') NOT NULL,
  action ENUM('publish','subscribe','all') NOT NULL,
  topic VARCHAR(255) NOT NULL,
  UNIQUE KEY acl_entry (username, action, topic),
  CONSTRAINT acl_user FOREIGN KEY (username) REFERENCES mqtt_users(username)
);

CREATE TABLE IF NOT EXISTS telemetry (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  received_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  mqtt_username VARCHAR(64) NOT NULL,
  client_id VARCHAR(64) NOT NULL,
  topic VARCHAR(255) NOT NULL,
  boot_id VARCHAR(32) NOT NULL,
  sample_seq BIGINT UNSIGNED NOT NULL,
  source ENUM('device','test') NOT NULL,
  accel_x_g DOUBLE NOT NULL,
  accel_y_g DOUBLE NOT NULL,
  accel_z_g DOUBLE NOT NULL,
  payload JSON NOT NULL,
  UNIQUE KEY sample_identity (mqtt_username, boot_id, sample_seq),
  KEY recent_device (mqtt_username, received_at),
  CONSTRAINT telemetry_user FOREIGN KEY (mqtt_username) REFERENCES mqtt_users(username)
);
