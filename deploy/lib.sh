# shellcheck shell=bash
# Funciones compartidas por los scripts de deploy/. APP_DIR es el DEPLOY_PATH del
# droplet: ahí viven .env, .deploy.env, docker-compose.prod.yml, Caddyfile y backups/.

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"

log() { echo "[$(date '+%F %T')] $*"; }

# Cuando el script corre por SSH desde Actions, esto aparece como anotación del run.
warn() { echo "::warning::$*"; }

dc() {
  docker compose -f "$APP_DIR/docker-compose.prod.yml" --env-file "$APP_DIR/.deploy.env" "$@"
}

# Con --env-file, compose ya no interpola desde .env: DOMAIN se copia aquí para Caddy.
# POSTGRES_PASSWORD no se copia: el volumen ya se inicializó con el valor por defecto.
write_deploy_env() {
  {
    echo "GATEWAY_IMAGE=$1"
    grep -E '^DOMAIN=' "$APP_DIR/.env" | tail -1 || true
  } > "$APP_DIR/.deploy.env"
}

# Deploy, mantenimiento y restore no deben correr a la vez (también a mano).
take_lock() {
  exec 9>/tmp/meta-odoo-gateway-ops.lock
  if ! flock -w 600 9; then
    log "Hay otro deploy, mantenimiento o restore en curso; abortando."
    exit 1
  fi
}

require_docker() {
  if ! docker info >/dev/null 2>&1; then
    log "ERROR: 'docker info' falló. Instala Docker Engine y agrega el usuario al grupo docker (docs/deploy.md)."
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    log "ERROR: falta el plugin 'docker compose' v2."
    exit 1
  fi
}

db_running() {
  dc ps --status running --services 2>/dev/null | grep -qx db
}

dump_db() {
  local dest="$1"
  # shellcheck disable=SC2016 # las variables se expanden dentro del contenedor
  if ! dc exec -T db sh -c \
      'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' \
      | gzip > "$dest"; then
    rm -f "$dest"
    return 1
  fi
}

# Algunas versiones de postgres-backup-local escriben como uid/gid 999 en vez de root.
ensure_backup_dirs() {
  mkdir -p backups/pre-deploy backups/knowledge backups/scheduled
  if [[ "$(stat -c %u backups/scheduled)" != 999 ]]; then
    dc run --rm --no-deps --user 0:0 --entrypoint chown backup -R 999:999 /backups
  fi
}

wait_healthy() {
  local timeout="${1:-240}" elapsed=0 api caddy
  while (( elapsed < timeout )); do
    api="$(docker inspect -f '{{.State.Health.Status}}' "$(dc ps -q api)" 2>/dev/null || echo unknown)"
    caddy="$(docker inspect -f '{{.State.Status}}' "$(dc ps -q caddy)" 2>/dev/null || echo unknown)"
    if [[ "$api" == healthy && "$caddy" == running ]]; then
      return 0
    fi
    sleep 5
    elapsed=$(( elapsed + 5 ))
  done
  return 1
}
