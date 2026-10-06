#!/usr/bin/env bash
# Render runs this on every deploy.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate
# Creates the first login from DJANGO_SUPERUSER_* env vars; skipped if it already exists.
python manage.py createsuperuser --no-input || true
