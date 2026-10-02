SELECT permission, action, topic
FROM mqtt_acl
WHERE username = ${username}
ORDER BY id
