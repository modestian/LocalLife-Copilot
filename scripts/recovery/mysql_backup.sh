#!/bin/sh
set -eu

target=$1
openssl version >/dev/null
mysqldump \
  -uroot \
  -p"$MYSQL_ROOT_PASSWORD" \
  --single-transaction \
  --routines \
  --events \
  --triggers \
  --hex-blob \
  --set-gtid-purged=OFF \
  "$MYSQL_DATABASE" \
  | openssl enc -aes-256-cbc -salt -pbkdf2 \
      -pass env:BACKUP_ENCRYPTION_PASSWORD -out "$target"
test -s "$target"
