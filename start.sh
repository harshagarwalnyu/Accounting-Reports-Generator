#!/usr/bin/env bash
set -e

free_port() {
  python3 - <<'EOF'
import socket
s = socket.socket()
s.bind(("", 0))
print(s.getsockname()[1])
s.close()
EOF
}

export FRONTEND_PORT=$(free_port)
export BACKEND_PORT=$(free_port)

echo "frontend → http://localhost:${FRONTEND_PORT}"
echo "backend  → http://localhost:${BACKEND_PORT}"

docker compose up --build "$@"
