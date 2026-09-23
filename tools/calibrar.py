"""Calibración del Índice de Fidelidad Analítica.

Barre el umbral sobre un conjunto etiquetado, reporta matriz de confusión y
F1 sobre la clase de riesgo (NO_FIEL), mide el ancho de la meseta óptima,
contrasta contra la línea base y hace un análisis de sensibilidad a los pesos.

    python tools/calibrar.py [--casos data/casos_calibracion.json]

Escribe `salida/calibracion.md` además de imprimir las tablas.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from auditor.archivos import leer_json  # noqa: E402
from auditor.config import construir_reglas  # noqa: E402
from auditor.entrada import parsear_casos  # noqa: E402
from auditor.excepciones import EntradaError  # noqa: E402
from auditor.fidelidad import crear_evaluador  # noqa: E402
from auditor.motor import Auditor  # noqa: E402

RIESGO = "NO_FIEL"
PASO = 0.05


@dataclass
class Medida:
    umbral: float
    vp: int
    fp: int
    vn: int
    fn: int

    @property
    def precision(self) -> float:
        return self.vp / (self.vp + self.fp) if self.vp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.vp / (self.vp + self.fn) if self.vp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def auditar(reglas_dict: dict, casos, evaluador: str) -> dict:
    """{id_caso: veredicto} con el evaluador indicado."""
    reglas = construir_reglas(reglas_dict)
    auditor = Auditor(reglas, crear_evaluador(evaluador, reglas))
    return {v.id_caso: v for v in auditor.auditar_lote(casos)}


def medir(indices: dict, etiquetas: dict, umbral: float) -> Medida:
    """Predicción: NO_FIEL si el índice queda por debajo del umbral."""
    m = Medida(umbral, 0, 0, 0, 0)
    for id_caso, indice in indices.items():
        predicho_riesgo = indice < umbral
        real_riesgo = etiquetas[id_caso] == RIESGO
        if predicho_riesgo and real_riesgo:
            m.vp += 1
        elif predicho_riesgo:
            m.fp += 1
        elif real_riesgo:
            m.fn += 1
        else:
            m.vn += 1
    return m


def barrido(indices: dict, etiquetas: dict) -> list[Medida]:
    umbrales = [round(i * PASO, 2) for i in range(int(1 / PASO) + 1)]
    return [medir(indices, etiquetas, u) for u in umbrales]


def meseta(medidas: list[Medida]) -> tuple[list[float], float]:
    """Umbrales con F1 máximo y ancho de esa meseta."""
    mejor = max(m.f1 for m in medidas)
    optimos = [m.umbral for m in medidas if m.f1 == mejor]
    return optimos, round(max(optimos) - min(optimos), 2)


def sensibilidad(reglas_dict: dict, casos, etiquetas: dict, umbral: float) -> list[tuple[str, int]]:
    """Cuántos casos cambian de clasificación al mover los pesos ±25 %."""
    base = {k: v.indice for k, v in auditar(reglas_dict, casos, "semantico").items()}
    base_clase = {k: v < umbral for k, v in base.items()}
    resultados = []

    escenarios: list[tuple[str, dict]] = [("pesos iguales", {"cumplimiento": 1 / 3, "anclaje": 1 / 3, "tematico": 1 / 3})]
    for componente in ("cumplimiento", "anclaje", "tematico"):
        for factor, etiqueta in ((1.25, "+25%"), (0.75, "-25%")):
            pesos = dict(reglas_dict["fidelidad"]["pesos"])
            pesos[componente] *= factor
            total = sum(pesos.values())
            escenarios.append((f"{componente} {etiqueta}", {k: v / total for k, v in pesos.items()}))

    for nombre, pesos in escenarios:
        variante = copy.deepcopy(reglas_dict)
        variante["fidelidad"]["pesos"] = pesos
        indices = {k: v.indice for k, v in auditar(variante, casos, "semantico").items()}
        cambios = sum(1 for k, v in indices.items() if (v < umbral) != base_clase[k])
        resultados.append((nombre, cambios))
    return resultados


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Calibra el Índice de Fidelidad Analítica")
    p.add_argument("--casos", default=str(RAIZ / "data" / "casos_calibracion.json"))
    p.add_argument("--reglas", default=str(RAIZ / "reglas.json"))
    p.add_argument("--salida", default=str(RAIZ / "salida" / "calibracion.md"))
    args = p.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # la consola de Windows usa cp1252
        sys.stdout.reconfigure(encoding="utf-8")

    reglas_dict, _ = leer_json(args.reglas, EntradaError)
    crudos, _ = leer_json(args.casos, EntradaError)
    etiquetas = {c["id_caso"]: c.get("etiqueta_esperada", "") for c in crudos}
    propositos = {c["id_caso"]: c.get("proposito", "") for c in crudos}
    casos = parsear_casos(crudos)

    semantico = auditar(reglas_dict, casos, "semantico")
    provisional = auditar(reglas_dict, casos, "provisional")
    indices = {k: v.indice for k, v in semantico.items()}

    medidas = barrido(indices, etiquetas)
    optimos, ancho = meseta(medidas)
    umbral_config = reglas_dict["fidelidad"]["umbral_revision"]
    umbral_sugerido = round(sum(optimos) / len(optimos), 2)
    en_meseta = min(optimos) <= umbral_config <= max(optimos)

    lineas: list[str] = ["# Calibración del Índice de Fidelidad Analítica", ""]
    lineas += [f"Conjunto etiquetado: {len(casos)} casos · clase de riesgo: `{RIESGO}`", ""]

    lineas += ["## Casos", "",
               "| Caso | Etiqueta | IFA semántico | IFA provisional | A | A independiente | Estado | Propósito |",
               "|---|---|---|---|---|---|---|---|"]
    for id_caso, v in semantico.items():
        comp = v.fidelidad.get("componentes", {})
        fmt = lambda x: "—" if x is None else f"{x:.2f}"  # noqa: E731
        lineas.append(
            f"| {id_caso} | {etiquetas[id_caso]} | {v.indice:.2f} | {provisional[id_caso].indice:.2f} | "
            f"{fmt(comp.get('A'))} | {fmt(comp.get('A_independiente'))} | {v.etiqueta} | {propositos[id_caso]} |"
        )

    lineas += ["", "## Barrido de umbrales", "",
               "| Umbral | VP | FP | VN | FN | Precisión | Recall | F1 |", "|---|---|---|---|---|---|---|---|"]
    for m in medidas:
        marca = " **←**" if m.umbral == umbral_config else ""
        lineas.append(
            f"| {m.umbral:.2f}{marca} | {m.vp} | {m.fp} | {m.vn} | {m.fn} | "
            f"{m.precision:.2f} | {m.recall:.2f} | {m.f1:.2f} |"
        )

    mejor_f1 = max(m.f1 for m in medidas)
    lineas += ["", "## Selección del umbral", "",
               f"- F1 máximo alcanzado: **{mejor_f1:.2f}**",
               f"- Meseta óptima: **[{min(optimos):.2f}, {max(optimos):.2f}]** (ancho {ancho:.2f})",
               f"- Centro de la meseta: **{umbral_sugerido:.2f}**",
               f"- `umbral_revision` configurado: **{umbral_config:.2f}** "
               f"({'dentro' if en_meseta else 'FUERA'} de la meseta)",
               "",
               "Criterio: se maximiza F1 sobre la clase de riesgo y, ante empate, se privilegia el "
               "*recall* (un falso negativo cuesta más que una revisión humana de más).",
               "",
               "> 11 casos son una prueba de humo del comportamiento de la métrica, no una validación "
               "estadística. La validación real exige etiquetado humano de cientos de interacciones."]

    ganados = [k for k in semantico if (provisional[k].indice < umbral_config) != (indices[k] < umbral_config)]
    lineas += ["", "## Contraste con la línea base", "",
               f"Casos que el evaluador semántico clasifica distinto del provisional: "
               f"**{len(ganados)}** ({', '.join(map(str, ganados)) or 'ninguno'})."]

    lineas += ["", "## Sensibilidad a los pesos (±25 %)", "", "| Escenario | Casos que cambian de clasificación |", "|---|---|"]
    for nombre, cambios in sensibilidad(reglas_dict, casos, etiquetas, umbral_config):
        lineas.append(f"| {nombre} | {cambios} |")

    reporte = "\n".join(lineas) + "\n"
    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(reporte, encoding="utf-8")
    print(reporte)
    print(f"Escrito en {salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
