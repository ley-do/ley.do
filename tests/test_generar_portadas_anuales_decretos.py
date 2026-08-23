import hashlib
import json
import tempfile
import unittest

import fitz
from pathlib import Path

from scripts.generar_portadas_anuales_decretos import render_year
from scripts.procesar_decretos_consultoria import generate_index


def make_pdf(text):
    doc=fitz.open(); page=doc.new_page(); page.insert_text((72,72),text,fontsize=9); data=doc.tobytes(); doc.close(); return data


class PortadasAnualesDecretosTests(unittest.TestCase):
    def test_orden_descendente_rutas_publicas_y_sin_inventario_legado(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            validated = {}
            records = []
            for number, date in ((1, "01/01/2026"), (2, "02/01/2026")):
                validated[number] = {
                    "numero": f"{number:03d}",
                    "anio": "2026",
                    "titulo": f"Título del paquete {number}",
                    "fecha": date,
                    "document_id_consultoria": f"id-{number}",
                }
                records.append(
                    {
                        "numero": f"{number}-26",
                        "anio": "2026",
                        "identidad_documental_numero": number,
                        "document_id_consultoria": f"id-{number}",
                        "titulo": f"Título reconciliado {number}",
                        "fecha_documento": date,
                    }
                )
            legacy = repo / "fuentes/consultoria_inventario_2026_leyes_decretos.json"
            legacy.parent.mkdir(parents=True)
            legacy.write_text(
                json.dumps({"documentos": {"decretos": [{"numero": "2-26", "titulo": "Título legado que no debe usarse", "fecha_documento": "31/12/1900"}]}}),
                encoding="utf-8",
            )

            self.assertEqual(render_year(repo, 2026, validated, records), 2)
            content = (repo / "docs/decretos/2026/index.md").read_text(encoding="utf-8")

            self.assertLess(content.index("002-2026"), content.index("001-2026"))
            self.assertIn('href="decreto-002-2026/"', content)
            self.assertNotIn("decreto-002-2026.md", content)
            self.assertIn("Título reconciliado 2", content)
            self.assertNotIn("Título legado que no debe usarse", content)
            self.assertNotIn("31/12/1900", content)

    def test_render_year_rechaza_identidades_no_validadas(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            validated = {1: {"numero": "001", "anio": "2026", "titulo": "Título válido", "fecha": "01/01/2026", "document_id_consultoria": "id-1"}}

            with self.assertRaisesRegex(ValueError, "identidades"):
                render_year(repo, 2026, validated, [])

    def test_generate_index_usa_tarjetas_publicas_ordenadas(self):
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td); records=[]
            for number,date in ((1,"01/01/2026"),(2,"02/01/2026")):
                data=repo/f"datos/decretos/2026/decreto-{number:03d}-2026.json"
                markdown=repo/f"docs/decretos/2026/decreto-{number:03d}-2026.md"
                pdf=repo/f"archivos/decretos/2026/decreto-{number:03d}-2026.pdf"
                data.parent.mkdir(parents=True,exist_ok=True)
                markdown.parent.mkdir(parents=True,exist_ok=True)
                pdf.parent.mkdir(parents=True,exist_ok=True)
                document_id=f"id-{number}"
                record={"numero":f"{number}-26","anio":"2026","identidad_documental_numero":number,"document_id_consultoria":document_id,"institucion_fuente":"Consultoría Jurídica","url_fuente_oficial":"https://www.consultoria.gov.do/","url_documento_consultoria_descargar":f"https://www.consultoria.gov.do/{number}.pdf","url_documento_consultoria_abrir":f"https://www.consultoria.gov.do/{number}","titulo":f"Decreto {number}","fecha_documento":date}
                pdf.write_bytes(make_pdf('Dec. No. {number}-26\nNUMERO: {number}-26\nDADO en Santo Domingo, a {number} de enero de 2026.'.format(number=number)))
                markdown.write_text('# Decreto {number}\n\nLEY.DO no es una fuente oficial.\nLEY.DO no ofrece asesoría legal.\n\n## Metadata\n\n## Texto\n\nTexto.\n\n## Notas de revisión\n'.format(number=number),encoding="utf-8")
                metadata={"tipo_documento":"decreto","numero":f"{number:03d}","anio":"2026","document_id_consultoria":document_id,"institucion_fuente":record["institucion_fuente"],"url_fuente_oficial":record["url_fuente_oficial"],"url_pdf_original":record["url_documento_consultoria_descargar"],"url_documento_oficial":record["url_documento_consultoria_abrir"],"ruta_pdf_local":f"archivos/decretos/2026/decreto-{number:03d}-2026.pdf","ruta_markdown":f"docs/decretos/2026/decreto-{number:03d}-2026.md","ruta_json":f"datos/decretos/2026/decreto-{number:03d}-2026.json","sha256_pdf_original":hashlib.sha256(pdf.read_bytes()).hexdigest(),"sha256_markdown":hashlib.sha256(markdown.read_bytes()).hexdigest(),"estado_revision":"pendiente_revision","estado_publicacion":"normalizado","estado_extraccion":"extraido_desde_pdf_oficial","fecha":date,"fecha_texto_pdf_detectada":date,"estado_fecha_texto_pdf":"detectada","numero_formal_pdf":f"{number}-26","fragmentos_decretos_vecinos_excluidos":[]}
                data.write_text(json.dumps(metadata),encoding="utf-8")
                records.append(record)
            inventory=repo/"fuentes/inventario.json"; inventory.parent.mkdir(parents=True,exist_ok=True)
            inventory.write_text(json.dumps({"resumen":{"registros_fuente":2,"identidades_documentales":2},"registros_fuente":records,"documentos":{"decretos":records}}),encoding="utf-8")
            generate_index(repo,inventory,2026)
            content=(repo/"docs/decretos/2026/index.md").read_text(encoding="utf-8")
            self.assertIn('<a class="leydo-doc" href="decreto-002-2026/">',content)
            self.assertNotIn("decreto-002-2026.md",content)
            self.assertLess(content.index("002-2026"),content.index("001-2026"))


    def test_generate_index_rechaza_paquete_canonico_ausente(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td)
            record = {
                "numero": "1-26",
                "anio": "2026",
                "identidad_documental_numero": 1,
                "document_id_consultoria": "id-1",
                "titulo": "Documento esperado",
                "fecha_documento": "01/01/2026",
                "institucion_fuente": "Consultoría Jurídica",
                "url_fuente_oficial": "https://www.consultoria.gov.do/",
                "url_documento_consultoria_descargar": "https://www.consultoria.gov.do/1.pdf",
                "url_documento_consultoria_abrir": "https://www.consultoria.gov.do/1",
            }
            inventory = repo / "fuentes/inventario.json"
            inventory.parent.mkdir(parents=True)
            inventory.write_text(json.dumps({"registros_fuente": [record], "documentos": {"decretos": [record]}}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Paquetes canónicos"):
                generate_index(repo, inventory, 2026)

if __name__=="__main__": unittest.main()
