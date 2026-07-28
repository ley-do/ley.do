"""Evita que el texto legal completo exceda el límite del índice de búsqueda."""

from __future__ import annotations

import re


SECCION_TEXTO = re.compile(
    r'(<h2\b[^>]*\bid="texto"[^>]*>.*?)(?=<h2\b|\Z)',
    flags=re.IGNORECASE | re.DOTALL,
)
ENCABEZADO = re.compile(r'<h[2-6]\b[^>]*>', flags=re.IGNORECASE)


def _excluir_encabezado(match: re.Match[str]) -> str:
    encabezado = match.group(0)
    if "data-search-exclude" in encabezado:
        return encabezado
    return f'{encabezado[:-1]} data-search-exclude="true">'


def _excluir_seccion(match: re.Match[str]) -> str:
    return ENCABEZADO.sub(_excluir_encabezado, match.group(1))


def on_page_content(html: str, **_: object) -> str:
    """Excluye Texto y sus subsecciones, sin cambiar el HTML final."""
    return SECCION_TEXTO.sub(_excluir_seccion, html, count=1)
