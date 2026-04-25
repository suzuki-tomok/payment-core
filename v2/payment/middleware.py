"""payment 層の例外を HTTP レスポンスに翻訳する middleware."""

import logging

from django.http import HttpRequest, HttpResponse, JsonResponse

logger = logging.getLogger(__name__)

# 例外クラス → (HTTP status, error code, user message)
# 新しい例外を追加したら、ここに1行追記する.
EXCEPTION_MAP: dict = {}


class ExceptionTranslationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_exception(self, request: HttpRequest, exception: Exception) -> JsonResponse | None:
        for exc_cls, (status, code, message) in EXCEPTION_MAP.items():
            if isinstance(exception, exc_cls):
                logger.warning("Handled business exception: %s", exception)
                return JsonResponse({"error_code": code, "message": message}, status=status)
        return None
