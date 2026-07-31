#!/usr/bin/env python3
"""Regenera portadas anuales de decretos como directorio legible en móvil."""

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

from scripts.procesar_decretos_consultoria import _atomic_write_text, generate_index  # noqa: E402


def _esc(value: str) -> str:
    return html.escape(str(value or "").replace("\r", " ").replace("\n", " ").strip(), quote=False)


def _short(title: str, limit: int = 140) -> str:
    text = " ".join(str(title or "").split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + "…"


def _extract_notes(existing: str) -> list[str]:
    keep = {
        "salvedades documentales",
        "registros con numeración atípica",
        "notas de revisión",
        "notas editoriales",
    }
    notes = []
    for section in re.split(r"(?=^## )", existing, flags=re.M):
        first = section.splitlines()[0].strip().lower() if section.strip() else ""
        title = first[3:].strip() if first.startswith("## ") else ""
        if title in keep:
            notes.append(section.rstrip())
    return notes


def _load_packages(repo: Path, year: int) -> list[dict]:
    root = repo / f"datos/decretos/{year}"
    items = []
    if not root.exists():
        return items
    for path in sorted(root.glob(f"decreto-*-{year}.json")):
        match = re.fullmatch(rf"decreto-(\d+)-{year}\.json", path.name)
        if not match:
            continue
        number = int(match.group(1))
        md = repo / f"docs/decretos/{year}/decreto-{number:03d}-{year}.md"
        if not md.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        data["_number"] = number
        data["_has_pdf"] = (repo / f"archivos/decretos/{year}/decreto-{number:03d}-{year}.pdf").exists()
        items.append(data)
    return items


def _page_from_packages(repo: Path, year: int, notes: list[str]) -> str:
    items = _load_packages(repo, year)
    total = len(items)
    with_pdf = sum(1 for item in items if item.get("_has_pdf") and item.get("estado_extraccion") != "pendiente_encontrar_pdf")
    pending = total - with_pdf
    lines = [
        f"# Decretos {year}",
        "",
        '<div class="leydo-year-hero" markdown>',
        f'<p class="leydo-year-kicker">Decretos · {year}</p>',
        "",
        f"Directorio de los decretos de **{year}** en LEY.DO. Cada fila abre el documento. No se interpreta la ley ni se certifica vigencia.",
        "",
        f'<div class="leydo-year-summary" markdown><span class="leydo-year-chip"><strong>{total}</strong> decretos</span><span class="leydo-year-chip"><strong>{with_pdf}</strong> con PDF</span><span class="leydo-year-chip"><strong>{pending}</strong> sin PDF</span></div>',
        "</div>",
        "",
        '!!! warning "Aviso"',
        "    LEY.DO no es una fuente oficial. Verifique cada documento contra la fuente oficial indicada.",
        "",
    ]
    if notes:
        # Keep salvedades, but after the short header and before the directory.
        lines.extend(notes)
        lines.append("")
    lines.extend([
        "## Decretos",
        "",
        '<div class="leydo-dir" markdown>',
        '<div class="leydo-dir-head" markdown>',
        '<div class="leydo-dir-num">Número</div>',
        '<div class="leydo-dir-date">Fecha</div>',
        '<div class="leydo-dir-title">Título</div>',
        "</div>",
        "",
    ])
    for item in items:
        number = item["_number"]
        stem = f"decreto-{number:03d}-{year}"
        title = _esc(_short(item.get("titulo") or "Sin título"))
        date = _esc(item.get("fecha") or "—")
        lines.extend([
            '<div class="leydo-dir-row" markdown>',
            f'<div class="leydo-dir-num">[{number:03d}-{year}]({stem}.md)</div>',
            f'<div class="leydo-dir-date">{date}</div>',
            f'<div class="leydo-dir-title">{title}</div>',
            "</div>",
            "",
        ])
    if not items:
        lines.append('<div class="leydo-dir-row" markdown><div class="leydo-dir-title">No hay decretos en este año todavía.</div></div>')
        lines.append("")
    lines.append("</div>")
    lines.append("")
    return "\n".join(lines)


def _hub(repo: Path) -> str:
    rows = []
    total = 0
    for year in range(2016, 2027):
        count = len(_load_packages(repo, year))
        total += count
        rows.append((year, count))
    lines = [
        "# Decretos",
        "",
        '<div class="leydo-year-hero" markdown>',
        '<p class="leydo-year-kicker">Corpus de decretos</p>',
        "",
        "Elija un año. Cada año abre un directorio simple: número, fecha y título.",
        "",
        f'<div class="leydo-year-summary" markdown><span class="leydo-year-chip"><strong>{total:,}</strong> decretos en LEY.DO</span></div>'.replace(",", "."),
        "</div>",
        "",
        '!!! warning "Aviso"',
        "    LEY.DO no es una fuente oficial. No certifica exhaustividad, vigencia ni validez legal.",
        "",
        "## Años",
        "",
        '<div class="leydo-dir" markdown>',
        '<div class="leydo-dir-head" markdown>',
        '<div class="leydo-dir-num">Año</div>',
        '<div class="leydo-dir-date">Documentos</div>',
        '<div class="leydo-dir-title">Abrir</div>',
        "</div>",
        "",
    ]
    for year, count in rows:
        lines.extend([
            '<div class="leydo-dir-row" markdown>',
            f'<div class="leydo-dir-num">[{year}]({year}/index.md)</div>',
            f'<div class="leydo-dir-date">{count}</div>',
            f'<div class="leydo-dir-title">Ver decretos de {year}</div>',
            "</div>",
            "",
        ])
    lines.append("</div>")
    lines.append("")
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
            if notes:
                content = index_path.read_text(encoding="utf-8")
                block = "\n\n" + "\n\n".join(notes) + "\n"
                if "## Decretos" in content and block.strip() not in content:
                    content = content.replace("## Decretos", block + "\n## Decretos", 1)
                    _atomic_write_text(index_path, content)
            print(f"OK {year} reconciliado")
        else:
            content = _page_from_packages(repo, year, notes)
            index_path.parent.mkdir(parents=True, exist_ok=True)
            _atomic_write_text(index_path, content)
            print(f"OK {year} paquetes")
    _atomic_write_text(repo / "docs/decretos/index.md", _hub(repo))
    print("OK hub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
