from django.urls import path

from . import views

app_name = 'dispute'


urlpatterns = [
    path('contracts/<int:contract_id>/raise/', views.raise_dispute_view, name='raise_dispute_view'),
    path('mine/', views.my_disputes_view, name='my_disputes_view'),
    path('<int:dispute_id>/', views.dispute_detail_view, name='dispute_detail_view'),
    path('<int:dispute_id>/message/', views.party_send_message_view, name='party_send_message_view'),
]
