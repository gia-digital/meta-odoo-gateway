# Deploy a DigitalOcean (droplet)

Flujo:

```
push main → CI (pytest + validación de deploy) → build Docker → push GHCR
          → SSH → deploy/deploy.sh (respaldo → pull → up → health → rollback si falla)
          → smoke test HTTPS
```

Además, cada domingo corre **Droplet maintenance** (sección 3).

## 1. Preparar el droplet (una sola vez)

### Docker Engine (obligatorio)

Este deploy necesita **Docker Engine + Compose v2 plugin**.  
**No sirve** Podman con el mensaje `Emulate Docker CLI using podman`, ni el binario legacy `docker-compose` 1.29.

En el droplet:

```bash
# Instalar Docker Engine oficial (incluye compose plugin v2)
curl -fsSL https://get.docker.com | sh
sudo systemctl enable --now docker

# Si el usuario de deploy no es root:
sudo usermod -aG docker $USER
# cierra sesión SSH y vuelve a entrar

# Verificar (debe existir el socket y responder el daemon)
ls -l /var/run/docker.sock
docker info
docker compose version
```

Si ves `Emulate Docker CLI using podman` o errores a `/var/run/docker.sock`:

```bash
# Diagnóstico rápido
which docker
docker --version
systemctl status docker || true
ls -l /var/run/docker.sock || echo "NO HAY SOCKET — falta Docker Engine"
```

Quita/desactiva el shim de Podman si compite con Docker, o instala Docker Engine encima con el script de arriba. Luego confirma:

```bash
docker info   # sin mensaje de podman
docker compose version   # Compose version v2.x
```

### Directorio de la app

```bash
mkdir -p ~/meta-odoo-gateway
cd ~/meta-odoo-gateway
```

Copia `.env.example` del repo a `~/meta-odoo-gateway/.env` y completa secretos reales.

Asegura que `DATABASE_URL` apunte al servicio `db` del compose:

```env
DATABASE_URL=postgresql+asyncpg://gateway:gateway@db:5432/gateway
```

Si cambias `POSTGRES_PASSWORD` en el host, alinea usuario/password en `DATABASE_URL`.

En el `.env` del droplet agrega también:

```env
DOMAIN=gia.init.com.mx
```

(No uses `ACME_EMAIL=admin@localhost`; si pones email, que sea uno real.)

