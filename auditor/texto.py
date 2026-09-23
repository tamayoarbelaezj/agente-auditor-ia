"""Similitud léxica sin dependencias ni corpus.

Coseno de frecuencias de término (TF), **sin IDF**: así el puntaje de un caso no
depende de con qué otros casos se procesó, que es un requisito de auditoría.
La especificación del tokenizador está fijada aquí para que los valores sean
reproducibles entre corridas y entre máquinas.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable

_NO_ALFANUMERICO = re.compile(r"[^a-z0-9]+")


def tokenizar(texto_normalizado: str, stopwords: Iterable[str] = (), min_len: int = 3) -> Counter[str]:
    """Tokeniza texto ya normalizado (minúsculas y sin tildes).

    Todo lo que no sea ``[a-z0-9]`` separa tokens, de modo que "$1,200" produce
    "1" y "200", y "sarlaft/aml" produce "sarlaft" y "aml". Se descartan los
    tokens más cortos que ``min_len`` y los de ``stopwords``.
    """
    vetadas = set(stopwords)
    tokens = (t for t in _NO_ALFANUMERICO.split(texto_normalizado) if t)
    return Counter(t for t in tokens if len(t) >= min_len and t not in vetadas)


def coseno_tf(a: Counter[str], b: Counter[str]) -> float:
    """Coseno entre dos vectores de frecuencias; 0.0 si alguno está vacío."""
    if not a or not b:
        return 0.0
    comunes = a.keys() & b.keys()
    producto = sum(a[t] * b[t] for t in comunes)
    if not producto:
        return 0.0
    norma_a = math.sqrt(sum(v * v for v in a.values()))
    norma_b = math.sqrt(sum(v * v for v in b.values()))
    return producto / (norma_a * norma_b)
