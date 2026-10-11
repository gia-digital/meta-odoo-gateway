#!/usr/bin/env bash
# Despliega una imagen del gateway en el droplet: respalda la base, levanta la
# imagen nueva, verifica salud y regresa a la imagen anterior si falla.
# Uso: deploy/deploy.sh <imagen>   (p. ej. ghcr.io/gia-digital/meta-odoo-gateway:abc1234)
# Requiere haber hecho `docker login ghcr.io` si el paquete es privado.
set -Eeuo pipefail
# shellcheck source=deploy/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

IMAGE="${1:?Uso: deploy.sh <imagen>}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-240}"
KEEP_PREDEPLOY_DAYS="${KEEP_PREDEPLOY_DAYS:-14}"

rollback() {
  local prev="$1"
  if [[ -z "$prev" || "$prev" == "$IMAGE" ]]; then
    log "No hay imagen previa a la cual regresar."
    return
  fi
  log "Rollback a $prev"
  write_deploy_env "$prev"
  if dc pull api && dc up -d --remove-orphans && wait_healthy "$HEALTH_TIMEOUT"; then
    log "Rollback aplicado. Los cambios de esquema de la imagen fallida NO se revierten;"
    log "si hace falta, restaura con deploy/restore.sh backups/pre-deploy/<archivo>."
  else
    log "El rollback tampoco quedó sano; revisa los logs de api y db."
  fi
}

cd "$APP_DIR"
take_lock
require_docker

for f in .env Caddyfile docker-compose.prod.yml; do
  if [[ ! -f "$f" ]]; then
    log "Falta $APP_DIR/$f (.env se crea una vez a partir de .env.example)."
    exit 1
  fi
done

if systemctl is-active --quiet caddy 2>/dev/null; then
  sudo systemctl disable --now caddy || true
fi

mkdir -p knowledge_uploads
chmod 777 knowledge_uploads || true

prev="$(sed -n 's/^GATEWAY_IMAGE=//p' .deploy.env 2>/dev/null || true)"
log "Imagen a desplegar: $IMAGE (anterior: ${prev:-ninguna})"

mkdir -p backups/pre-deploy
if db_running; then
  prev_tag="${prev##*:}"
  dump="backups/pre-deploy/$(date +%Y%m%d-%H%M%S)_${prev_tag:-initial}.sql.gz"
  log "Respaldando base de datos en $dump"
  dump_db "$dump"
else
  log "La base aún no está corriendo; se omite el respaldo previo."
fi

# Libera disco antes del pull (droplet chico); no toca imágenes en uso.
docker image prune -af >/dev/null || true

write_deploy_env "$IMAGE"
ensure_backup_dirs
dc pull api

if dc up -d --remove-orphans && wait_healthy "$HEALTH_TIMEOUT"; then
  log "Deploy OK: $IMAGE"
else
  log "La API no quedó sana en ${HEALTH_TIMEOUT}s. Logs recientes:"
  dc logs --tail=80 api caddy || true
  rollback "$prev"
  exit 1
fi

log "Limpiando imágenes y respaldos pre-deploy de más de $KEEP_PREDEPLOY_DAYS días"
docker image prune -af >/dev/null || true
find backups/pre-deploy -name '*.sql.gz' -mtime +"$KEEP_PREDEPLOY_DAYS" -delete
df -h /
