#!/usr/bin/env bash
set -o errexit

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
# Apply migrations separately at deployment time, never during an image build.
python manage.py collectstatic --no-input
