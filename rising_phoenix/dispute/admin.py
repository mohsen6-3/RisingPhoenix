from django.contrib import admin

from .models import Dispute, DisputeMessage


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ('id', 'contract', 'opened_by', 'reason', 'status', 'created_at', 'resolved_at')
    list_filter = ('status', 'reason')
    search_fields = ('description', 'resolution_note', 'opened_by__username')
    raw_id_fields = ('contract', 'opened_by', 'resolved_by')


@admin.register(DisputeMessage)
class DisputeMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'dispute', 'party', 'sender', 'created_at', 'is_read')
    list_filter = ('is_read',)
    search_fields = ('body', 'sender__username')
    raw_id_fields = ('dispute', 'party', 'sender')
