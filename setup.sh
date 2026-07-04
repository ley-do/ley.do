#!/usr/bin/env bash
set -euo pipefail

python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install mkdocs mkdocs-material

echo "Entorno local de LEY.DO listo."
echo "Ejecutar: source .venv/bin/activate && mkdocs serve"
