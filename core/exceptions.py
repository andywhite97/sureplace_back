from rest_framework.views import exception_handler

CODE_BY_STATUS = {
    400: "validation_error",
    401: "authentication_required",
    403: "permission_denied",
    404: "not_found",
    409: "conflict",
    429: "throttled",
}


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return response
    request = context.get("request")
    details = response.data
    message = "The request could not be completed."
    if isinstance(details, dict) and set(details) == {"detail"}:
        message = str(details["detail"])
    elif isinstance(details, dict):
        field_messages = [str(value[0] if isinstance(value, list) else value) for value in details.values() if value]
        if field_messages:
            message = field_messages[0]
    elif isinstance(details, list) and details:
        message = str(details[0])
    response.data = {
        "code": getattr(exc, "default_code", None) or CODE_BY_STATUS.get(response.status_code, "request_error"),
        "message": message,
        "errors": details,
        "request_id": getattr(request, "request_id", None),
    }
    return response
