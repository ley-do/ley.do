#!/usr/bin/env python3
"""Regenera portadas anuales de decretos con presentación legible en móvil."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.procesar_decretos_consultoria import (  # noqa: E402
    _atomic_write_text,
    _cell,
    generate_index,
)


def _escape(value: str) -> str:
    return html.escape(str(value or "").replace("\r", " ").replace("\n", " ").strip(), quote=False)


def _extract_notes(existing: str) -> list[str]:
    """Conserva secciones editoriales humanas entre la portada y el listado."""
    keep_titles = {
        "salvedades documentales",
        "registros con numeración atípica",
        "notas de revisión",
        "notas editoriales",
    }
    sections = re.split(r"(?=^## )", existing, flags=re.M)
    notes: list[str] = []
    for section in sections:
        first = section.splitlines()[0].strip().lower() if section.strip() else ""
        title = first[3:].strip() if first.startswith("## ") else ""
        if title in keep_titles:
            notes.append(section.rstrip())
    return notes


def _load_packages(repo: Path, year: int) -> list[dict]:
    data_root = repo / f"datos/decretos/{year}"
    items = []
    if not data_root.exists():
        return items
    for path in sorted(data_root.glob(f"decreto-*-{year}.json")):
        match = re.fullmatch(rf"decreto-(\d+)-{year}\.json", path.name)
        if not match:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        number = int(match.group(1))
        md = repo / f"docs/decretos/{year}/decreto-{number:03d}-{year}.md"
        pdf = repo / f"archivos/decretos/{year}/decreto-{number:03d}-{year}.pdf"
        if not md.exists():
            continue
        data["_number"] = number
        data["_has_pdf"] = pdf.exists()
        items.append(data)
    return items


def _state_label(item: dict) -> str:
    if item.get("estado_extraccion") == "pendiente_encontrar_pdf" or not item.get("_has_pdf"):
        return "pendiente de PDF · pendiente_revision"
    if item.get("alertas_revision"):
        return "normalizado con alerta · pendiente_revision"
    if item.get("estado_publicacion") == "normalizado":
        return "normalizado · pendiente_revision"
    return str(item.get("estado_publicacion") or "pendiente_revision")


def _build_from_packages(repo: Path, year: int, notes: list[str]) -> str:
    items = _load_packages(repo, year)
    package_count = len(items)
    pending_pdf = sum(1 for item in items if item.get("estado_extraccion") == "pendiente_encontrar_pdf" or not item.get("_has_pdf"))
    complete = package_count - pending_pdf
    lines = [
        f"# Decretos {year}",
        "",
        '<div class="leydo-year-hero" markdown>',
        f'<p class="leydo-year-kicker">Archivo documental · {year}</p>',
        "",
        f"Esta página reúne los decretos de **{year}** preservados en LEY.DO desde fuentes oficiales dominicanas. Es una portada de navegación: no interpreta la ley ni certifica vigencia.",
        "",
        f"En este año hay **{package_count}** documentos con página en LEY.DO y **{complete}** paquetes con PDF oficial disponible.",
        "</div>",
        "",
        '!!! warning "Aviso"',
        "    LEY.DO no es una fuente oficial. Verifique cada documento contra la fuente oficial indicada.",
        "    LEY.DO no ofrece asesoría legal.",
        "",
        '<div class="leydo-year-stats" markdown>',
        f'<div class="leydo-year-stat"><span class="leydo-stat">{package_count}</span><span class="leydo-muted">Documentos en LEY.DO</span></div>',
        f'<div class="leydo-year-stat"><span class="leydo-stat">{complete}</span><span class="leydo-muted">Con PDF oficial</span></div>',
        f'<div class="leydo-year-stat"><span class="leydo-stat">{pending_pdf}</span><span class="leydo-muted">Pendientes de PDF</span></div>',
        f'<div class="leydo-year-stat"><span class="leydo-stat">{year}</span><span class="leydo-muted">Año documental</span></div>',
        "</div>",
        "",
        "## Lectura rápida",
        "",
        f"- Año documental: **{year}**.",
        f"- Documentos publicados en esta sección: **{package_count}**.",
        f"- Paquetes con PDF oficial: **{complete}**.",
        "- Estado editorial general: **pendiente de revisión humana**.",
        "",
        "Fuente principal de consulta: [Consultoría Jurídica del Poder Ejecutivo](https://www.consultoria.gov.do/consulta/).",
        "",
    ]
    if notes:
        lines.extend(notes)
        lines.append("")
    lines.extend([
        "## Documentos del año",
        "",
        "Listado principal para consulta en móvil y escritorio.",
        "",
        '<div class="leydo-year-list" markdown>',
    ])
    for item in items:
        number = item["_number"]
        stem = f"decreto-{number:03d}-{year}"
        title = _escape(item.get("titulo") or "Sin título en metadata")
        date = _escape(item.get("fecha") or "")
        state = _state_label(item)
        tipo = "Reglamento" if item.get("tipo_documento") == "reglamento" else "Decreto"
        meta = " · ".join(part for part in [date, state] if part)
        lines.extend([
            f'<div class="leydo-year-entry" markdown>',
            f"**[{tipo} {number:03d}-{year}]({stem}.md)**",
            "",
            title,
            "",
            f'<p class="leydo-year-meta">{meta}</p>',
            "</div>",
            "",
        ])
    if not items:
        lines.append("No hay documentos normalizados todavía para este año.")
        lines.append("")
    lines.append("</div>")
    lines.append("")
    return "\n".join(lines)


def _build_hub(repo: Path) -> str:
    rows = []
    total_docs = 0
    for year in range(2016, 2027):
        items = _load_packages(repo, year)
        count = len(items)
        total_docs += count
        pending = sum(1 for item in items if item.get("estado_extraccion") == "pendiente_encontrar_pdf" or not item.get("_has_pdf"))
        label = f"{count} documentos"
        if pending:
            label += f" · {pending} pendientes de PDF"
        rows.append((year, label))
    lines = [
        "# Decretos",
        "",
        '<div class="leydo-year-hero" markdown>',
        '<p class="leydo-year-kicker">Corpus documental</p>',
        "",
        "Sección de decretos del archivo público LEY.DO. Elija un año para ver una portada legible en móvil, con cifras del periodo y el listado de documentos.",
        "",
        f"Cobertura actual en LEY.DO: **{total_docs:,}** páginas documentales entre 2016 y 2026.".replace(",", "."),
        "</div>",
        "",
        '!!! warning "Aviso"',
        "    LEY.DO no es una fuente oficial. Esta sección organiza documentos detectados o normalizados desde fuentes oficiales. No certifica exhaustividad, vigencia ni validez legal.",
        "",
        "## Años disponibles",
        "",
        '<div class="leydo-year-catalog" markdown>',
    ]
    for year, label in rows:
        lines.extend([
            f'<div class="leydo-year-catalog-entry" markdown>',
            f"**[{year}]({year}/index.md)**",
            "",
            f'<p class="leydo-year-meta">{label}</p>',
            "</div>",
            "",
        ])
    lines.extend([
        "</div>",
        "",
        "## Nota editorial",
        "",
        "Cada año abre con un resumen de cobertura y un listado apilado pensado para teléfono. El detalle de trazabilidad por registro fuente, cuando existe, aparece debajo del listado principal.",
        "",
    ])
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--inicio", type=int, default=2016)
    parser.add_argument("--fin", type=int, default=2026)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    for year in range(args.inicio, args.fin + 1):
        index_path = repo / f"docs/decretos/{year}/index.md"
        existing = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
        notes = _extract_notes(existing)
        recon = repo / f"fuentes/consultoria_decretos_{year}_reconciliado.json"
        if recon.exists():
            generate_index(repo, recon, year)
            # reinsert preserved human notes after lectura rapida if present
            if notes:
                content = index_path.read_text(encoding="utf-8")
                insertion = "\n\n" + "\n\n".join(notes) + "\n"
                if "## Documentos del año" in content and insertion.strip() not in content:
                    content = content.replace("## Documentos del año", insertion + "\n## Documentos del año", 1)
                    _atomic_write_text(index_path, content)
            print(f"OK {year} reconciliado")
        else:
            content = _build_from_packages(repo, year, notes)
            index_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(index_path, content)
            print(f"OK {year} paquetes")
    hub = repo / "docs/decretos/index.md"
    _atomic_write_text(hub, _build_hub(repo))
    print("OK hub decretos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
