#!/bin/bash
# Azure App Service corre este script al iniciar el contenedor.
# Gunicorn con worker Uvicorn es la combinación recomendada para FastAPI en producción.
pip install -r requirements.txt
gunicorn servidor_pagos:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --workers 2 \
  --timeout 120
