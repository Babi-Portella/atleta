SELECT
  clientid AS client_id,
  username AS mqtt_username,
  topic,
  payload
FROM "atletas/+/telemetria"
WHERE payload.schema_version = 1
  AND (payload.source = 'device' OR payload.source = 'test')
  AND is_str(payload.boot_id)
  AND is_int(payload.sample_seq)
  AND payload.sample_seq >= 0
  AND is_num(payload.accel_x_g)
  AND is_num(payload.accel_y_g)
  AND is_num(payload.accel_z_g)
