from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static

def home_redirect(request):
    return redirect('/login-page/')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', home_redirect),
    path('api/employees/', include('employees.urls')),
    path('', include('employees.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)