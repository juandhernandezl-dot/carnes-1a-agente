# agent/firestore.py — Conexión con Firestore de Carnes 1A
"""
Todas las operaciones contra la base de datos de Carnes 1A.
Usa firebase-admin con asyncio.to_thread para no bloquear el event loop de FastAPI.
"""

import os
import json
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger("agentkit")

_db = None


def _init_firebase():
    """Inicializa firebase-admin una sola vez."""
    global _db
    sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT")
    if not sa_json:
        logger.warning("⚠️  FIREBASE_SERVICE_ACCOUNT no configurada — Firestore deshabilitado")
        return

    try:
        from firebase_admin import credentials, firestore, initialize_app, get_app
        try:
            get_app()
        except ValueError:
            cred = credentials.Certificate(json.loads(sa_json))
            initialize_app(cred)
        _db = firestore.client()
        logger.info("✅ Firestore de Carnes 1A conectado")
    except Exception as e:
        logger.error(f"Error iniciando Firebase: {e}")


_init_firebase()


# ─── Productos ────────────────────────────────────────────────────────────────

async def obtener_productos(categoria: str | None = None) -> list[dict]:
    """Retorna productos activos con stock > 0 desde Firestore."""
    if not _db:
        return []

    def _query():
        from firebase_admin import firestore
        ref = _db.collection("products").where("active", "==", True)
        if categoria:
            ref = ref.where("category", "==", categoria)
        docs = ref.stream()
        resultados = []
        for d in docs:
            data = d.to_dict()
            if (data.get("stock") or 0) > 0:
                resultados.append({
                    "id":       d.id,
                    "name":     data.get("name", ""),
                    "category": data.get("category", ""),
                    "unit":     data.get("unit", "kg"),
                    "stock":    data.get("stock", 0),
                    "price":    data.get("price", 0),
                    "minStock": data.get("minStock", 0),
                })
        return sorted(resultados, key=lambda x: x["name"])

    try:
        return await asyncio.to_thread(_query)
    except Exception as e:
        logger.error(f"Error consultando productos: {e}")
        return []


# ─── Pedidos ─────────────────────────────────────────────────────────────────

async def crear_pedido(
    telefono: str,
    nombre_cliente: str,
    items: list[dict],
    tipo_entrega: str,
    direccion: str | None = None
) -> str:
    """Crea un pedido en Firestore y retorna el orderNumber."""
    if not _db:
        return "SIN_FIRESTORE"

    def _crear():
        from firebase_admin import firestore

        # Generar número de orden
        year = datetime.now().year
        ultimos = list(
            _db.collection("orders")
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .limit(1).stream()
        )
        if ultimos:
            ultimo_num = ultimos[0].to_dict().get("orderNumber", f"ORD-{year}-000")
            try:
                seq = int(ultimo_num.split("-")[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        else:
            seq = 1

        order_number = f"ORD-{year}-{seq:03d}"

        items_doc = [
            {
                "productName": i.get("producto", ""),
                "quantity":    i.get("cantidad", 0),
                "unit":        i.get("unidad", "kg"),
                "price":       0,
                "subtotal":    0,
            }
            for i in items
        ]

        _db.collection("orders").add({
            "orderNumber":  order_number,
            "channel":      "whatsapp",
            "status":       "pendiente",
            "deliveryType": tipo_entrega,
            "customer": {
                "name":    nombre_cliente,
                "phone":   telefono,
                "address": direccion or "",
            },
            "items":    items_doc,
            "total":    0,
            "notes":    "Pedido recibido por WhatsApp",
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })
        return order_number

    try:
        return await asyncio.to_thread(_crear)
    except Exception as e:
        logger.error(f"Error creando pedido: {e}")
        return "ERROR"


# ─── Clientes ─────────────────────────────────────────────────────────────────

async def buscar_cliente(telefono: str) -> dict | None:
    """Busca un cliente frecuente por teléfono."""
    if not _db:
        return None

    def _buscar():
        docs = list(
            _db.collection("customers")
            .where("phone", "==", telefono)
            .limit(1).stream()
        )
        if docs:
            return {"id": docs[0].id, **docs[0].to_dict()}
        return None

    try:
        return await asyncio.to_thread(_buscar)
    except Exception as e:
        logger.error(f"Error buscando cliente: {e}")
        return None
