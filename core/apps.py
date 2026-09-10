from django.apps import AppConfig
from django.db.backends.signals import connection_created


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        connection_created.connect(log_connection_created, dispatch_uid="sureplace_db_connection_timing")


def log_connection_created(sender, connection, **kwargs):
    print(
        f"sureplace_startup stage=db_connection alias={connection.alias} vendor={connection.vendor}",
        flush=True,
    )
