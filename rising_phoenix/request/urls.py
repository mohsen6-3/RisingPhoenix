from django.urls import path

from . import views

app_name = 'request'

urlpatterns = [
    path('', views.request_list_view, name='request_list_view'),
    path('mine/', views.my_requests_view, name='my_requests_view'),
    path('create/', views.request_create_view, name='request_create_view'),
    path('<int:request_id>/', views.request_detail_view, name='request_detail_view'),
    path('<int:request_id>/edit/', views.request_edit_view, name='request_edit_view'),
    path('<int:request_id>/reopen/', views.reopen_request_view, name='reopen_request_view'),
    path('api/refine-text/', views.refine_request_view, name='refine_request_view'),
    path('api/suggested-artisans/', views.suggested_artisans_view, name='suggested_artisans_view'),
    path('api/my-open-requests/', views.my_open_requests_view, name='my_open_requests_view'),
]