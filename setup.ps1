python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install mkdocs mkdocs-material

Write-Host "Entorno local de LEY.DO listo."
Write-Host "Ejecutar: .\.venv\Scripts\Activate.ps1 ; mkdocs serve"
