#!/usr/bin/env bash
# نسخة احتياطية متسقة لقاعدة SQLite (آمنة أثناء عمل الخدمة). تشغيل يومي عبر cron/systemd timer.
set -euo pipefail
DB="${DB_PATH:-/opt/aipro/data/aipro.db}"
OUT="${BACKUP_DIR:-/opt/aipro/backups}"
mkdir -p "$OUT"
F="$OUT/aipro-$(date +%Y%m%d-%H%M%S).db"
python3 - "$DB" "$F" <<'PY'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2])
src.backup(dst); dst.close(); src.close()
PY
gzip "$F"
find "$OUT" -name 'aipro-*.db.gz' -mtime +30 -delete   # احتفظ بآخر 30 يومًا
echo "backup: $F.gz"
