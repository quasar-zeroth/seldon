#!/usr/bin/env bash
set -Eeuo pipefail

# Launch Seldon API + web GUI for access from other devices on the LAN.
# Usage:
#   ./launch-lan.sh              # foreground, logs visible
#   ./launch-lan.sh -d           # detached/background
#   ./launch-lan.sh --down       # stop services
#   ./launch-lan.sh --rebuild    # rebuild images before launch
#   HOST_IP=192.168.0.x ./launch-lan.sh  # override detected LAN IP

cd "$(dirname "${BASH_SOURCE[0]}")"

DETACH=false
REBUILD=false
DOWN=false

for arg in "$@"; do
  case "$arg" in
    -d|--detach) DETACH=true ;;
    --rebuild) REBUILD=true ;;
    --down|stop) DOWN=true ;;
    -h|--help)
      sed -n '/^# Launch Seldon/,/^$/p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Run: ./launch-lan.sh --help" >&2
      exit 2
      ;;
  esac
done

if ! docker info >/dev/null 2>&1; then
  if getent group docker | grep -Eq "(^|[:,])${USER}([,]|$)" && ! id -nG | grep -qw docker; then
    cat >&2 <<'EOF'
Cannot access Docker yet.

Your user has been added to the docker group, but this shell/login session has not picked up the new group membership.

Run either:
  newgrp docker
  ./launch-lan.sh -d

Or fully log out and back in, then run:
  ./launch-lan.sh -d

Temporary workaround:
  sudo ./launch-lan.sh -d
EOF
  else
    cat >&2 <<'EOF'
Cannot access Docker.

Most likely your user is not in the docker group. Fix once with:
  sudo usermod -aG docker "$USER"

Then log out and back in, or run:
  newgrp docker

Temporary workaround:
  sudo ./launch-lan.sh -d
EOF
  fi
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "Docker Compose is not installed or not on PATH." >&2
  exit 1
fi

if [[ "$DOWN" == true ]]; then
  "${COMPOSE[@]}" down
  exit 0
fi

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    echo "Created .env from .env.example. Add OPENROUTER_API_KEY if live model calls are needed."
  else
    touch .env
    echo "Created empty .env. Add OPENROUTER_API_KEY if live model calls are needed."
  fi
fi

# Pick the LAN-facing IP used for outbound traffic unless HOST_IP was supplied.
HOST_IP="${HOST_IP:-$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')}"
HOST_IP="${HOST_IP:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
HOST_IP="${HOST_IP//[[:space:]]/}"

if [[ -z "$HOST_IP" ]]; then
  echo "Could not detect LAN IP. Re-run with HOST_IP=<your-lan-ip> ./launch-lan.sh" >&2
  exit 1
fi

OVERRIDE_FILE=".docker-compose.lan.override.yml"
cat > "$OVERRIDE_FILE" <<YAML
services:
  web:
    environment:
      # These must be LAN-visible, not localhost, for phones/laptops on the network.
      NEXT_PUBLIC_SELDON_API_URL: http://${HOST_IP}:8000
      NEXT_PUBLIC_SELDON_BROWSER_API_URL: http://${HOST_IP}:8000
YAML

args=(-f docker-compose.yml -f "$OVERRIDE_FILE" up)
if [[ "$REBUILD" == true ]]; then
  args+=(--build)
fi
if [[ "$DETACH" == true ]]; then
  args+=(-d)
fi

echo "Launching Seldon for LAN access..."
echo "  GUI: http://${HOST_IP}:3000"
echo "  API: http://${HOST_IP}:8000"
echo

echo "If it is not reachable from another device, check that the device is on the same Wi‑Fi/LAN and that firewall rules allow ports 3000 and 8000."
if ! grep -Eq '^SELDON_API_KEY=.+' .env && ! grep -Eq '^SELDON_REQUIRE_API_KEY=false$' .env; then
  echo
  echo "Note: API-key enforcement is enabled by default, but .env has no SELDON_API_KEY."
  echo "The GUI may load while API-backed data/actions show Unauthorized."
  echo "For trusted LAN dev, add SELDON_REQUIRE_API_KEY=false to .env, or set SELDON_API_KEY."
fi
echo

"${COMPOSE[@]}" "${args[@]}"

if [[ "$DETACH" == true ]]; then
  echo
  "${COMPOSE[@]}" ps
  echo
  echo "Seldon is running in the background."
  echo "  GUI: http://${HOST_IP}:3000"
  echo "  API: http://${HOST_IP}:8000/health"
  echo "Stop it with: ./launch-lan.sh --down"
fi
