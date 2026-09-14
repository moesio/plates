#!/bin/sh
export FLASK_APP=webapp/webapp.py
flask db upgrade
exec gunicorn -b 0.0.0.0:9009 -w "${GUNICORN_WORKERS:-1}" --threads "${GUNICORN_THREADS:-16}" webapp.webapp:app
