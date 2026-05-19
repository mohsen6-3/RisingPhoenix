from django.urls import path

from . import views

app_name = 'invitation'

urlpatterns = [
    path('send/', views.send_invitation_view, name='send_invitation_view'),
]
