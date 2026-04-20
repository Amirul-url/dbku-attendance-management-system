from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static


# Redirect homepage → login page
def home_redirect(request):
    return redirect('/login-page/')


urlpatterns = [
    path('admin/', admin.site.urls),

    # homepage redirect
    path('', home_redirect),

    # API routes
    path('api/employees/', include('employees.urls')),

    # Frontend pages (login, dashboard, etc.)
    path('', include('employees.urls')),
]

# 🔥 IMPORTANT: serve MEDIA in production (for QR, images, etc.)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)