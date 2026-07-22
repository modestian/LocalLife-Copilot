#!/bin/sh
set -eu

database=$1
case "$database" in
  local_life_restore_drill_[a-z0-9]*) ;;
  *) echo "refusing to drop non-drill database" >&2; exit 2 ;;
esac
mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -e "DROP DATABASE $database"
