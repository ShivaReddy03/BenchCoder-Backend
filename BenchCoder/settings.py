"""
Django settings for BenchCoder project.
"""
import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get('SECRET_KEY', 'your-secret-key-here')
DEBUG = os.environ.get('DEBUG', 'True').lower() in {'1', 'true', 'yes', 'on'}
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'users',
    'problems',
    'submissions',
    'judge',
    'hints',
    'solutions',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'BenchCoder.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'BenchCoder.wsgi.application'

use_postgres = os.environ.get('USE_POSTGRES', '').lower() in {'1', 'true', 'yes', 'on'}
database_url = os.environ.get('DATABASE_URL') if use_postgres else None

if database_url:
    DATABASES = {
        'default': dj_database_url.config(default=database_url, conn_max_age=60, conn_health_checks=True, ssl_require=False)
    }
    DATABASES['default'].setdefault('OPTIONS', {}).update({
        'connect_timeout': 10, 'keepalives': 1, 'keepalives_idle': 15,
        'keepalives_interval': 5, 'keepalives_count': 3,
    })
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=7),
}

CORS_ALLOWED_ORIGINS = [
    'http://localhost:8080',
    'http://127.0.0.1:8080',
    'http://localhost:5173',
    'http://127.0.0.1:5173',
]

AUTH_USER_MODEL = 'users.User'

CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/0')
CELERY_RESULT_BACKEND = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_SOFT_TIME_LIMIT = 240
CELERY_TASK_MAX_RETRIES = 3
CELERY_TASK_RETRY_DELAY = 30

# Fail enqueueing promptly; accepted jobs remain owned by the worker.
CELERY_BROKER_CONNECTION_TIMEOUT = 3
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_BROKER_TRANSPORT_OPTIONS = {
    'socket_connect_timeout': 3,
    'socket_timeout': 3,
    'visibility_timeout': 600,
}
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_CONCURRENCY = 2

# Optional AI assistance: never expose the API key to the browser.
AI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
AI_HINT_MODEL = os.environ.get('AI_HINT_MODEL', 'gpt-4.1-mini')
AI_SOLUTION_MODEL = os.environ.get('AI_SOLUTION_MODEL', 'gpt-4.1-mini')
AI_SOLUTIONS_DAILY_LIMIT = int(os.environ.get('AI_SOLUTIONS_DAILY_LIMIT', '10'))
AI_SOLUTIONS_GLOBAL_DAILY_LIMIT = int(os.environ.get('AI_SOLUTIONS_GLOBAL_DAILY_LIMIT', '100'))
AI_EMBEDDING_MODEL = os.environ.get('AI_EMBEDDING_MODEL', 'text-embedding-3-small')
AI_HINTS_DAILY_LIMIT = int(os.environ.get('AI_HINTS_DAILY_LIMIT', '20'))
AI_HINTS_GLOBAL_DAILY_LIMIT = int(os.environ.get('AI_HINTS_GLOBAL_DAILY_LIMIT', '200'))

AI_HINTS_SIMILARITY_THRESHOLD = float(os.environ.get('AI_HINTS_SIMILARITY_THRESHOLD', '0.25'))

# Pinecone is optional; explicit mode prevents silently falling back on remote failures.
AI_RETRIEVAL_BACKEND = os.environ.get('AI_RETRIEVAL_BACKEND', 'local').lower()
PINECONE_API_KEY = os.environ.get('PINECONE_API_KEY', '')
PINECONE_INDEX_HOST = os.environ.get('PINECONE_INDEX_HOST', '')
PINECONE_NAMESPACE = os.environ.get('PINECONE_NAMESPACE', 'benchcoder-knowledge-v1')
PINECONE_EMBEDDING_FIELD = os.environ.get('PINECONE_EMBEDDING_FIELD', 'chunk_text')
PINECONE_EMBEDDING_MODEL = os.environ.get('PINECONE_EMBEDDING_MODEL', 'text-embedding-3-small')
