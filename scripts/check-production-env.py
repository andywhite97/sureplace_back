"""Validate a production dotenv file without printing secrets or contacting services."""
import sys
from pathlib import Path
from urllib.parse import urlparse


def validate(values):
    errors = []
    required = (
        'SECRET_KEY', 'ALLOWED_HOSTS', 'DATABASE_URL', 'CACHE_URL',
        'CELERY_BROKER_URL', 'CELERY_RESULT_BACKEND', 'CLOUDINARY_CLOUD_NAME',
        'CLOUDINARY_API_KEY', 'CLOUDINARY_API_SECRET', 'BIRD_API_KEY',
        'DEFAULT_FROM_EMAIL', 'FRONTEND_BASE_URL', 'CORS_ALLOWED_ORIGINS',
        'CSRF_TRUSTED_ORIGINS',
    )
    for name in required:
        value = values.get(name, '')
        if not value or any(marker in value.lower() for marker in ('replace-with', 'changeme', '<password>', '<host>')):
            errors.append(f'{name}: supply a real production value')
    for name, expected in {
        'DEBUG': 'false', 'USE_SQLITE': 'false', 'USE_CLOUDINARY': 'true',
        'SECURE_SSL_REDIRECT': 'true', 'SESSION_COOKIE_SECURE': 'true',
        'CSRF_COOKIE_SECURE': 'true', 'CELERY_TASK_ALWAYS_EAGER': 'false',
        'EMAIL_PROVIDER': 'bird', 'EMAIL_DELIVERY_MODE': 'async',
    }.items():
        if values.get(name, '').lower() != expected:
            errors.append(f'{name}: must be {expected}')
    if len(values.get('SECRET_KEY', '')) < 50:
        errors.append('SECRET_KEY: use at least 50 random characters')
    for name in ('DATABASE_URL', 'CACHE_URL', 'CELERY_BROKER_URL', 'CELERY_RESULT_BACKEND'):
        value = values.get(name, '')
        if not value:
            continue
        parsed = urlparse(value)
        schemes = ('postgres', 'postgresql', 'postgis') if name == 'DATABASE_URL' else ('redis', 'rediss')
        if parsed.scheme not in schemes or not parsed.hostname or parsed.hostname in ('localhost', '127.0.0.1'):
            errors.append(f'{name}: use a production database/service URL')
    hosts = values.get('ALLOWED_HOSTS', '').split(',')
    if any(host.strip() in ('*', 'localhost', '127.0.0.1') for host in hosts):
        errors.append('ALLOWED_HOSTS: use explicit production hostnames')
    for name in ('FRONTEND_BASE_URL', 'CORS_ALLOWED_ORIGINS', 'CSRF_TRUSTED_ORIGINS'):
        for origin in filter(None, values.get(name, '').split(',')):
            parsed = urlparse(origin.strip())
            if parsed.scheme != 'https' or not parsed.hostname or parsed.hostname in ('localhost', '127.0.0.1'):
                errors.append(f'{name}: use HTTPS production origins')
    bird_key = values.get('BIRD_API_KEY', '')
    if bird_key and not bird_key.startswith(('bk_us1_', 'bk_eu1_')):
        errors.append('BIRD_API_KEY: use a supported regional Bird key')
    return errors


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / '.env.production'
    if not path.is_file():
        print('Production environment file not found.')
        return 1
    values = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('\"\'')
    errors = validate(values)
    for error in errors:
        print(error)
    if errors:
        print(f'Not ready: {len(errors)} configuration issues. No secrets printed.')
        return 1
    print('Configuration values pass. Run Django deployment checks and staging smoke tests next.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
