from django.contrib import admin
from django.urls import include, path

from payments.views import export_all

urlpatterns = [
    path("admin/export-all/", export_all, name="export_all"),
    path("admin/", admin.site.urls),
    path("", include("payments.urls")),
]
