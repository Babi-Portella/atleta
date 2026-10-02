INSERT INTO telemetry
  (mqtt_username, client_id, topic, boot_id, sample_seq, source,
   accel_x_g, accel_y_g, accel_z_g, payload)
VALUES
  (${mqtt_username}, ${client_id}, ${topic}, ${payload.boot_id},
   ${payload.sample_seq}, ${payload.source}, ${payload.accel_x_g},
   ${payload.accel_y_g}, ${payload.accel_z_g}, ${payload})
ON DUPLICATE KEY UPDATE id=id
