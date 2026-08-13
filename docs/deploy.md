# Deploy a DigitalOcean (droplet)

Flujo:

```
push main → pytest → build Docker → push GHCR → SSH → pull + compose up
```

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

Crea también el Environment **production** (Settings → Environments) si quieres approvals manuales; luego descomenta `environment: production` en `deploy.yml`.

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
| [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | push/PR a `main` | `pytest` |
| [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) | push a `main` o manual | test → build/push GHCR → SCP compose → SSH deploy |

Deploy manual: Actions → **Deploy** → **Run workflow**.

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
- Webhook Meta: `https://gia.init.com.mx/webhook/meta`

Imagen publicada: `ghcr.io/gia-digital/meta-odoo-gateway:<short-sha>` y `:latest`.

## 5. Rollback rápido

```bash
cd ~/meta-odoo-gateway
echo 'GATEWAY_IMAGE=ghcr.io/gia-digital/meta-odoo-gateway:<sha-anterior>' > .deploy.env
docker compose -f docker-compose.prod.yml --env-file .deploy.env pull api
docker compose -f docker-compose.prod.yml --env-file .deploy.env up -d
```

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

- `extension "vector" is not available` → el volumen es del Postgres viejo (sin pgvector). Borra `meta-odoo-gateway_gateway-pgdata` (sección 7) y vuelve a `up`.
- `Permission denied` en `knowledge_uploads` → `chmod 777 knowledge_uploads` y reinicia el API.
- El seed tarda (`knowledge_embed_*`) → espera `knowledge_seed_done` y `curl -fsS http://127.0.0.1:8000/health`.

### HTTPS no arranca / challenge ACME falla

- DNS A de `DOMAIN` debe apuntar a la IP del droplet
- Puertos 80 y 443 abiertos (ufw + firewall de DigitalOcean)
- No otro proceso usando 80/443
- Revisa: `docker compose ... logs caddy`
