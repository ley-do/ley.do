import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

import fitz

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from scripts.auditar_decretos_consultoria import audit
from scripts.procesar_decretos_consultoria import generate_index


def make_pdf(text):
    doc=fitz.open(); page=doc.new_page(); page.insert_text((72,72),text,fontsize=9); data=doc.tobytes(); doc.close(); return data


class AuditorDecretosTests(unittest.TestCase):
    def make_corpus(self,root,formal="1-19",alerts=None,dado_year=2019):
        record={"numero":"1-19","anio":"2019","identidad_documental_numero":1,"document_id_consultoria":"id-1","institucion_fuente":"Consultoria Juridica","url_fuente_oficial":"https://www.consultoria.gov.do/","url_documento_consultoria_descargar":"https://www.consultoria.gov.do/1.pdf","url_documento_consultoria_abrir":"https://www.consultoria.gov.do/1","titulo":"Prueba","fecha_documento":"01/01/2019","gaceta_oficial":"10900"}
        inventory={"resumen":{"total_registros_fuente":1,"total_identidades_documentales":1},"registros_fuente":[record],"documentos":{"decretos":[record]}}
        inventory_path=root/"fuentes/inventario.json"; inventory_path.parent.mkdir(parents=True); inventory_path.write_text(json.dumps(inventory),encoding="utf-8")
        pdf=root/"archivos/decretos/2019/decreto-001-2019.pdf"; md=root/"docs/decretos/2019/decreto-001-2019.md"; js=root/"datos/decretos/2019/decreto-001-2019.json"
        pdf.parent.mkdir(parents=True); md.parent.mkdir(parents=True); js.parent.mkdir(parents=True)
        dado_words="dos mil dieciocho" if dado_year==2018 else "dos mil diecinueve"
        pdf.write_bytes(make_pdf(f"Dec. No. 1-19\nNUMERO: {formal}\nDADO en Santo Domingo, a un (1) dia del mes de enero del ano {dado_words} ({dado_year})."))
        md.write_text("# Decreto 001-2019\n\nLEY.DO no es una fuente oficial.\nLEY.DO no ofrece asesoría legal.\n\n## Metadata\n\n## Texto\n\nTexto.\n\n## Notas de revisión\n",encoding="utf-8")
        metadata={"tipo_documento":"decreto","numero":"001","anio":"2019","document_id_consultoria":"id-1","institucion_fuente":"Consultoria Juridica","url_fuente_oficial":"https://www.consultoria.gov.do/","url_pdf_original":"https://www.consultoria.gov.do/1.pdf","url_documento_oficial":"https://www.consultoria.gov.do/1","ruta_pdf_local":"archivos/decretos/2019/decreto-001-2019.pdf","ruta_markdown":"docs/decretos/2019/decreto-001-2019.md","ruta_json":"datos/decretos/2019/decreto-001-2019.json","sha256_pdf_original":hashlib.sha256(pdf.read_bytes()).hexdigest(),"sha256_markdown":hashlib.sha256(md.read_bytes()).hexdigest(),"estado_revision":"pendiente_revision","estado_publicacion":"normalizado","estado_extraccion":"extraido_desde_pdf_oficial","fecha":"01/01/2019","gaceta_oficial":"10900","fecha_texto_pdf_detectada":"01/01/2019","estado_fecha_texto_pdf":"detectada","numero_formal_pdf":formal,"fragmentos_decretos_vecinos_excluidos":[]}
        if alerts: metadata["alertas_revision"]=alerts
        js.write_text(json.dumps(metadata),encoding="utf-8"); generate_index(root,inventory_path,2019); return inventory_path

    def test_audita_un_corpus_minimo_valido(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_corpus(root); report=audit(root,inventory,2019)
            self.assertEqual(report["errores"],[]); self.assertEqual(report["resumen"]["identidades_documentales"],1); self.assertEqual(report["resumen"]["filas_indice"],1)

    def test_falla_si_fecha_del_json_contradice_fuente_reconciliada(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_corpus(root); path=root/"datos/decretos/2019/decreto-001-2019.json"; metadata=json.loads(path.read_text(encoding="utf-8")); metadata["fecha"]="31/12/1999"; path.write_text(json.dumps(metadata),encoding="utf-8")
            report=audit(root,inventory,2019)
            self.assertTrue(any("fecha" in error.lower() and "fuente" in error.lower() for error in report["errores"]))

    def test_falla_si_gaceta_del_json_contradice_fuente_reconciliada(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_corpus(root); path=root/"datos/decretos/2019/decreto-001-2019.json"; metadata=json.loads(path.read_text(encoding="utf-8")); metadata["gaceta_oficial"]="99999"; path.write_text(json.dumps(metadata),encoding="utf-8")
            report=audit(root,inventory,2019)
            self.assertTrue(any("gaceta" in error.lower() and "fuente" in error.lower() for error in report["errores"]))

    def test_falla_si_numero_formal_discrepa_sin_alerta(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_corpus(root,formal="0-19"); report=audit(root,inventory,2019)
            self.assertTrue(any("formal" in error.lower() for error in report["errores"]))


    def test_conserva_anio_dado_observado_si_discrepancia_esta_documentada(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_corpus(root,dado_year=2018); path=root/"datos/decretos/2019/decreto-001-2019.json"; metadata=json.loads(path.read_text(encoding="utf-8")); metadata["fecha_texto_pdf_detectada"]="01/01/2018"; metadata["fecha_metadata_fuente"]="01/01/2019"; metadata["alertas_revision"]=["La metadata oficial indica 2019 y el DADO observado indica 2018; se conservan ambos valores."]; path.write_text(json.dumps(metadata),encoding="utf-8")
            report=audit(root,inventory,2019)
            self.assertEqual(report["errores"],[]); self.assertEqual(report["resumen"]["discrepancias_fecha_documentadas"],1)


    def test_falla_si_json_dado_contradice_pdf(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_corpus(root,dado_year=2019); path=root/"datos/decretos/2019/decreto-001-2019.json"; metadata=json.loads(path.read_text(encoding="utf-8")); metadata["fecha_texto_pdf_detectada"]="01/01/2018"; metadata["fecha_metadata_fuente"]="01/01/2019"; metadata["alertas_revision"]=["La metadata oficial indica 2019 y el DADO observado indica 2018; se conservan ambos valores."]; path.write_text(json.dumps(metadata),encoding="utf-8")
            report=audit(root,inventory,2019)
            self.assertTrue(any("dado" in error.lower() and "pdf" in error.lower() for error in report["errores"]))


    def test_audita_indice_de_encapsulados_con_rutas_publicas(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_corpus(root)
            index=root/"docs/decretos/2019/index.md"
            index.write_text(
                "# Decretos 2019\n\n"
                "<div class=\"leydo-doclist\">\n"
                "<a class=\"leydo-doc\" href=\"decreto-001-2019/\">\n"
                "<span class=\"leydo-doc-num\">001-2019</span>\n"
                "<span class=\"leydo-doc-date\">01/01/2019</span>\n"
                "<span class=\"leydo-doc-title\">Prueba</span>\n"
                "</a>\n</div>\n",
                encoding="utf-8",
            )
            report=audit(root,inventory,2019)
            self.assertEqual(report["errores"],[])
            self.assertEqual(report["resumen"]["filas_indice"],1)



    def make_ocr_package(self,root,warning_before_text=True,altered_markdown_line=""):
        inventory=self.make_corpus(root)
        pdf=root/"archivos/decretos/2019/decreto-001-2019.pdf"
        original=fitz.open(pdf); pix=original[0].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False); original.close()
        escaneado=fitz.open(); pagina=escaneado.new_page(width=pix.width,height=pix.height); pagina.insert_image(pagina.rect,stream=pix.tobytes("png")); pdf.write_bytes(escaneado.tobytes()); escaneado.close()
        ocr=root/"datos/decretos/2019/decreto-001-2019.ocr.txt"; ocr_text='===== PÁGINA 1 DEL PDF =====\n\nNÚMERO:\n1-19\nDECRETO:\nDADO en Santo Domingo.'; ocr.write_text(ocr_text,encoding="utf-8")
        body=re.sub(r"(?m)^===== PÁGINA (\d+) DEL PDF =====$",lambda match:f"### Página {match.group(1)} del PDF",ocr_text).strip()
        nl=chr(10)
        if altered_markdown_line: body+=nl+altered_markdown_line
        warning='!!! warning "Texto OCR pendiente de revisión"\n    Texto generado mediante OCR local.'; prefix='# Decreto 001-2019\n\nLEY.DO no es una fuente oficial.\nLEY.DO no ofrece asesoría legal.\n\n'; metadata_section='## Metadata\n\n'; notes='## Notas de revisión\n\n- OCR pendiente de revisión humana.\n'
        if warning_before_text:
            markdown=prefix+warning+nl+nl+metadata_section+"## Texto"+nl+nl+body+nl+nl+notes
        else:
            markdown=prefix+metadata_section+"## Texto"+nl+nl+body+nl+nl+warning+nl+nl+notes
        md=root/"docs/decretos/2019/decreto-001-2019.md"; md.write_text(markdown,encoding="utf-8")
        js=root/"datos/decretos/2019/decreto-001-2019.json"; metadata=json.loads(js.read_text(encoding="utf-8"))
        metadata.update({"sha256_pdf_original":hashlib.sha256(pdf.read_bytes()).hexdigest(),"sha256_markdown":hashlib.sha256(md.read_bytes()).hexdigest(),"estado_extraccion":"ocr_asistido_pendiente_revision","capa_texto_pdf_original":False,"herramienta_ocr":"EasyOCR 1.7.2","procedencia_ocr":"local","ruta_texto_ocr":"datos/decretos/2019/decreto-001-2019.ocr.txt","sha256_texto_ocr":hashlib.sha256(ocr.read_bytes()).hexdigest(),"estado_fecha_texto_pdf":"no_disponible_pdf_escaneado","fecha_texto_pdf_detectada":"","numero_formal_pdf":"","alertas_revision":["El PDF oficial no contiene capa de texto. Texto generado mediante OCR local y pendiente de revisión humana."]})
        js.write_text(json.dumps(metadata),encoding="utf-8")
        return inventory

    def test_audita_paquete_ocr_documentado_sin_capa_de_texto(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_ocr_package(root); report=audit(root,inventory,2019)
            self.assertEqual(report["errores"],[])
            self.assertEqual(report["resumen"]["documentos_ocr_pendientes_revision"],1)

    def test_rechaza_paquete_ocr_de_procedencia_remota(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_ocr_package(root)
            js=root/"datos/decretos/2019/decreto-001-2019.json"; metadata=json.loads(js.read_text(encoding="utf-8")); metadata.update({"herramienta_ocr":"Servicio OCR remoto","procedencia_ocr":"remota"}); js.write_text(json.dumps(metadata),encoding="utf-8")
            report=audit(root,inventory,2019)
            self.assertTrue(any("OCR" in error for error in report["errores"]))

    def test_rechaza_paquete_ocr_con_herramienta_no_local(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_ocr_package(root)
            js=root/"datos/decretos/2019/decreto-001-2019.json"; metadata=json.loads(js.read_text(encoding="utf-8")); metadata["herramienta_ocr"]="Servicio OCR remoto"; js.write_text(json.dumps(metadata),encoding="utf-8")
            report=audit(root,inventory,2019)
            self.assertTrue(any("OCR" in error for error in report["errores"]))

    def test_rechaza_paquete_ocr_si_aviso_aparece_despues_del_texto(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_ocr_package(root,warning_before_text=False); report=audit(root,inventory,2019)
            self.assertTrue(any("OCR" in error for error in report["errores"]))

    def test_rechaza_paquete_ocr_si_aviso_esta_oculto_en_comentario(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_ocr_package(root)
            md=root/"docs/decretos/2019/decreto-001-2019.md"; content=md.read_text(encoding="utf-8"); nl=chr(10); marker='!!! warning "Texto OCR pendiente de revisión"'; content=content.replace(marker,'<!--'+nl+marker,1).replace('    Texto generado mediante OCR local.','    Texto generado mediante OCR local.'+nl+'-->',1); md.write_text(content,encoding="utf-8")
            js=root/"datos/decretos/2019/decreto-001-2019.json"; metadata=json.loads(js.read_text(encoding="utf-8")); metadata["sha256_markdown"]=hashlib.sha256(md.read_bytes()).hexdigest(); js.write_text(json.dumps(metadata),encoding="utf-8")
            report=audit(root,inventory,2019)
            self.assertTrue(any("OCR" in error for error in report["errores"]))

    def test_rechaza_paquete_ocr_si_texto_publicado_no_coincide_con_ocr(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); inventory=self.make_ocr_package(root,altered_markdown_line="Texto jurídico inventado sin origen OCR."); report=audit(root,inventory,2019)
            self.assertTrue(any("OCR" in error for error in report["errores"]))

    def test_rechaza_anio_formal_distinto_sin_evidencia_reconciliada(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            inventory=self.make_corpus(root,formal="1-06",alerts=["La línea formal del PDF indica 1-06 mientras la identidad de fuente es 1-19; se conserva la discrepancia para revisión humana."])
            report=audit(root,inventory,2019)
            self.assertTrue(any("evidencia reconciliada" in error.lower() for error in report["errores"]))


    def test_admite_anio_formal_distinto_con_evidencia_reconciliada_verificable(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            inventory=self.make_corpus(root,formal="1-06",alerts=["La línea formal del PDF indica 1-06 mientras la identidad de fuente es 1-19; se conserva la discrepancia para revisión humana."])
            pdf=root/"archivos/decretos/2019/decreto-001-2019.pdf"
            evidence={
                "tipo_evidencia":"discrepancia_formal_pdf",
                "estado_revision":"pendiente_revision",
                "document_id_consultoria":"id-1",
                "identidad_esperada":"1-19",
                "numero_formal_observado_pdf":"1-06",
                "ruta_pdf_local":"archivos/decretos/2019/decreto-001-2019.pdf",
                "url_pdf_oficial":"https://www.consultoria.gov.do/1.pdf",
                "pagina_pdf":1,
                "sha256_pdf":hashlib.sha256(pdf.read_bytes()).hexdigest(),
            }
            reconciled=json.loads(inventory.read_text(encoding="utf-8"))
            reconciled["registros_fuente"][0]["evidencia_discrepancia_formal"]=evidence
            reconciled["documentos"]["decretos"][0]["evidencia_discrepancia_formal"]=evidence
            inventory.write_text(json.dumps(reconciled),encoding="utf-8")
            metadata_path=root/"datos/decretos/2019/decreto-001-2019.json"
            metadata=json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["evidencia_discrepancia_formal"]=evidence
            metadata_path.write_text(json.dumps(metadata),encoding="utf-8")

            report=audit(root,inventory,2019)

            self.assertEqual(report["errores"],[])
            self.assertEqual(report["discrepancias_numero_formal"][0]["numero_formal_pdf"],"1-06")



if __name__=="__main__": unittest.main()
