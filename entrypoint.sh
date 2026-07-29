#!/bin/sh
export FLASK_APP=webapp/webapp.py
flask db upgrade
exec gunicorn -b 0.0.0.0:9009 -w 4 webapp.webapp:app
