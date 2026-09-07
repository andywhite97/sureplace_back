import logging
import time
import uuid

logger = logging.getLogger("sureplace.request")


class RequestIDMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-ID", "")
        try:
            request_id = str(uuid.UUID(incoming))
        except (ValueError, TypeError, AttributeError):
            request_id = str(uuid.uuid4())
        request.request_id = request_id
        started = time.monotonic()
        try:
            response = self.get_response(request)
        except Exception:
            logger.exception("unhandled request_id=%s method=%s path=%s", request_id, request.method, request.path)
            raise
        response["X-Request-ID"] = request_id
        user_id = getattr(getattr(request, "user", None), "id", None)
        logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%.2f user_id=%s",
            request_id,
            request.method,
            request.path,
            response.status_code,
            (time.monotonic() - started) * 1000,
            user_id or "anonymous",
        )
        return response
