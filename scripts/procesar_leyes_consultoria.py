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

    def _short(title, limit=140):
        text = " ".join(str(title or "").split())
        if len(text) <= limit:
            return text
        cut = text[: limit - 1]
        if " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        return cut + "…"

    package_count = len(packages)
    source_count = len(records)
    lines = [
        f"# Leyes {year}",
        "",
        '<div class="leydo-year-hero" markdown>',
        f'<p class="leydo-year-kicker">Leyes · {year}</p>',
        "",
        f"Directorio de las leyes de **{year}** en LEY.DO. Cada fila abre el documento. No se interpreta la ley ni se certifica vigencia.",
        "",
        f'<div class="leydo-year-summary" markdown><span class="leydo-year-chip"><strong>{package_count}</strong> leyes</span><span class="leydo-year-chip"><strong>{source_count}</strong> registros fuente</span></div>',
        "</div>",
        "",
        '!!! warning "Aviso"',
        "    LEY.DO no es una fuente oficial. Verifique cada documento contra la fuente oficial indicada.",
        "",
        "## Leyes",
        "",
        '<div class="leydo-dir" markdown>',
        '<div class="leydo-dir-head" markdown>',
        '<div class="leydo-dir-num">Número</div>',
        '<div class="leydo-dir-date">Fecha</div>',
        '<div class="leydo-dir-title">Título</div>',
        "</div>",
        "",
    ]
    for number in sorted(packages):
        item = packages[number]
        stem = f"ley-{number:03d}-{year}"
        title = html.escape(_short(item.get("titulo") or "Sin título"), quote=False)
        date = html.escape(str(item.get("fecha") or "—"), quote=False)
        lines.extend([
            '<div class="leydo-dir-row" markdown>',
            f'<div class="leydo-dir-num">[{number:03d}-{year}]({stem}.md)</div>',
            f'<div class="leydo-dir-date">{date}</div>',
            f'<div class="leydo-dir-title">{title}</div>',
            "</div>",
            "",
        ])
    if not packages:
        lines.append('<div class="leydo-dir-row" markdown><div class="leydo-dir-title">No hay leyes normalizadas todavía.</div></div>')
        lines.append("")
    lines.append("</div>")
    lines.append("")
    lines.extend([
        f'<details class="leydo-details"><summary>Trazabilidad fuente ({source_count} registros)</summary>',
        "",
        '<div class="leydo-dir" markdown>',
    ])
    for record in records:
        number = nint(record.get("numero"))
        related = f"[Ley {number:03d}-{year}](ley-{number:03d}-{year}.md)" if number in packages else ""
        document_id = html.escape(str(record.get("document_id_consultoria") or ""), quote=False)
        official = str(record.get("url_documento_consultoria_abrir") or "").strip()
        source = f"[ID {document_id}]({_markdown_url(official)})" if official else f"ID {document_id}"
        title = html.escape(_short(record.get("titulo") or "Sin título en fuente", 120), quote=False)
        date = html.escape(str(record.get("fecha_documento") or "—"), quote=False)
        number_label = html.escape(str(record.get("numero") or ""), quote=False)
        state = "en LEY.DO" if number in packages else "detectado"
        lines.extend([
            '<div class="leydo-dir-row" markdown>',
            f'<div class="leydo-dir-num">`{number_label}`' + (f' · {related}' if related else '') + '</div>',
            f'<div class="leydo-dir-date">{date}</div>',
            f'<div class="leydo-dir-title">{title} · {source} · {state}</div>',
            "</div>",
            "",
        ])
    lines.append("</div>")
    lines.append("")
    lines.append("</details>")
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
