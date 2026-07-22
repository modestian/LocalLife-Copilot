#!/bin/sh
set -eu

source_file=$1
database=$2
case "$database" in
  *[!a-z0-9_]*|'') echo "invalid restore database name" >&2; exit 2 ;;
esac

mysql -uroot -p"$MYSQL_ROOT_PASSWORD" \
  -e "CREATE DATABASE $database CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
openssl enc -d -aes-256-cbc -pbkdf2 \
  -pass env:BACKUP_ENCRYPTION_PASSWORD -in "$source_file" \
  | mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$database"
