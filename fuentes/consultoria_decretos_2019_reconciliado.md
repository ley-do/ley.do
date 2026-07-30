# Reconciliación del inventario oficial de decretos de 2019

## Alcance

Este archivo documenta la reconciliación archivística de los registros de decretos dominicanos de 2019 localizados en las consultas oficiales preservadas por LEY.DO. No interpreta vigencia ni efectos jurídicos.

## Fuentes oficiales

- [Consulta oficial de Consultoría Jurídica del Poder Ejecutivo](https://www.consultoria.gov.do/Consulta/)
- `fuentes/consultoria_inventario_2019_leyes_decretos.json`: 476 registros fuente.
- `fuentes/consultoria_inventario_2020_leyes_decretos.json`: 22 registros adicionales terminados en `-19`.

## Resultado

- Registros fuente preservados: **498**.
- Registros numerados: **496**.
- Registros vinculados a una identidad documental: **497**.
- Identidades documentales: **495**.
- Rendiciones oficiales adicionales: **2**.
- Fuente contextual oficial: **1**.
- Números no detectados entre 1 y 499: **265, 280, 370, 392**.

La ausencia de esos números en las consultas preservadas no demuestra que los decretos no existan. LEY.DO no crea registros faltantes por inferencia.

## Casos conservados explícitamente

- **Decreto 275-19:** se preservan la rendición publicada en Gaceta (ID `3395744`) y la rendición oficial prepublicación (ID `3393955`) con rutas y hashes separados.
- **Decreto 284-19:** se preservan los IDs `3393988` y `3395753`. Tienen texto y renderizado coincidentes, pero binarios y hashes distintos.
- **Registro 10952 (ID `3394115`):** se conserva como fuente contextual de Gaceta Oficial, no como identidad de decreto.
- **Decreto 066-19:** la metadata oficial indica `20/02/2016`; el apartado DADO del PDF indica `20/02/2019`. Ambos valores se conservarán para revisión humana.
- **Decreto 060-19:** la cláusula DADO omite el nombre del mes (`mes de del año`); la metadata oficial indica `07/02/2019`. No se infiere el mes desde el texto incompleto.
- **Decreto 368-19:** la cláusula DADO contiene `mes de veinticuatro`, que no identifica un mes; la metadata oficial indica `24/10/2019`. Se conservan ambos datos.

## Regla editorial

Todo paquete resultante permanecerá en `pendiente_revision`. Si existe conflicto, prevalece la fuente oficial.
