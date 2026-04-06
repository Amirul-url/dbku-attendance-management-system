from django.contrib import admin
from django.urls import path, include
from employees.views import register_page
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', register_page),
    path('api/employees/', include('employees.urls')),
    path('', include('employees.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)