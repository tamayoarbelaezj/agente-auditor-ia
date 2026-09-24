"""Punto de entrada del Agente Auditor (Agent A).

Equivalente a ``python -m auditor``, para poder ejecutar el proyecto con un
archivo visible en la raíz:

    python main.py
    python main.py --casos data/casos.json --reglas reglas.json
    python main.py --comparar

Sin argumentos usa `data/casos.json` y `reglas.json`, imprime el diagnóstico de
cada caso y escribe los reportes en `salida/`.
"""

from __future__ import annotations

import sys

from auditor.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
