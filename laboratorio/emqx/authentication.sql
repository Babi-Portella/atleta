SELECT password_hash, is_superuser
FROM mqtt_users
WHERE username = ${username}
  AND client_id = ${clientid}
  AND enabled = 1
LIMIT 1
