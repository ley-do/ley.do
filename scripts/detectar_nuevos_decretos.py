#!/usr/bin/env python3
"""Detecta decretos 2026 nuevos en la API oficial de Consultoría Jurídica.

Esta herramienta solo detecta e informa diferencias. No descarga PDFs, no modifica
el inventario y no publica contenido.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INVENTARIO_PATH = REPO_ROOT / "fuentes" / "consultoria_decretos_2026_inventario.json"
API_URL = "https://www.consultoria.gov.do/api/consultas/search"
ANIO = 2026


def registros_oficiales(timeout: int = 90) -> list[dict]:
    """Consulta la plataforma oficial vigente, filtrada por decretos del año."""
    payload = {
        "DocumentTypeCode": 3,
        "DocumentNumber": "",
        "FullText": "",
        "Name": "",
        "LastName": "",
        "Identification": "",
        "Charge": "",
        "Institution": 0,
        "President": 0,
        "Consultor": 0,
        "Career": 0,
        "Guild": 0,
        "PensionType": 0,
        "PublicationYear": str(ANIO),
        "sessionId": "leydo-detector",
    }
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://www.consultoria.gov.do",
            "Referer": "https://www.consultoria.gov.do/consultas",
            "User-Agent": "LEY.DO detector/1.0 (+https://ley.do)",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status not in (200, 201):
            raise RuntimeError(f"Respuesta oficial inesperada: HTTP {response.status}")
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, list):
        raise RuntimeError("La API oficial no devolvió una lista de documentos")
    return data


def numero_2026(value: object) -> int | None:
    match = re.fullmatch(r"\s*0*(\d+)\s*-\s*26\s*", str(value or ""))
    return int(match.group(1)) if match else None


def detectar_nuevos() -> list[dict]:
    inventory = json.loads(INVENTARIO_PATH.read_text(encoding="utf-8"))
    known_ids = {
        str(item.get("document_id_consultoria") or "").strip()
        for item in inventory.get("documentos", {}).get("decretos", [])
    }
    if "" in known_ids:
        raise RuntimeError("El inventario local contiene un document_id_consultoria vacío")
    rows = registros_oficiales()
    found = []
    for row in rows:
        document_id = str(row.get("DocId") or "").strip()
        number = numero_2026(row.get("Numero"))
        if not document_id or number is None or document_id in known_ids:
            continue
        found.append({
            "document_id_consultoria": document_id,
            "numero": f"{number}-26",
            "fecha_documento_iso": str(row.get("FechaPromulgacion") or "")[:10],
            "titulo": str(row.get("Titulo") or "").strip(),
            "gaceta_oficial": str(row.get("Gaceta") or "").strip(),
            "url_documento_oficial": f"https://www.consultoria.gov.do/api/document/{document_id}",
        })
    return sorted(found, key=lambda item: int(item["numero"].split("-", 1)[0]))


def main() -> int:
    if not INVENTARIO_PATH.is_file():
        print(f"Error: no existe el inventario {INVENTARIO_PATH}", file=sys.stderr)
        return 1
    try:
        new = detectar_nuevos()
    except (OSError, ValueError, urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as exc:
        print(f"Error al consultar la fuente oficial: {exc}", file=sys.stderr)
        return 1
    if not new:
        print("Sin decretos nuevos en la consulta oficial.")
        return 0
    print(json.dumps({"anio": ANIO, "nuevos_decretos": new}, ensure_ascii=False, indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
