import os
from celery import Celery

celery = Celery("adatdusito", broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"), backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
celery.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"], broker_connection_retry_on_startup=True)

@celery.task(name="infra.ping")
def ping():
    return "pong"
