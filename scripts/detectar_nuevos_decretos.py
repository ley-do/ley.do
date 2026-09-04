#!/usr/bin/env python3
"""
Script automático para detectar y procesar nuevos decretos desde la Consultoría Jurídica.
Detecta nuevos documentos probando IDs secuenciales superiores al último conocido.
"""

import json
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
import subprocess

# Configuración
REPO_ROOT = Path(__file__).parent.parent
INVENTARIO_PATH = REPO_ROOT / "fuentes" / "consultoria_decretos_2026_inventario.json"
RECONCILIADO_PATH = REPO_ROOT / "fuentes" / "consultoria_decretos_2026_reconciliado.json"
MANIFIESTO_PATH = REPO_ROOT / "fuentes" / "decretos_2026_actualizacion_manifest.json"
ANIO = 2026

def get_last_document_id():
    """Obtiene el último document_id conocido del inventario."""
    with open(INVENTARIO_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    decretos = data['documentos']['decretos']
    last_id = max(int(d['document_id_consultoria']) for d in decretos)
    return last_id

def check_document_exists(document_id, timeout=10):
    """
    Verifica si existe un documento con el ID dado.
    Retorna (existe, metadata) donde metadata es un dict con info del decreto si existe.
    """
    url = f"https://www.consultoria.gov.do/Consulta/Home/FileManagement?documentId={document_id}&managementType=1"
    
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'LEY.DO-Bot/1.0 (https://ley.do)',
            'Accept': 'application/json, text/html'
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            content_type = response.headers.get('Content-Type', '')
            
            # Si es JSON, intentar parsear
            if 'application/json' in content_type:
                data = json.loads(response.read().decode('utf-8'))
                return True, data
            
            # Si es HTML, verificar que no sea error 404
            html = response.read().decode('utf-8', errors='ignore')
            if '404' in html or 'not found' in html.lower():
                return False, None
            
            # Si hay contenido, probablemente existe
            return True, None
            
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, None
        # Otros errores HTTP pueden indicar que el documento existe pero hay problemas de acceso
        return None, None
    except Exception as e:
        print(f"Error checking document {document_id}: {e}", file=sys.stderr)
        return None, None

def detect_new_decretos(max_gap=100):
    """
    Detecta nuevos decretos probando IDs secuenciales.
    max_gap: número máximo de IDs consecutivos sin encontrar antes de detenerse.
    """
    last_known_id = get_last_document_id()
    print(f"Último document_id conocido: {last_known_id}")
    
    new_decretos = []
    current_id = last_known_id + 1
    gap_count = 0
    
    print(f"Buscando nuevos decretos desde ID {current_id}...")
    print(f"Gap máximo: {max_gap} IDs consecutivos sin encontrar")
    
    while gap_count < max_gap:
        existe, metadata = check_document_exists(current_id)
        
        if existe is True:
            print(f"✓ Encontrado nuevo decreto: document_id={current_id}")
            new_decretos.append({
                'document_id': current_id,
                'metadata': metadata
            })
            gap_count = 0  # Resetear contador
        elif existe is False:
            gap_count += 1
            if gap_count % 10 == 0:
                print(f"  ... probando ID {current_id} (gap: {gap_count})")
        else:
            # Error, continuar pero no contar como gap
            pass
        
        current_id += 1
    
    print(f"\nDetección completada. Nuevos decretos encontrados: {len(new_decretos)}")
    return new_decretos

def main():
    """
    Función principal del script de actualización automática.
    """
    print("=" * 60)
    print(f"LEY.DO - Detección automática de nuevos decretos")
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
    
    # Verificar que existe el inventario
    if not INVENTARIO_PATH.exists():
        print(f"Error: No se encuentra el inventario en {INVENTARIO_PATH}")
        return 1
    
    # Detectar nuevos decretos
    new_decretos = detect_new_decretos(max_gap=100)
    
    if not new_decretos:
        print("\nNo hay nuevos decretos desde la última actualización.")
        return 0
    
    # Mostrar resumen
    print(f"\nNuevos decretos detectados:")
    for d in new_decretos:
        print(f"  - document_id: {d['document_id']}")
    
    print("\nPara procesar estos decretos, ejecuta:")
    numeros = ','.join(str(d['document_id']) for d in new_decretos)
    print(f"  python scripts/procesar_decretos_consultoria.py --repo . --inventario fuentes/consultoria_decretos_2026_inventario.json --anio 2026 --numeros {numeros} --manifiesto fuentes/decretos_2026_actualizacion_manifest.json")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
