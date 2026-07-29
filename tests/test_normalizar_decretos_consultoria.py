import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import pymupdf

from scripts.normalizar_decretos_consultoria import extract, fecha_dado, run, title


class FechaDadoTests(unittest.TestCase):
    def test_detecta_fecha_parentetica_en_el_apartado_dado(self):
        pages = [
            "DADO en Santo Domingo de Guzmán, a los veinte (20) días "
            "del mes de febrero del año dos mil diecinueve (2019)."
        ]

        self.assertEqual(fecha_dado(pages, 2019), "20/02/2019")

    def test_detecta_dia_con_espacios_dentro_del_parentesis(self):
        pages = [
            "DADO en Santo Domingo, a los cuatro ( 4 ) días del mes de julio "
            "del año dos mil diecinueve (2019)."
        ]

        self.assertEqual(fecha_dado(pages, 2019), "04/07/2019")

    def test_rechaza_identidad_duplicada_sin_id_explicito(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            inventory_path = repo / "reconciliado.json"
            inventory_path.write_text(
                json.dumps(
                    {
                        "documentos": {
                            "decretos": [
                                {"numero": "284-19", "document_id_consultoria": "uno"},
                                {"numero": "284-19", "document_id_consultoria": "dos"},
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "múltiples registros"):
                run(repo, 2019, [284], inventario_path=inventory_path)

    def test_documenta_discrepancia_entre_metadata_y_dado(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            pdf = repo / "archivos/decretos/2019/decreto-066-2019.pdf"
            pdf.parent.mkdir(parents=True)
            document = pymupdf.open()
            page = document.new_page()
            page.insert_text(
                (72, 72),
                "Dec. No. 66-19 que dispone una medida.\n"
                "DANILO MEDINA\nPresidente de la Republica Dominicana\n"
                "NUMERO: 66-19\nARTICULO 1. Texto.\n"
                "DADO en Santo Domingo, a los veinte (20) dias del mes de febrero "
                "del ano dos mil diecinueve (2019).",
                fontsize=10,
            )
            document.save(pdf)
            document.close()
            inventory_path = repo / "reconciliado.json"
            inventory_path.write_text(
                json.dumps(
                    {
                        "documentos": {
                            "decretos": [
                                {
                                    "numero": "66-19",
                                    "document_id_consultoria": "id-66",
                                    "fecha_documento": "20/02/2016",
                                    "gaceta_oficial": "10934",
                                    "institucion_fuente": "Fuente oficial",
                                    "url_fuente_oficial": "https://oficial.example/",
                                    "url_documento_consultoria_abrir": "https://oficial.example/66",
                                    "url_documento_consultoria_descargar": "https://oficial.example/66.pdf",
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            run(repo, 2019, [66], inventario_path=inventory_path)

            metadata = json.loads(
                (repo / "datos/decretos/2019/decreto-066-2019.json").read_text(encoding="utf-8")
            )
            markdown = (repo / "docs/decretos/2019/decreto-066-2019.md").read_text(encoding="utf-8")
            self.assertEqual(metadata["fecha_metadata_fuente"], "20/02/2016")
            self.assertEqual(metadata["fecha_texto_pdf_detectada"], "20/02/2019")
            self.assertTrue(metadata["alertas_revision"])
            self.assertIn("Fecha observada en texto PDF: 20/02/2019", markdown)

    def test_preserva_procedencia_y_rendiciones_oficiales(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            canonical = repo / "archivos/decretos/2019/decreto-275-2019.pdf"
            related = repo / "archivos/decretos/2019/decreto-275-2019-fuente-extra.pdf"
            canonical.parent.mkdir(parents=True)
            document = pymupdf.open()
            page = document.new_page()
            page.insert_text(
                (72, 72),
                "Dec. No. 275-19 que otorga exequatur.\n"
                "NUMERO: 275-19\nARTICULO 1. Texto.\n"
                "DADO en Santo Domingo, al primer (1) dia del mes de agosto "
                "del ano dos mil diecinueve (2019).",
                fontsize=10,
            )
            document.save(canonical)
            document.close()
            related.write_bytes(canonical.read_bytes())
            related_hash = hashlib.sha256(related.read_bytes()).hexdigest()
            inventory_path = repo / "reconciliado.json"
            inventory_path.write_text(
                json.dumps(
                    {
                        "documentos": {
                            "decretos": [
                                {
                                    "numero": "275-19",
                                    "numero_registro_fuente": "TEMPORAL CORREGIR ULTIMA HOJA",
                                    "anio": "2019",
                                    "anio_metadata_fuente": "2019",
                                    "inventario_origen": "consultoria_inventario_2019",
                                    "alertas_revision": ["Alerta comprobada en la fuente."],
                                    "observacion_fecha_pdf": "El mes no aparece en la cláusula DADO.",
                                    "document_id_consultoria": "id-275",
                                    "fecha_documento": "01/08/2019",
                                    "institucion_fuente": "Fuente oficial",
                                    "url_fuente_oficial": "https://oficial.example/",
                                    "url_documento_consultoria_abrir": "https://oficial.example/275",
                                    "url_documento_consultoria_descargar": "https://oficial.example/275.pdf",
                                    "rendiciones_oficiales_relacionadas": [
                                        {
                                            "document_id_consultoria": "id-extra",
                                            "rol_archivistico": "rendicion_complementaria",
                                            "ruta_pdf_local": "archivos/decretos/2019/decreto-275-2019-fuente-extra.pdf",
                                            "url_pdf_oficial": "https://oficial.example/extra.pdf",
                                            "sha256_pdf": related_hash,
                                            "capa_texto": True,
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            run(repo, 2019, [275], inventario_path=inventory_path)

            metadata = json.loads(
                (repo / "datos/decretos/2019/decreto-275-2019.json").read_text(encoding="utf-8")
            )
            markdown = (repo / "docs/decretos/2019/decreto-275-2019.md").read_text(encoding="utf-8")
            self.assertEqual(metadata["numero_registro_fuente"], "TEMPORAL CORREGIR ULTIMA HOJA")
            self.assertEqual(metadata["inventario_origen"], "consultoria_inventario_2019")
            self.assertEqual(metadata["rendiciones_oficiales_relacionadas"][0]["sha256_pdf"], related_hash)
            self.assertIn("Rendiciones oficiales relacionadas", markdown)
            self.assertIn("id-extra", markdown)
            self.assertIn("Alerta comprobada en la fuente.", markdown)
            self.assertEqual(metadata["observacion_fecha_pdf"], "El mes no aparece en la cláusula DADO.")

    def test_recorta_vecinos_dentro_de_la_misma_pagina(self):
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "recorte.pdf"
            document = pymupdf.open()
            page = document.new_page()
            page.insert_text(
                (72, 72),
                "CIERRE DEL DOCUMENTO ANTERIOR.\n"
                "Dec. No. 5-19 que dispone una medida.\n"
                "NUMERO: 5-19\nARTICULO 1. Texto objetivo.\n"
                "DADO en Santo Domingo, a los cinco (5) dias del mes de enero de 2019.\n"
                "Dec. No. 6-19 que dispone otra medida.\n"
                "NUMERO: 6-19\nARTICULO 1. Texto vecino.",
                fontsize=10,
            )
            document.save(pdf)
            document.close()

            pages, trimmed, *_ = extract(pdf, 5, "19")
            extracted = "\n".join(pages)

            self.assertTrue(extracted.startswith("Dec. No. 5-19"))
            self.assertIn("Texto objetivo", extracted)
            self.assertNotIn("DOCUMENTO ANTERIOR", extracted)
            self.assertNotIn("Dec. No. 6-19", extracted)
            self.assertEqual(trimmed, ["fragmento_anterior", 6])

    def test_usa_numero_formal_si_falta_encabezado_sumario(self):
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "formal.pdf"
            document = pymupdf.open()
            page = document.new_page()
            page.insert_text(
                (72, 72),
                "MEMBRETE OFICIAL\n"
                "NUMERO: 241-19\n"
                "VISTO: Un antecedente.\n"
                "DECRETO:\nARTICULO 1. Texto objetivo.\n"
                "DADO en Santo Domingo, a los cuatro (4) dias del mes de julio de 2019.",
                fontsize=10,
            )
            document.save(pdf)
            document.close()

            pages, trimmed, state, document_class, header_number = extract(pdf, 241, "19")

            self.assertEqual(state, "extraido_desde_pdf_oficial")
            self.assertTrue(pages[0].startswith("NUMERO: 241-19"))
            self.assertEqual(trimmed, ["fragmento_anterior"])
            self.assertEqual(document_class, "Dec.")
            self.assertEqual(header_number, "241-19")
            self.assertEqual(title(pages, 241, "19", 2019), "Decreto núm. 241-2019")


if __name__ == "__main__":
    unittest.main()
