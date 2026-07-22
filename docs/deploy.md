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

Abre puertos (o pon Caddy/Nginx delante con HTTPS; Meta exige HTTPS en webhooks):

```bash
# mínimo para probar
sudo ufw allow OpenSSH
sudo ufw allow 80
sudo ufw allow 443
# solo si expones la API sin proxy:
# sudo ufw allow 8000
sudo ufw enable
```

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
```

Imagen publicada:

`ghcr.io/gia-digital/meta-odoo-gateway:<short-sha>` y `:latest`.

## 5. Rollback rápido

```bash
cd ~/meta-odoo-gateway
echo 'GATEWAY_IMAGE=ghcr.io/gia-digital/meta-odoo-gateway:<sha-anterior>' > .deploy.env
docker compose -f docker-compose.prod.yml --env-file .deploy.env pull api
docker compose -f docker-compose.prod.yml --env-file .deploy.env up -d
```

## 6. HTTPS (recomendado)

Pon Caddy o Nginx como reverse proxy a `127.0.0.1:8000` y apunta el dominio del webhook Meta a ese HTTPS. No expongas `:8000` a internet si puedes evitarlo.

## 7. Troubleshooting

### `FileNotFoundError` / `Error while fetching server API version` / `unix_socket`

El CLI `docker` en el droplet es un **shim de Podman** o no hay daemon. Compose v1 (`/usr/bin/docker-compose`) intenta `/var/run/docker.sock` y falla.

**Fix:** instala Docker Engine (sección 1) y verifica `docker info` + `docker compose version` (v2).

### `Login Succeeded` pero falla el `pull`

El login a GHCR funcionó; el fallo es local (daemon/compose), no del registry.
