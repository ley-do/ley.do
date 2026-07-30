import hashlib
import http.client
import os
import io
import json
import tempfile
import subprocess
import sys
import unittest
from unittest import mock
from pathlib import Path

import pymupdf

from scripts.procesar_decretos_consultoria import _safe_repo_path, _validated_packages, download_pdf, generate_index, main, parse_numbers, process_documents


def pdf_bytes(text="contenido"):
    document=pymupdf.open(); page=document.new_page(); page.insert_text((72,72),text); data=document.tobytes(); document.close(); return data


class ProcesarDecretosTests(unittest.TestCase):
    def test_expande_rangos_y_elimina_repetidos(self):
        self.assertEqual(parse_numbers("1-3,2,5"), [1, 2, 3, 5])

    def test_rechaza_url_que_no_sea_https_de_consultoria(self):
        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "documento.pdf"
            with self.assertRaisesRegex(ValueError, "URL oficial no permitida"):
                download_pdf(
                    "http://127.0.0.1/documento.pdf",
                    destination,
                    opener=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no debe abrir")),
                )
            self.assertFalse(destination.exists())

    def test_descarga_pdf_validado_de_forma_atomica(self):
        data = pdf_bytes()

        class Response(io.BytesIO):
            def __init__(self):
                super().__init__(data)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "documento.pdf"
            digest = download_pdf("https://www.consultoria.gov.do/documento.pdf", destination, opener=lambda *args, **kwargs: Response())

            self.assertEqual(destination.read_bytes(), data)
            self.assertEqual(digest, hashlib.sha256(data).hexdigest())
            self.assertFalse(destination.with_suffix(".pdf.tmp").exists())

    def test_reintenta_descarga_transitoria_hasta_tres_veces(self):
        data = pdf_bytes()
        attempts = []

        class Response(io.BytesIO):
            def __init__(self):
                super().__init__(data)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def opener(*args, **kwargs):
            attempts.append(1)
            if len(attempts) < 3:
                raise OSError("fallo transitorio")
            return Response()

        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "documento.pdf"
            download_pdf(
                "https://www.consultoria.gov.do/documento.pdf",
                destination,
                opener=opener,
                retries=3,
                sleeper=lambda _: None,
            )

        self.assertEqual(len(attempts), 3)

    def test_reintenta_una_respuesta_invalida_antes_de_publicar(self):
        valid = pdf_bytes("válido")
        responses = [b"<html>error</html>", valid]
        attempts = []

        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def geturl(self): return "https://www.consultoria.gov.do/documento.pdf"

        def opener(*args, **kwargs):
            attempts.append(1)
            return Response(responses.pop(0))

        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "documento.pdf"
            digest = download_pdf(
                "https://www.consultoria.gov.do/documento.pdf",
                destination,
                opener=opener,
                sleeper=lambda _: None,
            )
            self.assertEqual(digest, hashlib.sha256(valid).hexdigest())
            self.assertEqual(destination.read_bytes(), valid)

        self.assertEqual(len(attempts), 2)

    def test_no_reemplaza_destino_si_el_hash_esperado_no_coincide(self):
        original = pdf_bytes("original")
        received = pdf_bytes("recibido")

        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def geturl(self): return "https://www.consultoria.gov.do/documento.pdf"

        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "documento.pdf"
            destination.write_bytes(original)
            with self.assertRaisesRegex(ValueError, "Hash SHA256 inesperado"):
                download_pdf(
                    "https://www.consultoria.gov.do/documento.pdf",
                    destination,
                    opener=lambda *args, **kwargs: Response(received),
                    sleeper=lambda _: None,
                    retries=1,
                    expected_hash="0" * 64,
                )
            self.assertEqual(destination.read_bytes(), original)

    def test_rechaza_descarga_mayor_al_limite(self):
        valid = pdf_bytes("demasiado grande")

        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def geturl(self): return "https://www.consultoria.gov.do/documento.pdf"

        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "documento.pdf"
            with self.assertRaisesRegex(ValueError, "excede el límite"):
                download_pdf(
                    "https://www.consultoria.gov.do/documento.pdf",
                    destination,
                    opener=lambda *args, **kwargs: Response(valid),
                    sleeper=lambda _: None,
                    retries=1,
                    max_bytes=32,
                )
            self.assertFalse(destination.exists())

    def test_procesa_pdf_canonico_y_rendicion_relacionada(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            inventory = repo / "reconciliado.json"
            inventory.write_text(
                json.dumps(
                    {
                        "documentos": {
                            "decretos": [
                                {
                                    "numero": "275-19",
                                    "document_id_consultoria": "canonico",
                                    "url_documento_consultoria_descargar": "https://www.consultoria.gov.do/canonico.pdf",
                                    "rendiciones_oficiales_relacionadas": [
                                        {
                                            "document_id_consultoria": "extra",
                                            "ruta_pdf_local": "archivos/decretos/2019/decreto-275-2019-extra.pdf",
                                            "url_pdf_oficial": "https://www.consultoria.gov.do/extra.pdf",
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            downloads = []
            normalizations = []

            def fake_download(url, destination):
                destination = Path(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"%PDF-1.4\nprueba")
                downloads.append((url, destination.relative_to(repo).as_posix()))
                return hashlib.sha256(destination.read_bytes()).hexdigest()

            def fake_normalizer(repo_arg, year, numbers, **kwargs):
                normalizations.append((Path(repo_arg), year, numbers, kwargs))

            result = process_documents(
                repo,
                inventory,
                2019,
                [275],
                downloader=fake_download,
                normalizer=fake_normalizer,
            )

            self.assertEqual(result["ok"], [275])
            self.assertEqual(result["errors"], [])
            self.assertEqual(len(downloads), 2)
            self.assertEqual(normalizations[0][1:3], (2019, [275]))
            self.assertEqual(normalizations[0][3]["inventario_path"], inventory)

    def test_redescarga_rendicion_existente_si_el_hash_no_coincide(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            inventory = repo / "reconciliado.json"
            correct = pdf_bytes("rendición correcta")
            expected = hashlib.sha256(correct).hexdigest()
            inventory.write_text(
                json.dumps(
                    {
                        "documentos": {
                            "decretos": [
                                {
                                    "numero": "275-19",
                                    "anio": "2019",
                                    "document_id_consultoria": "canonico",
                                    "url_documento_consultoria_descargar": "https://www.consultoria.gov.do/canonico.pdf",
                                    "rendiciones_oficiales_relacionadas": [
                                        {
                                            "ruta_pdf_local": "archivos/decretos/2019/decreto-275-2019-extra.pdf",
                                            "url_pdf_oficial": "https://www.consultoria.gov.do/extra.pdf",
                                            "sha256_pdf": expected,
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            canonical = repo / "archivos/decretos/2019/decreto-275-2019.pdf"
            rendition = repo / "archivos/decretos/2019/decreto-275-2019-extra.pdf"
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(pdf_bytes("canónico"))
            rendition.write_bytes(pdf_bytes("incorrecta"))
            downloads = []

            def fake_download(url, destination, **kwargs):
                downloads.append(kwargs.get("expected_hash"))
                Path(destination).write_bytes(correct)
                return expected

            result = process_documents(
                repo,
                inventory,
                2019,
                [275],
                downloader=fake_download,
                normalizer=lambda *args, **kwargs: None,
            )

            self.assertEqual(result["errors"], [])
            self.assertEqual(downloads, [expected])
            self.assertEqual(rendition.read_bytes(), correct)

    def test_rechaza_ruta_de_rendicion_fuera_del_repositorio(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            inventory = repo / "reconciliado.json"
            inventory.write_text(
                json.dumps(
                    {
                        "documentos": {
                            "decretos": [
                                {
                                    "numero": "275-19",
                                    "anio": "2019",
                                    "document_id_consultoria": "canonico",
                                    "url_documento_consultoria_descargar": "https://www.consultoria.gov.do/canonico.pdf",
                                    "rendiciones_oficiales_relacionadas": [
                                        {
                                            "ruta_pdf_local": "../escape.pdf",
                                            "url_pdf_oficial": "https://www.consultoria.gov.do/extra.pdf",
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            canonical = repo / "archivos/decretos/2019/decreto-275-2019.pdf"
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(b"%PDF-1.4\nexistente")

            result = process_documents(
                repo,
                inventory,
                2019,
                [275],
                downloader=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no debe descargar")),
                normalizer=lambda *args, **kwargs: None,
            )

            self.assertEqual(result["ok"], [])
            self.assertIn("Ruta fuera del repositorio", result["errors"][0]["error"])
            self.assertFalse((repo.parent / "escape.pdf").exists())

    def test_acepta_sufijo_documental_2019_aunque_metadata_fuente_diga_2020(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            inventory = repo / "reconciliado.json"
            inventory.write_text(
                json.dumps(
                    {
                        "documentos": {
                            "decretos": [
                                {
                                    "numero": "478-19",
                                    "anio": "2020",
                                    "anio_metadata_fuente": "2020",
                                    "document_id_consultoria": "id-478",
                                    "url_documento_consultoria_descargar": "https://www.consultoria.gov.do/478.pdf",
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            canonical = repo / "archivos/decretos/2019/decreto-478-2019.pdf"
            canonical.parent.mkdir(parents=True); canonical.write_bytes(pdf_bytes("decreto 478-19"))

            result = process_documents(repo, inventory, 2019, [478], normalizer=lambda *args, **kwargs: None)

            self.assertEqual(result, {"ok": [478], "errors": []})

    def test_no_procesa_un_registro_del_mismo_numero_pero_otro_anio(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            inventory = repo / "reconciliado.json"
            inventory.write_text(
                json.dumps(
                    {
                        "documentos": {
                            "decretos": [
                                {
                                    "numero": "275-20",
                                    "anio": "2020",
                                    "document_id_consultoria": "id-2020",
                                    "url_documento_consultoria_descargar": "https://www.consultoria.gov.do/275.pdf",
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            result = process_documents(
                repo,
                inventory,
                2019,
                [275],
                downloader=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no debe descargar")),
                normalizer=lambda *args, **kwargs: None,
            )

            self.assertEqual(result["ok"], [])
            self.assertIn("encontrados: 0", result["errors"][0]["error"])

    def test_cli_escribe_manifiesto_reanudable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inventory = root / "inventario.json"
            inventory.write_text("{}", encoding="utf-8")
            manifest = root / "manifest.json"
            calls = []

            def processor(repo, inventory_path, year, numbers):
                calls.append((Path(repo), Path(inventory_path), year, numbers))
                return {"ok": list(numbers), "errors": []}

            exit_code = main(
                [
                    "--repo", str(root),
                    "--inventario", str(inventory),
                    "--anio", "2019",
                    "--numeros", "1-2",
                    "--manifiesto", str(manifest),
                ],
                processor=processor,
            )

            saved = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual([(call[2], call[3]) for call in calls], [(2019, [1]), (2019, [2])])
            self.assertEqual(saved["resultado"], {"ok": [1, 2], "errors": []})
            self.assertEqual(saved["estado"], "completado")
            self.assertEqual(saved["inventario"], "inventario.json")
            self.assertTrue((root / "docs/decretos/2019/index.md").is_file())

    def test_cli_reanuda_desde_un_manifiesto_compatible(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inventory = root / "inventario.json"
            inventory.write_text("{}", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "1.1",
                        "anio": 2019,
                        "inventario": "inventario.json",
                        "sha256_inventario": hashlib.sha256(inventory.read_bytes()).hexdigest(),
                        "numeros": [1, 2],
                        "resultado": {"ok": [1], "errors": []},
                    }
                ),
                encoding="utf-8",
            )
            calls = []

            def processor(repo, inventory_path, year, numbers):
                calls.append(numbers)
                return {"ok": list(numbers), "errors": []}

            exit_code = main(
                [
                    "--repo", str(root),
                    "--inventario", str(inventory),
                    "--anio", "2019",
                    "--numeros", "1-2",
                    "--manifiesto", str(manifest),
                ],
                processor=processor,
            )

            saved = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(calls, [[2]])
            self.assertEqual(saved["resultado"]["ok"], [1, 2])

    def test_cli_reprocesa_un_ok_del_manifiesto_si_el_paquete_falta(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inventory = root / "inventario.json"
            record = {
                "numero": "1-19",
                "anio": "2019",
                "document_id_consultoria": "id-1",
                "identidad_documental_numero": 1,
                "institucion_fuente": "Consultoria Juridica",
                "url_fuente_oficial": "https://www.consultoria.gov.do/",
                "url_documento_consultoria_descargar": "https://www.consultoria.gov.do/1.pdf",
                "url_documento_consultoria_abrir": "https://www.consultoria.gov.do/1",
            }
            inventory.write_text(
                json.dumps({"documentos": {"decretos": [record]}, "registros_fuente": [record]}),
                encoding="utf-8",
            )
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": "1.1",
                        "anio": 2019,
                        "inventario": "inventario.json",
                        "sha256_inventario": hashlib.sha256(inventory.read_bytes()).hexdigest(),
                        "numeros": [1],
                        "resultado": {"ok": [1], "errors": []},
                    }
                ),
                encoding="utf-8",
            )
            calls = []

            def processor(repo, inventory_path, year, numbers):
                calls.append(list(numbers))
                pdf = root / "archivos/decretos/2019/decreto-001-2019.pdf"
                markdown = root / "docs/decretos/2019/decreto-001-2019.md"
                package = root / "datos/decretos/2019/decreto-001-2019.json"
                pdf.parent.mkdir(parents=True, exist_ok=True); markdown.parent.mkdir(parents=True, exist_ok=True); package.parent.mkdir(parents=True, exist_ok=True)
                pdf.write_bytes(pdf_bytes("decreto 1")); markdown.write_text("# Decreto 1\n\nLEY.DO no es una fuente oficial.\nLEY.DO no ofrece asesoría legal.\n\n## Metadata\n\n## Texto\n\n## Notas de revisión\n", encoding="utf-8")
                package.write_text(
                    json.dumps(
                        {
                            "document_id_consultoria": "id-1",
                            "numero": "001",
                            "anio": "2019",
                            "ruta_pdf_local": "archivos/decretos/2019/decreto-001-2019.pdf",
                            "ruta_markdown": "docs/decretos/2019/decreto-001-2019.md",
                            "ruta_json": "datos/decretos/2019/decreto-001-2019.json",
                            "institucion_fuente": "Consultoria Juridica",
                            "url_fuente_oficial": "https://www.consultoria.gov.do/",
                            "url_pdf_original": "https://www.consultoria.gov.do/1.pdf",
                            "url_documento_oficial": "https://www.consultoria.gov.do/1",
                            "sha256_pdf_original": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                            "sha256_markdown": hashlib.sha256(markdown.read_bytes()).hexdigest(),
                            "estado_revision": "pendiente_revision",
                            "estado_publicacion": "normalizado",
                            "estado_extraccion": "extraido_desde_pdf_oficial",
                        }
                    ),
                    encoding="utf-8",
                )
                return {"ok": list(numbers), "errors": []}

            exit_code = main(
                ["--repo", str(root), "--inventario", str(inventory), "--anio", "2019", "--numeros", "1", "--manifiesto", str(manifest)],
                processor=processor,
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(calls, [[1]])

    def test_indice_rechaza_ids_canonicos_duplicados_aun_sin_reprocesar(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            inventory = repo / "reconciliado.json"
            records = [
                {"numero": "1-19", "anio": "2019", "identidad_documental_numero": 1, "document_id_consultoria": "duplicado"},
                {"numero": "2-19", "anio": "2019", "identidad_documental_numero": 2, "document_id_consultoria": "duplicado"},
            ]
            inventory.write_text(json.dumps({"documentos": {"decretos": records}, "registros_fuente": records}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "ID de registro fuente duplicado"):
                generate_index(repo, inventory, 2019)

    def test_indice_falla_si_falta_una_rendicion_oficial_declarada(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            inventory = repo / "reconciliado.json"
            record = {
                "numero": "1-19",
                "anio": "2019",
                "identidad_documental_numero": 1,
                "document_id_consultoria": "canonico",
                "rendiciones_oficiales_relacionadas": [
                    {
                        "document_id_consultoria": "extra",
                        "ruta_pdf_local": "archivos/decretos/2019/decreto-001-2019-fuente-extra.pdf",
                        "url_pdf_oficial": "https://www.consultoria.gov.do/extra.pdf",
                        "sha256_pdf": "0" * 64,
                    }
                ],
            }
            inventory.write_text(json.dumps({"documentos": {"decretos": [record]}, "registros_fuente": [record]}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Rendiciones oficiales"):
                generate_index(repo, inventory, 2019)

    def test_indice_falla_si_hay_un_paquete_canonico_huerfano(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            inventory = repo / "reconciliado.json"
            inventory.write_text(json.dumps({"documentos": {"decretos": []}, "registros_fuente": []}), encoding="utf-8")
            orphan = repo / "datos/decretos/2019/decreto-999-2019.json"
            orphan.parent.mkdir(parents=True); orphan.write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "huérfanos"):
                generate_index(repo, inventory, 2019)

    def test_indice_codifica_caracteres_de_control_markdown_en_url_oficial(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            inventory = repo / "reconciliado.json"
            malicious_url = "https://www.consultoria.gov.do/doc) [x](javascript:alert(1))"
            record = {
                "numero": "1-19",
                "anio": "2019",
                "titulo": "<script>alerta</script>",
                "document_id_consultoria": "id](malicioso)",
                "url_documento_consultoria_abrir": malicious_url,
                "identidad_documental_numero": 1,
                "rol_reconciliacion": "canonico",
            }
            inventory.write_text(
                json.dumps({"registros_fuente": [record], "documentos": {"decretos": [record]}}),
                encoding="utf-8",
            )

            content = generate_index(repo, inventory, 2019).read_text(encoding="utf-8")

            self.assertNotIn("<script>", content)
            self.assertNotIn("javascript:alert", content)
            self.assertIn("%29", content)
            self.assertIn("&#93;", content)

    def test_indice_no_enlaza_un_paquete_de_otro_id(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            inventory = repo / "reconciliado.json"
            record = {
                "numero": "275-19",
                "anio": "2019",
                "titulo": "Documento canónico",
                "document_id_consultoria": "canonico",
                "url_documento_consultoria_abrir": "https://www.consultoria.gov.do/canonico",
                "identidad_documental_numero": 275,
                "rol_reconciliacion": "canonico",
            }
            inventory.write_text(
                json.dumps(
                    {
                        "resumen": {"registros_fuente": 1, "identidades_documentales": 1},
                        "registros_fuente": [record],
                        "documentos": {"decretos": [record]},
                    }
                ),
                encoding="utf-8",
            )
            package = repo / "datos/decretos/2019/decreto-275-2019.json"
            package.parent.mkdir(parents=True)
            package.write_text(
                json.dumps(
                    {
                        "document_id_consultoria": "otro-id",
                        "numero": "275",
                        "anio": "2019",
                        "estado_revision": "pendiente_revision",
                    }
                ),
                encoding="utf-8",
            )

            content = generate_index(repo, inventory, 2019).read_text(encoding="utf-8")

            self.assertNotIn("[Decreto 275-2019](decreto-275-2019.md)", content)
            self.assertIn("descubierto · pendiente_revision", content)

    def test_indice_preserva_cada_registro_fuente_y_relacion(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            inventory = repo / "reconciliado.json"
            records = [
                {
                    "numero": "275-19",
                    "titulo": "Documento canónico",
                    "document_id_consultoria": "canonico",
                    "institucion_fuente": "Consultoria Juridica",
                    "url_fuente_oficial": "https://www.consultoria.gov.do/",
                    "url_documento_consultoria_descargar": "https://www.consultoria.gov.do/canonico.pdf",
                    "url_documento_consultoria_abrir": "https://www.consultoria.gov.do/canonico",
                    "identidad_documental_numero": 275,
                    "rol_reconciliacion": "canonico",
                },
                {
                    "numero": "TEMPORAL",
                    "titulo": "Rendición relacionada",
                    "document_id_consultoria": "extra",
                    "url_documento_consultoria_abrir": "https://www.consultoria.gov.do/extra",
                    "identidad_documental_numero": 275,
                    "rol_reconciliacion": "rendicion_complementaria",
                },
                {
                    "numero": "10952",
                    "titulo": "Gaceta contextual",
                    "document_id_consultoria": "gaceta",
                    "url_documento_consultoria_abrir": "https://www.consultoria.gov.do/gaceta",
                    "rol_reconciliacion": "fuente_contextual_no_decreto",
                },
            ]
            inventory.write_text(
                json.dumps(
                    {
                        "resumen": {"registros_fuente": 3, "identidades_documentales": 1},
                        "registros_fuente": records,
                        "documentos": {"decretos": [records[0]]},
                    }
                ),
                encoding="utf-8",
            )
            package = repo / "datos/decretos/2019/decreto-275-2019.json"
            pdf = repo / "archivos/decretos/2019/decreto-275-2019.pdf"
            markdown = repo / "docs/decretos/2019/decreto-275-2019.md"
            package.parent.mkdir(parents=True); pdf.parent.mkdir(parents=True); markdown.parent.mkdir(parents=True)
            pdf.write_bytes(pdf_bytes("documento canónico")); markdown.write_text("# Decreto 275-2019\n\nLEY.DO no es una fuente oficial.\nLEY.DO no ofrece asesoría legal.\n\n## Metadata\n\n## Texto\n\n## Notas de revisión\n", encoding="utf-8")
            package.write_text(
                json.dumps(
                    {
                        "document_id_consultoria": "canonico",
                        "numero": "275",
                        "anio": "2019",
                        "ruta_pdf_local": "archivos/decretos/2019/decreto-275-2019.pdf",
                        "ruta_markdown": "docs/decretos/2019/decreto-275-2019.md",
                        "ruta_json": "datos/decretos/2019/decreto-275-2019.json",
                        "institucion_fuente": "Consultoria Juridica",
                        "url_fuente_oficial": "https://www.consultoria.gov.do/",
                        "url_pdf_original": "https://www.consultoria.gov.do/canonico.pdf",
                        "url_documento_oficial": "https://www.consultoria.gov.do/canonico",
                        "sha256_pdf_original": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                        "sha256_markdown": hashlib.sha256(markdown.read_bytes()).hexdigest(),
                        "estado_revision": "pendiente_revision",
                        "estado_publicacion": "normalizado",
                        "estado_extraccion": "extraido_desde_pdf_oficial",
                    }
                ),
                encoding="utf-8",
            )

            index = generate_index(repo, inventory, 2019)
            content = index.read_text(encoding="utf-8")

            self.assertIn("canonico", content)
            self.assertIn("extra", content)
            self.assertIn("gaceta", content)
            self.assertIn("[Decreto 275-2019](decreto-275-2019.md)", content)
            self.assertIn("rendición oficial relacionada", content)
            self.assertIn("fuente contextual oficial", content)


    def test_rechaza_respuesta_mas_corta_que_content_length(self):
        data = pdf_bytes("válido pero truncado según cabecera")
        class Response(io.BytesIO):
            headers = {"Content-Length": str(len(data) + 100)}
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def geturl(self): return "https://www.consultoria.gov.do/documento.pdf"
        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "documento.pdf"
            with self.assertRaisesRegex(ValueError, "Content-Length"):
                download_pdf("https://www.consultoria.gov.do/documento.pdf", destination, opener=lambda *a, **k: Response(data), retries=1, sleeper=lambda _: None)
            self.assertFalse(destination.exists())

    def test_reintenta_incomplete_read_y_limpia_temporales(self):
        attempts = []
        class Response:
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def geturl(self): return "https://www.consultoria.gov.do/documento.pdf"
            def read(self, size=-1): raise http.client.IncompleteRead(b"%PDF-parcial", 100)
        def opener(*args, **kwargs): attempts.append(1); return Response()
        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "documento.pdf"
            with self.assertRaises(http.client.IncompleteRead):
                download_pdf("https://www.consultoria.gov.do/documento.pdf", destination, opener=opener, retries=3, sleeper=lambda _: None)
            self.assertEqual(len(attempts), 3)
            self.assertEqual(list(Path(td).glob("*.tmp")), [])

    def test_rechaza_rendicion_fuera_de_la_raiz_anual_permitida(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td); inventory = repo / "reconciliado.json"
            record = {"numero":"1-19","document_id_consultoria":"id-1","url_documento_consultoria_descargar":"https://www.consultoria.gov.do/1.pdf","rendiciones_oficiales_relacionadas":[{"ruta_pdf_local":"docs/sobrescrito.pdf","url_pdf_oficial":"https://www.consultoria.gov.do/extra.pdf"}]}
            inventory.write_text(json.dumps({"documentos":{"decretos":[record]}}),encoding="utf-8")
            def fake_download(url,destination,**kwargs): Path(destination).parent.mkdir(parents=True,exist_ok=True); Path(destination).write_bytes(pdf_bytes("oficial")); return hashlib.sha256(Path(destination).read_bytes()).hexdigest()
            result=process_documents(repo,inventory,2019,[1],downloader=fake_download,normalizer=lambda *a,**k:None)
            self.assertEqual(result["ok"],[])
            self.assertIn("raíz permitida",result["errors"][0]["error"])
            self.assertFalse((repo/"docs/sobrescrito.pdf").exists())

    def test_rechaza_symlink_en_ruta_de_salida(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td)/"repo"; outside=Path(td)/"outside"; repo.mkdir(); outside.mkdir()
            try: (repo/"archivos").symlink_to(outside,target_is_directory=True)
            except OSError as exc: self.skipTest(f"symlink no disponible: {exc}")
            allowed=repo/"archivos/decretos/2019"
            with self.assertRaisesRegex(ValueError,"enlace simbólico"):
                _safe_repo_path(repo,"archivos/decretos/2019/decreto-001-2019.pdf",allowed_root=allowed)

    def test_redescarga_pdf_canonico_si_no_coincide_hash_oficial(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td); inventory=repo/"reconciliado.json"; correct=pdf_bytes("correcto"); expected=hashlib.sha256(correct).hexdigest()
            record={"numero":"1-19","document_id_consultoria":"id-1","sha256_pdf":expected,"url_documento_consultoria_descargar":"https://www.consultoria.gov.do/1.pdf"}
            inventory.write_text(json.dumps({"documentos":{"decretos":[record]}}),encoding="utf-8")
            canonical=repo/"archivos/decretos/2019/decreto-001-2019.pdf"; canonical.parent.mkdir(parents=True); canonical.write_bytes(pdf_bytes("alterado")); calls=[]
            def fake_download(url,destination,**kwargs): calls.append(kwargs); Path(destination).write_bytes(correct); return expected
            result=process_documents(repo,inventory,2019,[1],downloader=fake_download,normalizer=lambda *a,**k:None)
            self.assertEqual(result,{"ok":[1],"errors":[]}); self.assertEqual(calls,[{"expected_hash":expected}]); self.assertEqual(canonical.read_bytes(),correct)

    def test_rechaza_manifiesto_corrupto_sin_sobrescribirlo(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=root/"inventario.json"; inventory.write_text("{}",encoding="utf-8"); manifest=root/"manifest.json"; manifest.write_text("{corrupto",encoding="utf-8")
            exit_code=main(["--repo",str(root),"--inventario",str(inventory),"--anio","2019","--numeros","1","--manifiesto",str(manifest)],processor=lambda *a,**k:{"ok":[1],"errors":[]})
            self.assertEqual(exit_code,1); self.assertEqual(manifest.read_text(encoding="utf-8"),"{corrupto")

    def test_rechaza_manifiesto_de_schema_incompatible(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=root/"inventario.json"; inventory.write_text("{}",encoding="utf-8"); manifest=root/"manifest.json"; original=json.dumps({"schema_version":"0.0","anio":2019,"inventario":"inventario.json","sha256_inventario":hashlib.sha256(inventory.read_bytes()).hexdigest(),"numeros":[1],"resultado":{"ok":[1],"errors":[]}}); manifest.write_text(original,encoding="utf-8"); calls=[]
            exit_code=main(["--repo",str(root),"--inventario",str(inventory),"--anio","2019","--numeros","1","--manifiesto",str(manifest)],processor=lambda *a,**k:calls.append(1) or {"ok":[1],"errors":[]})
            self.assertEqual(exit_code,1); self.assertEqual(calls,[]); self.assertEqual(manifest.read_text(encoding="utf-8"),original)

    def test_rechaza_numero_solicitado_ausente_del_inventario(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=root/"inventario.json"; inventory.write_text(json.dumps({"documentos":{"decretos":[]},"registros_fuente":[]}),encoding="utf-8"); manifest=root/"manifest.json"; calls=[]
            exit_code=main(["--repo",str(root),"--inventario",str(inventory),"--anio","2019","--numeros","999","--manifiesto",str(manifest)],processor=lambda *a,**k:calls.append(1) or {"ok":[999],"errors":[]})
            self.assertEqual(exit_code,1); self.assertEqual(calls,[])

    def test_indice_rechaza_ids_duplicados_en_registros_fuente(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td); inventory=repo/"reconciliado.json"; records=[{"numero":"TEMP-A","document_id_consultoria":"duplicado","rol_reconciliacion":"fuente_contextual_no_decreto"},{"numero":"TEMP-B","document_id_consultoria":"duplicado","rol_reconciliacion":"fuente_contextual_no_decreto"}]
            inventory.write_text(json.dumps({"documentos":{"decretos":[]},"registros_fuente":records}),encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"ID de registro fuente duplicado"): generate_index(repo,inventory,2019)


    def test_reanudacion_no_confia_en_paquete_con_trazabilidad_incompleta(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td); record={"numero":"1-19","anio":"2019","identidad_documental_numero":1,"document_id_consultoria":"id-1","institucion_fuente":"Consultoria Juridica","url_fuente_oficial":"https://www.consultoria.gov.do/","url_documento_consultoria_descargar":"https://www.consultoria.gov.do/1.pdf","url_documento_consultoria_abrir":"https://www.consultoria.gov.do/1"}
            pdf=repo/"archivos/decretos/2019/decreto-001-2019.pdf"; md=repo/"docs/decretos/2019/decreto-001-2019.md"; package=repo/"datos/decretos/2019/decreto-001-2019.json"
            pdf.parent.mkdir(parents=True); md.parent.mkdir(parents=True); package.parent.mkdir(parents=True)
            pdf.write_bytes(pdf_bytes("oficial")); md.write_text("# Decreto 001-2019\n\nLEY.DO no es una fuente oficial.\nLEY.DO no ofrece asesoría legal.\n\n## Metadata\n\n## Texto\n\n## Notas de revisión\n",encoding="utf-8")
            package.write_text(json.dumps({"document_id_consultoria":"id-1","numero":"001","anio":"2019","institucion_fuente":"Consultoria Juridica","url_fuente_oficial":"https://www.consultoria.gov.do/","url_pdf_original":"https://evil.example/1.pdf","url_documento_oficial":"https://www.consultoria.gov.do/1","ruta_pdf_local":"archivos/decretos/2019/decreto-001-2019.pdf","ruta_markdown":"docs/decretos/2019/decreto-001-2019.md","ruta_json":"datos/decretos/2019/otro.json","sha256_pdf_original":hashlib.sha256(pdf.read_bytes()).hexdigest(),"sha256_markdown":hashlib.sha256(md.read_bytes()).hexdigest(),"estado_revision":"pendiente_revision","estado_publicacion":"alterado","estado_extraccion":"desconocido"}),encoding="utf-8")
            inventory={"documentos":{"decretos":[record]},"registros_fuente":[record]}
            self.assertEqual(_validated_packages(repo,inventory,2019),{})


    def test_cli_reprocess_fuerza_un_ok_de_manifiesto_compatible(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=root/"inventario.json"; inventory.write_text("{}",encoding="utf-8"); manifest=root/"manifest.json"
            manifest.write_text(json.dumps({"schema_version":"1.1","anio":2019,"inventario":"inventario.json","sha256_inventario":hashlib.sha256(inventory.read_bytes()).hexdigest(),"numeros":[1],"resultado":{"ok":[1],"errors":[]}}),encoding="utf-8"); calls=[]
            exit_code=main(["--repo",str(root),"--inventario",str(inventory),"--anio","2019","--numeros","1","--manifiesto",str(manifest),"--reprocess"],processor=lambda *a,**k:calls.append(list(a[3])) or {"ok":list(a[3]),"errors":[]})
            self.assertEqual(exit_code,0); self.assertEqual(calls,[[1]])


    def test_rechaza_componente_symlink_de_forma_portable(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td)
            original=Path.is_symlink
            with mock.patch.object(Path,"is_symlink",autospec=True,side_effect=lambda candidate: candidate.name=="archivos" or original(candidate)):
                with self.assertRaisesRegex(ValueError,"enlace simbólico"):
                    _safe_repo_path(repo,"archivos/decretos/2019/decreto-001-2019.pdf",allowed_root=repo/"archivos/decretos/2019")

    def test_scripts_admiten_import_directo_desde_directorio_scripts(self):
        code="import sys; sys.path.insert(0,'scripts'); import normalizar_decretos_consultoria as n; import procesar_decretos_consultoria as p; assert callable(p.process_documents); assert 'consultoria.gov.do' in n.official_link('https://www.consultoria.gov.do/prueba.pdf')"
        completed=subprocess.run([sys.executable,"-c",code],cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True)
        self.assertEqual(completed.returncode,0,completed.stderr)


if __name__ == "__main__":
    unittest.main()
