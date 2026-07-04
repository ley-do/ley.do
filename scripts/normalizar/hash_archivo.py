#!/usr/bin/env python3
from pathlib import Path
import hashlib
import sys

def sha256_archivo(ruta: Path) -> str:
    hash_obj = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            hash_obj.update(bloque)
    return hash_obj.hexdigest()

def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: python scripts/normalizar/hash_archivo.py <archivo>")
        return 1

    ruta = Path(sys.argv[1])
    if not ruta.exists():
        print(f"Archivo no encontrado: {ruta}")
        return 1

    print(sha256_archivo(ruta))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
