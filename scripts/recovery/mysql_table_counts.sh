#!/bin/sh
set -eu

database=$1
if [ "$database" = "__SOURCE__" ]; then
  database=$MYSQL_DATABASE
fi
case "$database" in
  *[!a-z0-9_]*|'') echo "invalid database name" >&2; exit 2 ;;
esac

mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -B \
  -e "SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA='$database' AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME" \
  | while IFS= read -r table; do
      case "$table" in
        *[!a-zA-Z0-9_]*|'') echo "invalid table name" >&2; exit 2 ;;
      esac
      count=$(mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -B \
        -e "SELECT COUNT(*) FROM $database.$table")
      printf '%s=%s\n' "$table" "$count"
    done
