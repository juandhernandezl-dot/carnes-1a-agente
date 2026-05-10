# agent/tools.py — Herramientas del agente Carnes 1A
# Generado por AgentKit

"""
Herramientas específicas del negocio Carnes 1A.
Incluye funciones para FAQ, consulta de productos y toma de pedidos.
"""

import os
import yaml
import logging
from datetime import datetime

logger = logging.getLogger("agentkit")

# Productos disponibles en Carnes 1A
PRODUCTOS = [
    "Carne molida",
    "Costilla",
    "Pechuga",
    "Cerdo",
    "Chorizo",
    "Pollo entero",
]

# FAQ frecuentes
FAQ = {
    "domicilio": "¡Claro que sí! Manejamos domicilios. Cuéntame qué necesitas y coordinamos la entrega 🛵",
    "cortes": f"Hoy tenemos disponible: {', '.join(PRODUCTOS)}. ¿Qué te llevo?",
    "nequi": "¡Sí! Aceptamos Nequi, efectivo y otros medios de pago. Sin problema 😊",
    "tiempo domicilio": "Depende del sector, pero normalmente entre 30 y 60 minutos. Te confirmamos cuando sepamos tu dirección.",
}


def cargar_info_negocio() -> dict:
    """Carga la información del negocio desde business.yaml."""
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("config/business.yaml no encontrado")
        return {}


def obtener_horario() -> dict:
    """Retorna el horario de atención del negocio."""
    info = cargar_info_negocio()
    horario = info.get("negocio", {}).get("horario", "Lunes a Domingos de 4am a 2pm")
    hora_actual = datetime.now().hour
    # Abierto entre las 4am (4) y las 2pm (14)
    esta_abierto = 4 <= hora_actual < 14
    return {
        "horario": horario,
        "esta_abierto": esta_abierto,
    }


def obtener_productos() -> list[str]:
    """Retorna la lista de productos disponibles."""
    return PRODUCTOS


def responder_faq(consulta: str) -> str | None:
    """
    Busca una respuesta en las preguntas frecuentes.
    Retorna la respuesta si encuentra coincidencia, o None si no.
    """
    consulta_lower = consulta.lower()
    for clave, respuesta in FAQ.items():
        if clave in consulta_lower:
            return respuesta
    return None


# ── Toma de pedidos ──────────────────────────────────────────

# Pedidos en progreso por número de teléfono (en memoria — se pierde al reiniciar)
# En producción se debería persistir en la base de datos
_pedidos_en_progreso: dict[str, dict] = {}


def iniciar_pedido(telefono: str) -> dict:
    """Inicia un pedido nuevo para un número de teléfono."""
    _pedidos_en_progreso[telefono] = {
        "productos": [],
        "tipo": None,          # "local" o "domicilio"
        "direccion": None,
        "estado": "en_progreso",
        "timestamp": datetime.utcnow().isoformat(),
    }
    return _pedidos_en_progreso[telefono]


def agregar_al_pedido(telefono: str, producto: str, cantidad: int = 1) -> bool:
    """Agrega un producto al pedido en progreso. Retorna True si fue exitoso."""
    # Verificar que el producto existe
    producto_valido = next(
        (p for p in PRODUCTOS if p.lower() in producto.lower()),
        None
    )
    if not producto_valido:
        return False

    if telefono not in _pedidos_en_progreso:
        iniciar_pedido(telefono)

    _pedidos_en_progreso[telefono]["productos"].append({
        "producto": producto_valido,
        "cantidad": cantidad,
    })
    return True


def ver_pedido(telefono: str) -> dict | None:
    """Retorna el pedido en progreso de un cliente, o None si no hay."""
    return _pedidos_en_progreso.get(telefono)


def confirmar_pedido(telefono: str, tipo: str, direccion: str | None = None) -> str:
    """
    Confirma el pedido de un cliente.

    Args:
        telefono: Número del cliente
        tipo: "local" o "domicilio"
        direccion: Dirección de entrega si es domicilio

    Returns:
        Resumen del pedido confirmado
    """
    if telefono not in _pedidos_en_progreso:
        return "No tienes un pedido en progreso."

    pedido = _pedidos_en_progreso[telefono]
    pedido["tipo"] = tipo
    pedido["direccion"] = direccion
    pedido["estado"] = "confirmado"

    # Construir resumen
    items = "\n".join(
        f"  - {item['cantidad']}x {item['producto']}"
        for item in pedido["productos"]
    )
    entrega = f"Domicilio a: {direccion}" if tipo == "domicilio" else "Recoge en el local"

    resumen = (
        f"✅ Pedido confirmado:\n{items}\n"
        f"📦 {entrega}\n"
        "En breve te contactamos para coordinar el pago y la entrega."
    )

    # Limpiar pedido en progreso
    del _pedidos_en_progreso[telefono]
    return resumen


def cancelar_pedido(telefono: str) -> bool:
    """Cancela el pedido en progreso. Retorna True si había uno."""
    if telefono in _pedidos_en_progreso:
        del _pedidos_en_progreso[telefono]
        return True
    return False
