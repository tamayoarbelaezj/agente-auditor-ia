"""Agent A: Agente Auditor de decisiones de Agent B (AI Governance, 2.ª línea de defensa)."""

__version__ = "1.0.0"

from .config import Reglas, cargar_reglas
from .entrada import cargar_casos
from .motor import Auditor

__all__ = ["Auditor", "Reglas", "cargar_casos", "cargar_reglas", "__version__"]
