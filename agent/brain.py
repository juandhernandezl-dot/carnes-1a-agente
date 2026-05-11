# agent/brain.py — Cerebro del agente con tool use de Claude
"""
Lógica de IA del agente. Lee el system prompt de prompts.yaml y
genera respuestas usando Claude con herramientas conectadas a Firestore.
"""

import os
import yaml
import logging
from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from agent import firestore as fs

load_dotenv()
logger = logging.getLogger("agentkit")

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── Herramientas que Claude puede invocar ────────────────────────────────────
HERRAMIENTAS = [
    {
        "name": "consultar_productos",
        "description": (
            "Consulta el inventario REAL y en tiempo real de Carnes 1A. "
            "Úsala cuando el cliente pregunte qué hay disponible, precios, cortes o stock. "
            "Los datos vienen directamente de la base de datos del negocio."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "categoria": {
                    "type": "string",
                    "description": "Filtrar por categoría. Omitir para ver todo.",
                    "enum": ["res", "cerdo", "pollo", "embutidos", "otros"]
                }
            },
            "required": []
        }
    },
    {
        "name": "crear_pedido",
        "description": (
            "Registra un pedido confirmado en el sistema de Carnes 1A. "
            "Úsala SOLO cuando el cliente haya dicho explícitamente qué quiere pedir y cómo lo recibirá. "
            "El pedido aparecerá inmediatamente en el panel de la carnicería."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_cliente": {
                    "type": "string",
                    "description": "Nombre del cliente"
                },
                "items": {
                    "type": "array",
                    "description": "Productos del pedido",
                    "items": {
                        "type": "object",
                        "properties": {
                            "producto": {"type": "string", "description": "Nombre del producto"},
                            "cantidad": {"type": "number", "description": "Cantidad"},
                            "unidad":   {"type": "string", "description": "kg, libra o unidad", "default": "kg"}
                        },
                        "required": ["producto", "cantidad"]
                    }
                },
                "tipo_entrega": {
                    "type": "string",
                    "enum": ["domicilio", "presencial"],
                    "description": "Cómo recibirá el pedido el cliente"
                },
                "direccion": {
                    "type": "string",
                    "description": "Dirección de entrega (solo si es domicilio)"
                }
            },
            "required": ["items", "tipo_entrega"]
        }
    },
    {
        "name": "identificar_cliente",
        "description": (
            "Verifica si el cliente es frecuente en Carnes 1A buscando su teléfono en la base de datos. "
            "Úsala al inicio de la conversación para personalizar el saludo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "telefono": {
                    "type": "string",
                    "description": "Número de teléfono del cliente (con código de país)"
                }
            },
            "required": ["telefono"]
        }
    }
]


# ── Ejecutor de herramientas ─────────────────────────────────────────────────

async def _ejecutar_herramienta(nombre: str, inputs: dict, telefono: str) -> str:
    if nombre == "consultar_productos":
        productos = await fs.obtener_productos(inputs.get("categoria"))
        if not productos:
            return "No hay productos disponibles en este momento."
        lineas = [
            f"• *{p['name']}* — ${p['price']:,.0f}/{p['unit']}  ({p['stock']} {p['unit']} disponibles)"
            for p in productos
        ]
        return "Inventario actual:\n" + "\n".join(lineas)

    elif nombre == "crear_pedido":
        order_number = await fs.crear_pedido(
            telefono=telefono,
            nombre_cliente=inputs.get("nombre_cliente", "Cliente WhatsApp"),
            items=inputs.get("items", []),
            tipo_entrega=inputs.get("tipo_entrega", "presencial"),
            direccion=inputs.get("direccion")
        )
        if order_number in ("SIN_FIRESTORE", "ERROR"):
            return "Hubo un problema al registrar el pedido. Por favor intenta de nuevo."
        return f"Pedido registrado con número {order_number}. El equipo de Carnes 1A ya lo ve en su panel."

    elif nombre == "identificar_cliente":
        cliente = await fs.buscar_cliente(inputs.get("telefono", telefono))
        if cliente:
            pedidos = cliente.get("totalOrders", 0)
            return f"Cliente frecuente: {cliente['name']} — {pedidos} pedido(s) anteriores."
        return "Cliente nuevo (primera vez en Carnes 1A)."

    return f"Herramienta '{nombre}' no reconocida."


# ── Configuración desde YAML ─────────────────────────────────────────────────

def cargar_config_prompts() -> dict:
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return {}


def cargar_system_prompt() -> str:
    config = cargar_config_prompts()
    return config.get("system_prompt", "Eres un asistente de Carnes 1A. Responde en español.")


def obtener_mensaje_error() -> str:
    config = cargar_config_prompts()
    return config.get("error_message", "Lo siento, estoy teniendo problemas técnicos. Intenta de nuevo en unos minutos.")


def obtener_mensaje_fallback() -> str:
    config = cargar_config_prompts()
    return config.get("fallback_message", "Disculpa, no entendí tu mensaje. ¿Podrías reformularlo?")


# ── Generación de respuesta con bucle agentico ───────────────────────────────

async def generar_respuesta(mensaje: str, historial: list[dict], telefono: str = "") -> str:
    """
    Genera una respuesta usando Claude con tool use.
    Claude puede consultar el inventario real y crear pedidos en Firestore.
    """
    if not mensaje or len(mensaje.strip()) < 2:
        return obtener_mensaje_fallback()

    system_prompt = cargar_system_prompt()
    mensajes = [{"role": m["role"], "content": m["content"]} for m in historial]
    mensajes.append({"role": "user", "content": mensaje})

    for _ in range(5):  # máximo 5 rondas de tool use
        try:
            response = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                system=system_prompt,
                tools=HERRAMIENTAS,
                messages=mensajes
            )
        except Exception as e:
            logger.error(f"Error Claude API: {e}")
            return obtener_mensaje_error()

        if response.stop_reason == "end_turn":
            texto = next(
                (b.text for b in response.content if hasattr(b, "text")),
                obtener_mensaje_fallback()
            )
            logger.info(f"Respuesta ({response.usage.input_tokens} in / {response.usage.output_tokens} out)")
            return texto

        if response.stop_reason == "tool_use":
            mensajes.append({"role": "assistant", "content": response.content})
            resultados = []
            for bloque in response.content:
                if bloque.type == "tool_use":
                    logger.info(f"Tool use: {bloque.name}({bloque.input})")
                    resultado = await _ejecutar_herramienta(bloque.name, bloque.input, telefono)
                    logger.info(f"Tool result: {resultado[:100]}")
                    resultados.append({
                        "type":        "tool_result",
                        "tool_use_id": bloque.id,
                        "content":     resultado
                    })
            mensajes.append({"role": "user", "content": resultados})
            continue

        break

    return obtener_mensaje_error()
