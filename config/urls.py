from django.contrib import admin
from django.urls import path, include, re_path
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve


def home_redirect(request):
    return redirect("/login-page/")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", home_redirect),
    path("api/employees/", include("employees.urls")),
    path("", include("employees.urls")),
]

# Development
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Production fallback for media files
if not settings.DEBUG:
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]