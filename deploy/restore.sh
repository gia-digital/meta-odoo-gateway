#!/usr/bin/env bash
# Restaura un respaldo .sql.gz en la base del gateway.
# Uso: deploy/restore.sh <archivo.sql.gz> [--yes]
# Respaldos disponibles (dentro de DEPLOY_PATH):
#   backups/pre-deploy/*.sql.gz                        (antes de cada deploy)
#   backups/scheduled/{daily,weekly,monthly}/*.sql.gz  (servicio backup)
set -Eeuo pipefail
# shellcheck source=deploy/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[[ -f "${1:?Uso: restore.sh <archivo.sql.gz> [--yes]}" ]] || { echo "No existe $1"; exit 1; }
FILE="$(realpath "$1")"

cd "$APP_DIR"
take_lock

if [[ "${2:-}" != "--yes" ]]; then
  read -r -p "Esto reemplaza la base actual con $FILE. Escribe RESTAURAR para continuar: " answer
  [[ "$answer" == "RESTAURAR" ]] || { echo "Cancelado."; exit 1; }
fi

mkdir -p backups/pre-deploy
safety="backups/pre-deploy/$(date +%Y%m%d-%H%M%S)_pre-restore.sql.gz"
log "Respaldo de seguridad del estado actual en $safety"
dump_db "$safety"

log "Deteniendo api y caddy"
dc stop caddy api

log "Restaurando $FILE"
# shellcheck disable=SC2016 # las variables se expanden dentro del contenedor
gunzip -c "$FILE" | dc exec -T db sh -c \
  'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null

log "Levantando servicios (al arrancar, la API completa columnas e índices faltantes)"
dc up -d api caddy
if wait_healthy 240; then
  dc ps
  log "Restore OK."
else
  log "La API no quedó sana; revisa: docker compose logs api"
  exit 1
fi
