"""
URL configuration for rising_phoenix project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from . import settings
from main import views as main_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('i18n/', include('django.conf.urls.i18n')),
    path('', include('main.urls')),
    # Backward-compatible aliases for plain (non-namespaced) reverses.
    path('about-us/', main_views.about_us_view, name='about_us_view'),
    path('members/', main_views.members_view, name='members_view'),
    path('terms/', main_views.terms_view, name='terms_view'),
    path('account/', include('account.urls')),
    path('staff/', include('staff.urls')),
    path('workshop/', include('workshop.urls')),
    path('requests/', include('request.urls')),
    path('payment/', include('payment.urls')),
    path('proposals/', include('proposal.urls')),
    path('message/', include('message.urls')),
    path('progress/', include('progress.urls')),
    path('notifications/', include('notification.urls')),
    path('invitations/', include('invitation.urls')),
    path('disputes/', include('dispute.urls')),
] + static(settings.MEDIA_URL, document_root = settings.MEDIA_ROOT)
