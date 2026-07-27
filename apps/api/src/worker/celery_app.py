"""Celery application for background housing-decision pipeline runs."""

from celery import Celery

from src.config import configure_langsmith_env, settings

configure_langsmith_env()

celery_app = Celery(
    "housing_decision_system",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.timezone = "UTC"
celery_app.conf.enable_utc = True
# Production Linux workers use prefork (default). Windows local uses --pool=solo.
celery_app.conf.worker_prefetch_multiplier = 1

# Ensure task modules are registered when the worker starts.
celery_app.autodiscover_tasks(["src.worker"])
# Explicit import path for `celery -A src.worker.celery_app worker`
celery_app.conf.imports = ("src.worker.tasks",)