Abre puertos (Caddy usa 80/443 para HTTP→HTTPS y Let's Encrypt):

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
```

No abras `:8000` a internet: la API queda en `127.0.0.1:8000` y Caddy hace el proxy público.

### sudo para el mantenimiento semanal

Si `DROPLET_USER` es `root` no hace falta nada. Si es otro usuario (p. ej. `deploy`), el mantenimiento necesita sudo **sin contraseña** solo para `apt-get`, `shutdown` y `journalctl`:

```bash
echo 'deploy ALL=(root) NOPASSWD: /usr/bin/apt-get, /sbin/shutdown, /usr/bin/journalctl' \
  | sudo tee /etc/sudoers.d/deploy-maintenance
sudo chmod 440 /etc/sudoers.d/deploy-maintenance
sudo visudo -c
```

Sin esto, el workflow sigue limpiando Docker y actualizando imágenes, pero se salta `apt upgrade` y el reinicio (lo marca como warning en el run).

## 2. Secrets en GitHub

Repo → **Settings → Secrets and variables → Actions** (y Environment `production` si lo usas):

| Secret | Descripción |
|---|---|
| `DROPLET_HOST` | IP o hostname del droplet |
| `DROPLET_USER` | Usuario SSH (ej. `root` o `deploy`) |
| `DROPLET_SSH_KEY` | Clave privada completa (`-----BEGIN ... PRIVATE KEY-----`) |
| `DROPLET_SSH_PORT` | Puerto SSH (normalmente `22`) |
| `DEPLOY_PATH` | Ruta absoluta, ej. `/home/deploy/meta-odoo-gateway` |
| `GHCR_PULL_TOKEN` | (Opcional) PAT con `read:packages`. Si no existe, se usa `GITHUB_TOKEN` del job |
| `DROPLET_SSH_FINGERPRINT` | (Recomendado) huella SHA256 del host para que Deploy verifique al droplet: `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub \| cut -d' ' -f2` (en el droplet) |
| `DROPLET_SSH_KNOWN_HOSTS` | (Recomendado) salida de `ssh-keyscan -t ed25519 <IP>` desde tu máquina; la usa Maintenance. Sin él, confía en la llave que presente el host |

Y en **Variables** (misma pantalla, pestaña Variables):

| Variable | Descripción |
|---|---|
| `DOMAIN` | (Opcional) p. ej. `gia.init.com.mx`. Activa el smoke test HTTPS externo y el link del environment |

Los jobs de deploy y mantenimiento usan el Environment **production** (GitHub lo crea solo la primera vez). Si le agregas *Required reviewers*, cada deploy **y** el mantenimiento semanal esperan aprobación. Los secrets pueden vivir a nivel repo o del environment.

### SSH key

```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ./gha_deploy -N ""
# pública → ~/.ssh/authorized_keys en el droplet
# privada → secret DROPLET_SSH_KEY
```

### Paquete GHCR

Tras el primer push, en GitHub → **Packages** → `meta-odoo-gateway`:

- Si el paquete es **privado**, el droplet necesita login (el workflow ya lo hace).
- Opcional: haz el paquete **public** para simplificar pulls.

## 3. Workflows

| Archivo | Cuándo | Qué hace |
|---|---|---|
| [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | PR a `main` (y desde Deploy) | `pytest`; shellcheck de `deploy/`; valida `docker-compose.prod.yml` y `Caddyfile`; en PRs, build de la imagen |
| [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) | push a `main` o manual | CI → build/push GHCR → SCP compose + Caddyfile + `deploy/` → SSH `deploy/deploy.sh` → smoke test |
| [`.github/workflows/maintenance.yml`](../.github/workflows/maintenance.yml) | domingo 04:00 (CDMX) o manual | `deploy/maintenance.sh` (ver abajo) → reinicio si hace falta → verifica respaldos → smoke test |

Deploy manual: Actions → **Deploy** → **Run workflow**. Deploy y mantenimiento comparten el grupo de concurrencia `deploy-production`, así que nunca corren a la vez.

`deploy/deploy.sh <imagen>` (en el droplet):

- respalda la base en `backups/pre-deploy/` (se conservan 14 días); si el respaldo falla, no despliega;
- escribe `.deploy.env` con la imagen y el `DOMAIN` del `.env`;
- hace pull y `up -d`, y espera a que la API esté `healthy` y Caddy corriendo;
- si no queda sana, muestra logs y regresa a la imagen anterior (la vuelve a bajar de GHCR).

`deploy/maintenance.sh` (domingos):

- `apt upgrade`, `autoremove` y limpieza de journald (requiere sudo, sección 1);
- actualiza las imágenes de Postgres/pgvector, Caddy y backups (misma versión mayor) y corre `ALTER EXTENSION vector UPDATE`;
- empaqueta `knowledge_uploads/` en `backups/knowledge/` (se conservan 8 semanas);
- limpia contenedores, imágenes y redes sin uso de Docker (no toca volúmenes);
- reinicia el droplet si el kernel lo pide, y el workflow espera a que los servicios vuelvan sanos;
- falla si no hay respaldo diario de la base en los últimos 2 días (`maintenance.sh check-backups`), para que GitHub te avise por correo.

## 4. Verificar

```bash
# en el droplet
cd ~/meta-odoo-gateway
cat .deploy.env
docker compose -f docker-compose.prod.yml --env-file .deploy.env ps
curl -fsS http://127.0.0.1:8000/health
curl -fsSI https://gia.init.com.mx/health
```

URLs:

- Dashboard: `https://gia.init.com.mx/dashboard`
- Webhook Chatwoot: `https://gia.init.com.mx/webhook/chatwoot`

Imagen publicada: `ghcr.io/gia-digital/meta-odoo-gateway:<short-sha>` y `:latest`.

## 5. Rollback

- **Automático**: si la API no queda sana durante el deploy (incluye una migración que falle o una base inaccesible, porque `/health` hace `SELECT 1`), `deploy.sh` regresa a la imagen anterior. Las migraciones que sí se aplicaron **no** se revierten: la imagen anterior ve una revisión de Alembic que no conoce, registra `db_schema_newer_than_code` y arranca sin migrar. Por eso las migraciones deben ser compatibles hacia atrás (ver README, «Migraciones»). Si se dañaron datos, restaura el respaldo pre-deploy (sección 6).
- **Manual**: `git revert` del commit en `main` y push; o bien, en el droplet, con un SHA anterior:

```bash
cd ~/meta-odoo-gateway
docker login ghcr.io   # si el paquete es privado
bash deploy/deploy.sh ghcr.io/gia-digital/meta-odoo-gateway:<sha-anterior>
```

## 6. Respaldos y restauración

| Qué | Dónde (dentro de `DEPLOY_PATH`) | Retención |
|---|---|---|
| Base, antes de cada deploy | `backups/pre-deploy/*.sql.gz` | 14 días |
| Base, diario (servicio `backup`, 00:00 CDMX y al arrancar el contenedor) | `backups/scheduled/{daily,weekly,monthly}/` | 7 diarios, 4 semanales, 6 mensuales |
| `knowledge_uploads/` (PDFs del catálogo, archivos del knowledge) | `backups/knowledge/*.tar.gz` | 8 semanas |

Restaurar la base (primero respalda el estado actual, detiene `api` y `caddy`, restaura y vuelve a levantar):

```bash
cd ~/meta-odoo-gateway
bash deploy/restore.sh backups/pre-deploy/20261011-133232_abc1234.sql.gz
bash deploy/restore.sh backups/scheduled/daily/gateway-20261011.sql.gz
```

Restaurar `knowledge_uploads`:

```bash
tar -xzf backups/knowledge/20261011.tar.gz -C ~/meta-odoo-gateway
```

**Copia fuera del droplet**: todos estos respaldos viven en el mismo disco. Activa **Backups** del droplet en DigitalOcean (Droplet → Backups, copia diaria o semanal del disco completo) o sincroniza `backups/` a un Space de DigitalOcean con `rclone`/`s3cmd`.

**`POSTGRES_PASSWORD`**: compose solo interpola desde `.deploy.env`, así que `db` y `backup` usan el valor por defecto `gateway` aunque el `.env` defina otro. La base no está expuesta fuera de la red de Docker. Para cambiarla hay que hacer `ALTER USER` dentro de la base, agregar `POSTGRES_PASSWORD` a `write_deploy_env` en `deploy/lib.sh` y actualizar `DATABASE_URL`.

## 7. pgvector (recrear volumen)

El servicio `db` usa `pgvector/pgvector:pg16`. **El volumen anterior de `postgres:16-alpine` no sirve** (falta la extensión). Si no hay datos que conservar:

```bash
cd ~/meta-odoo-gateway
docker compose -f docker-compose.prod.yml --env-file .deploy.env down
docker volume rm meta-odoo-gateway_gateway-pgdata
mkdir -p knowledge_uploads
chmod 777 knowledge_uploads
docker compose -f docker-compose.prod.yml --env-file .deploy.env up -d
```

Usa el nombre literal `meta-odoo-gateway_gateway-pgdata` (no un placeholder). Si `volume rm` dice que está en uso, el `down` no terminó: `docker ps -a` y vuelve a `down`.

Confirma el nombre del volumen con `docker volume ls | grep gateway`. Al primer boot el API hace `CREATE EXTENSION vector`, crea tablas y **seed** de `agent_info` (FAQs, skills, negocio, PDFs).

Dashboard: `https://gia.init.com.mx/dashboard/knowledge`

## 8. HTTPS (Caddy)

Caddy va en `docker-compose.prod.yml` y usa [`Caddyfile`](../Caddyfile):

- Certificado Let's Encrypt automático para `DOMAIN`
- `reverse_proxy` a `api:8000`
- Puertos públicos: **80** y **443**

Si instalaste Caddy/nginx en el host (apt), deténlos para no pelear el puerto:

```bash
sudo systemctl disable --now caddy nginx 2>/dev/null || true
```

Activación inmediata (sin esperar el próximo push), en el droplet:

```bash
cd ~/meta-odoo-gateway
# asegúrate de tener DOMAIN y ACME_EMAIL en .env
# copia Caddyfile + docker-compose.prod.yml actualizados (o re-lanza Deploy en GitHub)

docker compose -f docker-compose.prod.yml --env-file .deploy.env pull caddy
docker compose -f docker-compose.prod.yml --env-file .deploy.env up -d
docker compose -f docker-compose.prod.yml --env-file .deploy.env logs -f caddy
```

## 9. Troubleshooting

### `FileNotFoundError` / `Error while fetching server API version` / `unix_socket`

El CLI `docker` en el droplet es un **shim de Podman** o no hay daemon. Compose v1 (`/usr/bin/docker-compose`) intenta `/var/run/docker.sock` y falla.

**Fix:** instala Docker Engine (sección 1) y verifica `docker info` + `docker compose version` (v2). **No instales `podman-docker`.**

### `Login Succeeded` pero falla el `pull`

El login a GHCR funcionó; el fallo es local (daemon/compose), no del registry.

### API `unhealthy` / Caddy no arranca

1. El seed de knowledge **no debe** bloquear `/health`. Si ves el API unhealthy ~90s, mira logs:

```bash
docker logs meta-odoo-gateway --tail 150
```

- `/health` responde 503 `{"database": "unreachable"}` → la API no llega a Postgres en 3 s (log `health_db_unreachable`). Revisa `docker compose ... ps db` y `logs db`.
- La API se reinicia en bucle con un traceback de Alembic → falló una migración al arrancar. Corrígela en el código (la transacción se revierte completa) o restaura el respaldo pre-deploy.
- `extension "vector" is not available` → el volumen es del Postgres viejo (sin pgvector). Borra `meta-odoo-gateway_gateway-pgdata` (sección 7) y vuelve a `up`.
- `Permission denied` en `knowledge_uploads` → `chmod 777 knowledge_uploads` y reinicia el API.
- El seed tarda (`knowledge_embed_*`) → espera `knowledge_seed_done` y `curl -fsS http://127.0.0.1:8000/health`.

### HTTPS no arranca / challenge ACME falla

- DNS A de `DOMAIN` debe apuntar a la IP del droplet
- Puertos 80 y 443 abiertos (ufw + firewall de DigitalOcean)
- No otro proceso usando 80/443
- Revisa: `docker compose ... logs caddy`
