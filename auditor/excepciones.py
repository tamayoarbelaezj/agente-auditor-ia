"""Jerarquía de excepciones del auditor."""


class AuditorError(Exception):
    """Error base del Agente Auditor."""


class ConfigError(AuditorError):
    """El archivo de reglas no existe, está mal formado o no pasa la validación."""


class EntradaError(AuditorError):
    """El archivo de casos no existe o no tiene la estructura esperada."""


class CasoInvalidoError(AuditorError):
    """Un caso individual no cumple el esquema mínimo (no detiene el lote)."""
