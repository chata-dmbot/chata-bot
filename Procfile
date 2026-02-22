web: gunicorn app:app --bind 0.0.0.0:$PORT --workers ${WEB_CONCURRENCY:-3} --worker-class gthread --threads ${WEB_THREADS:-4} --timeout 60 --graceful-timeout 30 --keep-alive 5 --max-requests 2000 --max-requests-jitter 200
worker: rq worker chata-webhooks --url ${REDIS_URL}
