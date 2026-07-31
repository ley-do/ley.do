#!/usr/bin/env python3
"""Descarga y normaliza leyes oficiales de Consultoría Jurídica para un año."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
import urllib.request
from pathlib import Path

try:
    from scripts.normalizar_leyes_consultoria import nint, run as normalize_year
    from scripts.procesar_decretos_consultoria import _atomic_write_text, _markdown_url, _validate_official_url
except ModuleNotFoundError:
    from normalizar_leyes_consultoria import nint, run as normalize_year
    from procesar_decretos_consultoria import _atomic_write_text, _markdown_url, _validate_official_url


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, destination: Path, retries: int = 4) -> str:
    _validate_official_url(url)
    destination.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "LEY.DO law normalization",
                    "Referer": "https://www.consultoria.gov.do/consulta/",
                },
            )
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
            if not data.startswith(b"%PDF"):
                raise ValueError(f"Respuesta no PDF ({len(data)} bytes)")
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_bytes(data)
            temporary.replace(destination)
            return sha_file(destination)
        except Exception as exc:  # noqa: BLE001 - se registra y reintenta
            last = exc
            print(f"RETRY {destination.name} attempt={attempt} error={exc}", flush=True)
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"No se pudo descargar {url}: {last}")


def generate_index(repo: Path, year: int, inventory: dict) -> None:
    records = inventory.get("documentos", {}).get("leyes", [])
    packages = {}
    data_root = repo / f"datos/leyes/{year}"
    if data_root.exists():
        for path in data_root.glob(f"ley-*-{year}.json"):
            match = re.fullmatch(rf"ley-(\d+)-{year}\.json", path.name)
            if not match:
                continue
            try:
                packages[int(match.group(1))] = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    package_count = len(packages)
    complete = sum(1 for item in packages.values() if str(item.get("estado_extraccion", "")).startswith("extraido"))
    pending = package_count - complete
    source_count = len(records)
    lines = [
        f"# Leyes {year}",
        "",
        '<div class="leydo-year-hero" markdown>',
        f'<p class="leydo-year-kicker">Leyes · {year}</p>',
        "",
        f"Portada del año **{year}** en LEY.DO. Aquí puede consultar cuántas leyes hay archivadas y abrir cada una. No se interpreta el contenido legal ni se certifica vigencia.",
        "",
        f"Resumen: **{package_count}** leyes con página en LEY.DO, a partir de **{source_count}** registros fuente oficiales.",
        "</div>",
        "",
        '!!! warning "Aviso"',
        "    LEY.DO no es una fuente oficial. Verifique cada documento contra la fuente oficial indicada.",
        "    LEY.DO no ofrece asesoría legal.",
        "",
        '<div class="leydo-year-stats" markdown>',
        f'<div class="leydo-year-stat"><span class="leydo-stat">{package_count}</span><span class="leydo-muted">Leyes en LEY.DO</span></div>',
        f'<div class="leydo-year-stat"><span class="leydo-stat">{complete}</span><span class="leydo-muted">Con texto extraído</span></div>',
        f'<div class="leydo-year-stat"><span class="leydo-stat">{source_count}</span><span class="leydo-muted">Registros fuente</span></div>',
        f'<div class="leydo-year-stat"><span class="leydo-stat">{pending}</span><span class="leydo-muted">Con alerta de extracción</span></div>',
        "</div>",
        "",
        "## Cómo leer esta página",
        "",
        "- En el teléfono: cada ley aparece como una tarjeta apilada, fácil de tocar.",
        "- En escritorio: las tarjetas se organizan en pares para recorrer el año con rapidez.",
        "- Para inteligencia artificial y auditoría: cada ley tiene Markdown + JSON + PDF + SHA256.",
        "- Estado editorial general: **pendiente de revisión humana**.",
        "",
        "## Leyes del año",
        "",
        '<div class="leydo-year-list leydo-year-list--pairs" markdown>',
    ]
    for number in sorted(packages):
        item = packages[number]
        stem = f"ley-{number:03d}-{year}"
        title = html.escape(str(item.get("titulo") or "Sin título"), quote=False)
        date = html.escape(str(item.get("fecha") or ""), quote=False)
        state = "normalizado · pendiente_revision"
        if item.get("estado_extraccion") == "extraido_sin_encabezado_numerico":
            state = "texto extraído sin número en encabezado · pendiente_revision"
        elif item.get("estado_extraccion") != "extraido_desde_pdf_oficial":
            state = f"{item.get('estado_extraccion')} · pendiente_revision"
        elif item.get("alertas_revision"):
            state = "normalizado con alerta · pendiente_revision"
        meta = " · ".join(part for part in [date, state] if part)
        lines.extend([
            f'<div class="leydo-year-entry" markdown>',
            f"**[Ley {number:03d}-{year}]({stem}.md)**",
            "",
            title,
            "",
            f'<p class="leydo-year-meta">{meta}</p>',
            "</div>",
            "",
        ])
    if not packages:
        lines.append("No hay paquetes normalizados todavía para este año.")
        lines.append("")
    lines.extend([
        "</div>",
        "",
        "## Trazabilidad fuente",
        "",
        "Registros oficiales del inventario. Útil para cotejo humano y para agentes que necesiten el ID de Consultoría.",
        "",
        '<div class="leydo-year-trace" markdown>',
    ])
    for record in records:
        number = nint(record.get("numero"))
        related = f"[Ley {number:03d}-{year}](ley-{number:03d}-{year}.md)" if number in packages else ""
        document_id = html.escape(str(record.get("document_id_consultoria") or ""), quote=False)
        official = str(record.get("url_documento_consultoria_abrir") or "").strip()
        source = f"[ID {document_id}]({_markdown_url(official)})" if official else f"ID {document_id}"
        title = html.escape(str(record.get("titulo") or "Sin título en fuente"), quote=False)
        date = html.escape(str(record.get("fecha_documento") or ""), quote=False)
        gaceta = html.escape(str(record.get("gaceta_oficial") or ""), quote=False)
        state = "en LEY.DO · pendiente_revision" if number in packages else "detectado · pendiente_paquete"
        meta = " · ".join(part for part in [date, f"Gaceta {gaceta}" if gaceta else "", source, state] if part)
        number_label = html.escape(str(record.get("numero") or ""), quote=False)
        lines.extend([
            f'<div class="leydo-year-trace-entry" markdown>',
            f"**`{number_label}`**" + (f" · {related}" if related else ""),
            "",
            title,
            "",
            f'<p class="leydo-year-meta">{meta}</p>',
            "</div>",
            "",
        ])
    lines.append("</div>")
    lines.append("")
    destination = repo / f"docs/leyes/{year}/index.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(destination, "\n".join(lines) + "\n")



def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--anio", type=int, required=True)
    parser.add_argument("--numeros", default="")
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    inventory_path = repo / f"fuentes/consultoria_inventario_{args.anio}_leyes_decretos.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    records = inventory.get("documentos", {}).get("leyes", [])
    selected = None
    if args.numeros.strip():
        selected = sorted({int(item.strip()) for item in args.numeros.split(",") if item.strip()})
    for record in records:
        number = nint(record.get("numero"))
        if number is None:
            continue
        if selected is not None and number not in selected:
            continue
        stem = f"ley-{number:03d}-{args.anio}"
        pdf = repo / f"archivos/leyes/{args.anio}/{stem}.pdf"
        url = record.get("url_documento_consultoria_descargar")
        if pdf.exists() and pdf.read_bytes()[:4] == b"%PDF":
            print(f"EXISTE {pdf.name}")
            continue
        print(f"DOWNLOAD {number} {url}")
        download(url, pdf)
    normalize_year(repo, args.anio, selected)
    generate_index(repo, args.anio, inventory)
    print(f"INDEX docs/leyes/{args.anio}/index.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
