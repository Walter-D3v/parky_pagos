"""
PARKY — Servidor de pagos con FastAPI
======================================
Sirve la app HTML de pagos y expone la API REST.

Endpoints:
  GET  /                          → sirve pagos.html
  GET  /api/ticket/{id}           → info del ticket + monto calculado
  POST /api/ticket/{id}/pagar     → marca ticket como 'pagado'

Instalar:
  pip install fastapi uvicorn psycopg2-binary python-dotenv

Correr:
  python3 servidor_pagos.py
"""

import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

app = FastAPI(title="PARKY Pagos API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HTML_PATH = Path(__file__).parent / "pagos.html"


# =============================================================================
# BD
# =============================================================================
def get_connection():
    return psycopg2.connect(
        host            = os.environ["DB_HOST"],
        port            = int(os.getenv("DB_PORT", "5432")),
        dbname          = os.environ["DB_NAME"],
        user            = os.environ["DB_USER"],
        password        = os.environ["DB_PASSWORD"],
        sslmode         = os.getenv("DB_SSLMODE", "require"),
        connect_timeout = 10,
        options         = "-c statement_timeout=8000",
    )


# =============================================================================
# RUTAS
# =============================================================================
@app.get("/", response_class=HTMLResponse)
async def index():
    if not HTML_PATH.exists():
        raise HTTPException(status_code=404, detail="pagos.html no encontrado")
    return HTMLResponse(content=HTML_PATH.read_text(encoding="utf-8"))


@app.get("/api/ticket/{id_ticket}")
async def obtener_ticket(id_ticket: str):
    conn = None
    try:
        conn = get_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT
                    t.id_ticket,
                    t.estado_ticket,
                    t.tipo_vehiculo,
                    t.tiempo_entrada,
                    t.monto_cobrado,
                    ta.nombre_tarifa,
                    ta.monto AS tarifa_por_hora
                FROM tickets t
                JOIN tarifas ta ON ta.id_tarifa = t.id_tarifa
                WHERE t.id_ticket = %s
                LIMIT 1
            """, (id_ticket,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Ticket no encontrado")

            ticket = dict(row)
            ahora  = datetime.now(timezone.utc)
            te     = ticket["tiempo_entrada"]
            if te.tzinfo is None:
                te = te.replace(tzinfo=timezone.utc)

            horas  = (ahora - te).total_seconds() / 3600
            monto  = round(float(ticket["tarifa_por_hora"]) * max(horas, 0.25), 2)
            estado = ticket["estado_ticket"]

            return {
                "id_ticket":           str(ticket["id_ticket"]),
                "estado":              estado,
                "tipo_vehiculo":       ticket["tipo_vehiculo"],
                "tiempo_entrada":      te.strftime("%d/%m/%Y %H:%M:%S"),
                "tarifa_nombre":       ticket["nombre_tarifa"],
                "tarifa_por_hora":     float(ticket["tarifa_por_hora"]),
                "horas_transcurridas": round(horas, 2),
                "monto_a_pagar":       monto,
                "ya_pagado":           estado in ("pagado", "anulado"),
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()


@app.post("/api/ticket/{id_ticket}/pagar")
async def pagar_ticket(id_ticket: str):
    conn = None
    try:
        conn = get_connection()
        conn.autocommit = False
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT t.estado_ticket, t.tiempo_entrada,
                       ta.monto AS tarifa_por_hora
                FROM tickets t
                JOIN tarifas ta ON ta.id_tarifa = t.id_tarifa
                WHERE t.id_ticket = %s LIMIT 1
            """, (id_ticket,))
            row = cur.fetchone()

            if not row:
                conn.rollback()
                raise HTTPException(status_code=404, detail="Ticket no encontrado")

            if row["estado_ticket"] != "activo":
                conn.rollback()
                raise HTTPException(
                    status_code=400,
                    detail=f"No se puede pagar — estado actual: {row['estado_ticket']}"
                )

            ahora = datetime.now(timezone.utc)
            te    = row["tiempo_entrada"]
            if te.tzinfo is None:
                te = te.replace(tzinfo=timezone.utc)

            horas  = (ahora - te).total_seconds() / 3600
            monto  = round(float(row["tarifa_por_hora"]) * max(horas, 0.25), 2)

            cur.execute("""
                UPDATE tickets
                SET estado_ticket = 'pagado',
                    hora_pago     = now(),
                    monto_cobrado = %s
                WHERE id_ticket = %s AND estado_ticket = 'activo'
                RETURNING id_ticket
            """, (monto, id_ticket))

            if not cur.fetchone():
                conn.rollback()
                raise HTTPException(status_code=500, detail="No se pudo actualizar")

            conn.commit()
            return {"ok": True, "id_ticket": id_ticket,
                    "monto_pagado": monto, "mensaje": "Ticket pagado correctamente"}

    except HTTPException:
        raise
    except Exception as e:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    # Azure App Service inyecta la variable PORT automáticamente.
    # Localmente usa PUERTO_API del .env, o 5000 por defecto.
    puerto = int(os.getenv("PORT", os.getenv("PUERTO_API", "5000")))
    print(f"PARKY Pagos → http://0.0.0.0:{puerto}")
    uvicorn.run("servidor_pagos:app", host="0.0.0.0", port=puerto, reload=False)
