#!/usr/bin/env bash
# Install only the web application on an existing, authorized Ubuntu instance.
set -Eeuo pipefail
umask 077

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail "Execute com sudo no servidor Ubuntu."
[[ $# -eq 2 && "$2" == --host-confirmed ]] || fail "Uso, somente após confirmar um host reservado: sudo bash deploy/ec2/install.sh HOST_PUBLICO --host-confirmed"
PUBLIC_HOST=$1
[[ "$PUBLIC_HOST" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] || fail "Host público inválido; informe apenas o domínio ou IPv4, sem URL ou porta."
[[ ${#PUBLIC_HOST} -le 253 ]] || fail "Host público inválido."
. /etc/os-release
[[ "$ID" == ubuntu && ( "$VERSION_ID" == 22.04 || "$VERSION_ID" == 24.04 ) ]] || fail "Este instalador exige Ubuntu 22.04 ou 24.04."
[[ "$(dpkg --print-architecture)" == amd64 ]] || fail "Este instalador foi preparado para amd64."

readonly BACKEND_DIR=/opt/returntech/backend
readonly FRONTEND_DIR=/var/www/returntech
readonly ENV_FILE=/etc/returntech/backend.env
readonly NGINX_TARGET=/etc/nginx/sites-available/returntech
readonly NGINX_LINK=/etc/nginx/sites-enabled/returntech
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ -d "$BACKEND_DIR" && "$(realpath "$BACKEND_DIR")" == "$BACKEND_DIR" ]] || fail "Entregue o backend em /opt/returntech/backend antes da instalação."
[[ -f "$BACKEND_DIR/run.py" && -f "$BACKEND_DIR/requirements-production.txt" ]] || fail "Backend incompleto."
[[ -d "$FRONTEND_DIR" && "$(realpath "$FRONTEND_DIR")" == "$FRONTEND_DIR" && -f "$FRONTEND_DIR/index.html" ]] || fail "Entregue o build do frontend em /var/www/returntech."
[[ -f "$ENV_FILE" && ! -L "$ENV_FILE" ]] || fail "Crie primeiro /etc/returntech/backend.env, fora do código."
for candidate in "$BACKEND_DIR"/.env "$BACKEND_DIR"/.env.*; do
    [[ ! -e "$candidate" || "$candidate" == "$BACKEND_DIR/.env.example" ]] || fail "O backend não deve conter arquivos .env privados; use /etc/returntech/backend.env."
done

# Inspect configuration without executing it or printing values.
python3 - "$ENV_FILE" "$PUBLIC_HOST" <<'VALIDATE_ENV'
import sys
from pathlib import Path
from urllib.parse import urlsplit

values = {}
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    if not line.strip() or line.lstrip().startswith("#"):
        continue
    key, separator, value = line.partition("=")
    if not separator or not key.strip().isidentifier():
        raise SystemExit("ERROR: Ambiente inválido. Use somente linhas NOME=valor, sem export.")
    values[key.strip()] = value.strip().strip("\"'")
origin = urlsplit(values.get("FRONTEND_URL", ""))
host = (origin.hostname or "").lower()
if (origin.scheme not in {"http", "https"} or host != sys.argv[2].lower()
        or host in {"localhost", "0.0.0.0", "127.0.0.1"} or host.startswith("127.")
        or host.endswith(".localhost") or origin.username or origin.password
        or origin.path not in {"", "/"} or origin.query or origin.fragment):
    raise SystemExit("ERROR: FRONTEND_URL deve conter a origem pública deste host, sem localhost ou caminho.")
if values.get("MAIL_APP_URL", values["FRONTEND_URL"]).rstrip("/") != values["FRONTEND_URL"].rstrip("/"):
    raise SystemExit("ERROR: MAIL_APP_URL deve usar a mesma origem pública de FRONTEND_URL.")
secret = values.get("JWT_SECRET_KEY", "")
if len(secret) < 32 or secret.startswith(("SUBSTITUA", "PREENCHER", "CHAVE_ALEATORIA", "return-tech-development")):
    raise SystemExit("ERROR: Defina JWT_SECRET_KEY aleatória com pelo menos 32 caracteres.")
if not values.get("MONGO_URI", "").startswith(("mongodb://", "mongodb+srv://")):
    raise SystemExit("ERROR: Configure MONGO_URI antes da instalação.")
if values.get("FLASK_DEBUG", "").lower() not in {"0", "false", "off", "no"}:
    raise SystemExit("ERROR: Defina FLASK_DEBUG=0.")
if values.get("BACKGROUND_JOBS_ENABLED", "").lower() not in {"0", "false", "off", "no"}:
    raise SystemExit("ERROR: Defina BACKGROUND_JOBS_ENABLED=false para usar os workers separados.")
VALIDATE_ENV

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends nginx python3-venv python3-pip git curl ca-certificates
if ! id returntech >/dev/null 2>&1; then
    useradd --system --user-group --home-dir /opt/returntech --no-create-home --shell /usr/sbin/nologin returntech
fi
[[ "$(id -u returntech)" != 0 && "$(id -gn returntech)" == returntech ]] || fail "A conta returntech existente não é compatível."
install -d -o root -g root -m 0750 /etc/returntech
chown root:root "$ENV_FILE"
chmod 0600 "$ENV_FILE"
if [[ ! -x "$BACKEND_DIR/.venv/bin/python" ]]; then
    python3 -m venv "$BACKEND_DIR/.venv"
fi
"$BACKEND_DIR/.venv/bin/python" -m pip install --requirement "$BACKEND_DIR/requirements-production.txt"
chown -R -h root:returntech "$BACKEND_DIR"
chmod -R u=rwX,g=rX,o= "$BACKEND_DIR"
chown -R -h root:root "$FRONTEND_DIR"
find "$FRONTEND_DIR" -type d -exec chmod 0755 {} +
find "$FRONTEND_DIR" -type f -exec chmod 0644 {} +

# Replace only this application's named files; keep other sites and defaults.
if [[ -e "$NGINX_TARGET" ]]; then
    [[ ! -L "$NGINX_TARGET" ]] && grep -q '^# Managed by Return Tech deployment\.$' "$NGINX_TARGET" || fail "A configuração returntech existente não pertence a este instalador."
fi
if [[ -e "$NGINX_LINK" || -L "$NGINX_LINK" ]]; then
    [[ -L "$NGINX_LINK" && "$(readlink -f "$NGINX_LINK")" == "$NGINX_TARGET" ]] || fail "Existe outro arquivo usando o nome de site returntech."
fi
nginx_backup=$(mktemp)
had_nginx=false
if [[ -f "$NGINX_TARGET" ]]; then cp -- "$NGINX_TARGET" "$nginx_backup"; had_nginx=true; fi
nginx_template="$SCRIPT_DIR/nginx.conf"
if [[ -s "/etc/letsencrypt/live/$PUBLIC_HOST/fullchain.pem" && -s "/etc/letsencrypt/live/$PUBLIC_HOST/privkey.pem" ]]; then
    nginx_template="$SCRIPT_DIR/nginx-https.conf"
fi
sed "s/__PUBLIC_HOST__/$PUBLIC_HOST/g" "$nginx_template" > "$NGINX_TARGET"
chmod 0644 "$NGINX_TARGET"
created_link=false
if [[ ! -L "$NGINX_LINK" ]]; then ln -s "$NGINX_TARGET" "$NGINX_LINK"; created_link=true; fi
if ! nginx -t; then
    if [[ "$had_nginx" == true ]]; then cp -- "$nginx_backup" "$NGINX_TARGET"; else rm -f -- "$NGINX_TARGET"; fi
    if [[ "$created_link" == true ]]; then rm -f -- "$NGINX_LINK"; fi
    rm -f -- "$nginx_backup"
    fail "NGINX recusou a configuração; o arquivo anterior foi restaurado e nada foi recarregado."
fi
rm -f -- "$nginx_backup"
for unit in returntech-api returntech-mailworker returntech-codeworker; do
    install -o root -g root -m 0644 "$SCRIPT_DIR/$unit.service" "/etc/systemd/system/$unit.service"
done
systemctl daemon-reload
systemctl enable returntech-api returntech-mailworker returntech-codeworker nginx
systemctl restart returntech-api returntech-mailworker returntech-codeworker
systemctl reload nginx
printf 'Instalação aplicada. Verifique os três serviços e GET /api/health antes de divulgar o endereço.\n'
printf 'O Judge0, as regras de rede e a lista de IPs do MongoDB devem ser preparados separadamente.\n'
