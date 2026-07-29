import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.procesar_decretos_consultoria import download_pdf, generate_index, main, parse_numbers, process_documents


class ProcesarDecretosTests(unittest.TestCase):
    def test_expande_rangos_y_elimina_repetidos(self):
        self.assertEqual(parse_numbers("1-3,2,5"), [1, 2, 3, 5])

    def test_descarga_pdf_validado_de_forma_atomica(self):
        data = b"%PDF-1.4\ncontenido"

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return data

        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "documento.pdf"
            digest = download_pdf("https://oficial.example/documento.pdf", destination, opener=lambda *args, **kwargs: Response())

            self.assertEqual(destination.read_bytes(), data)
            self.assertEqual(digest, hashlib.sha256(data).hexdigest())
            self.assertFalse(destination.with_suffix(".pdf.tmp").exists())

    def test_reintenta_descarga_transitoria_hasta_tres_veces(self):
        data = b"%PDF-1.4\ncontenido"
        attempts = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return data

        def opener(*args, **kwargs):
            attempts.append(1)
            if len(attempts) < 3:
                raise OSError("fallo transitorio")
            return Response()

        with tempfile.TemporaryDirectory() as td:
            destination = Path(td) / "documento.pdf"
            download_pdf(
                "https://oficial.example/documento.pdf",
                destination,
                opener=opener,
                retries=3,
                sleeper=lambda _: None,
            )

        self.assertEqual(len(attempts), 3)

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
                                    "url_documento_consultoria_descargar": "https://oficial.example/canonico.pdf",
                                    "rendiciones_oficiales_relacionadas": [
                                        {
                                            "document_id_consultoria": "extra",
                                            "ruta_pdf_local": "archivos/decretos/2019/decreto-275-2019-extra.pdf",
                                            "url_pdf_oficial": "https://oficial.example/extra.pdf",
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

    def test_cli_escribe_manifiesto_reanudable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inventory = root / "inventario.json"
            inventory.write_text("{}", encoding="utf-8")
            manifest = root / "manifest.json"
            calls = []

            def processor(repo, inventory_path, year, numbers):
                calls.append((Path(repo), Path(inventory_path), year, numbers))
                return {"ok": [1, 2], "errors": []}

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
            self.assertEqual(calls[0][2:], (2019, [1, 2]))
            self.assertEqual(saved["resultado"], {"ok": [1, 2], "errors": []})
            self.assertEqual(saved["estado"], "completado")
            self.assertTrue((root / "docs/decretos/2019/index.md").is_file())

    def test_indice_preserva_cada_registro_fuente_y_relacion(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            inventory = repo / "reconciliado.json"
            records = [
                {
                    "numero": "275-19",
                    "titulo": "Documento canónico",
                    "document_id_consultoria": "canonico",
                    "url_documento_consultoria_abrir": "https://oficial.example/canonico",
                    "identidad_documental_numero": 275,
                    "rol_reconciliacion": "canonico",
                },
                {
                    "numero": "TEMPORAL",
                    "titulo": "Rendición relacionada",
                    "document_id_consultoria": "extra",
                    "url_documento_consultoria_abrir": "https://oficial.example/extra",
                    "identidad_documental_numero": 275,
                    "rol_reconciliacion": "rendicion_complementaria",
                },
                {
                    "numero": "10952",
                    "titulo": "Gaceta contextual",
                    "document_id_consultoria": "gaceta",
                    "url_documento_consultoria_abrir": "https://oficial.example/gaceta",
                    "rol_reconciliacion": "fuente_contextual_no_decreto",
                },
            ]
            inventory.write_text(
                json.dumps(
                    {
                        "resumen": {"registros_fuente": 3, "identidades_documentales": 1},
                        "registros_fuente": records,
                        "documentos": {"decretos": []},
                    }
                ),
                encoding="utf-8",
            )
            package = repo / "datos/decretos/2019/decreto-275-2019.json"
            package.parent.mkdir(parents=True)
            package.write_text(json.dumps({"estado_revision": "pendiente_revision"}), encoding="utf-8")

            index = generate_index(repo, inventory, 2019)
            content = index.read_text(encoding="utf-8")

            self.assertIn("canonico", content)
            self.assertIn("extra", content)
            self.assertIn("gaceta", content)
            self.assertIn("[Decreto 275-2019](decreto-275-2019.md)", content)
            self.assertIn("rendición oficial relacionada", content)
            self.assertIn("fuente contextual oficial", content)


if __name__ == "__main__":
    unittest.main()
