#!/usr/bin/env bash
# Mantenimiento del droplet: paquetes del sistema, imágenes de Postgres/Caddy/backups,
# respaldo de knowledge_uploads y limpieza de Docker.
# Uso:
#   deploy/maintenance.sh                 mantenimiento completo; reinicia si el kernel lo pide
#   deploy/maintenance.sh verify          solo verifica que los servicios estén sanos
#   deploy/maintenance.sh check-backups   falla si no hay respaldo programado reciente
set -Eeuo pipefail
# shellcheck source=deploy/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

PRUNE_UNTIL="${PRUNE_UNTIL:-168h}"
KEEP_KNOWLEDGE_DAYS="${KEEP_KNOWLEDGE_DAYS:-56}"
BACKUP_MAX_AGE_DAYS="${BACKUP_MAX_AGE_DAYS:-2}"
export DEBIAN_FRONTEND=noninteractive

verify() {
  if wait_healthy "${1:-240}"; then
    dc ps
    log "Servicios sanos."
    return 0
  fi
  dc ps || true
  log "La API no está sana después de ${1:-240}s."
  return 1
}

check_backups() {
  local latest
  latest="$(find backups/scheduled/daily -name '*.sql.gz' -size +1k \
    -mtime -"$BACKUP_MAX_AGE_DAYS" -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2- || true)"
  if [[ -z "$latest" ]]; then
    echo "::error::No hay respaldo diario en backups/scheduled/daily de los últimos $BACKUP_MAX_AGE_DAYS días. Revisa: docker compose logs backup"
    ls -la backups/scheduled/daily 2>/dev/null || true
    return 1
  fi
  log "Último respaldo diario: $latest"
  du -sh backups/* 2>/dev/null || true
}

cd "$APP_DIR"

case "${1:-}" in
  verify) verify; exit ;;
  check-backups) check_backups; exit ;;
esac

take_lock
require_docker
[[ -f .deploy.env ]] || { log "Falta .deploy.env: haz al menos un deploy antes."; exit 1; }

SUDO=()
can_sudo=true
if (( EUID != 0 )); then
  if sudo -n apt-get --version >/dev/null 2>&1; then
    SUDO=(sudo -n)
  else
    can_sudo=false
    warn "$(id -un) no tiene sudo sin contraseña: se omiten apt upgrade y el reinicio (docs/deploy.md)."
  fi
fi

if $can_sudo; then
  log "Actualizando paquetes del sistema"
  "${SUDO[@]}" apt-get update -q
  "${SUDO[@]}" apt-get -y -q \
    -o Dpkg::Options::=--force-confdef \
    -o Dpkg::Options::=--force-confold \
    upgrade
  "${SUDO[@]}" apt-get -y -q autoremove --purge
  "${SUDO[@]}" apt-get -y -q autoclean
  "${SUDO[@]}" journalctl --vacuum-time=30d >/dev/null 2>&1 || true
fi

log "Actualizando imágenes de Postgres, Caddy y backups (misma versión mayor)"
ensure_backup_dirs
dc pull db caddy backup
dc up -d --wait --wait-timeout 300 db caddy backup
# shellcheck disable=SC2016 # las variables se expanden dentro del contenedor
dc exec -T db sh -c 'psql -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "ALTER EXTENSION vector UPDATE"'

log "Respaldando knowledge_uploads"
dc exec -T api tar -czf - -C /app knowledge_uploads > "backups/knowledge/$(date +%Y%m%d).tar.gz"
find backups/knowledge -name '*.tar.gz' -mtime +"$KEEP_KNOWLEDGE_DAYS" -delete

log "Limpiando Docker (no toca volúmenes)"
docker container prune -f >/dev/null
docker image prune -af --filter "until=$PRUNE_UNTIL" >/dev/null
docker network prune -f >/dev/null
docker system df
df -h /

if $can_sudo && [[ -f /var/run/reboot-required ]]; then
  log "Se requiere reinicio; reiniciando en 1 minuto."
  echo "REBOOT_SCHEDULED=1"
  "${SUDO[@]}" /sbin/shutdown -r +1
  exit 0
fi

verify
