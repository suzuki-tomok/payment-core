"""URL configuration for v3 project."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("payment/", include("payment.urls")),
    path("demo/", include("demo.urls")),
]
