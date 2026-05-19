from django.contrib import admin

from .models import Invitation


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ['request', 'artisan', 'status', 'created_at', 'viewed_at']
    list_filter = ['status']
    search_fields = ['artisan__username', 'request__title']
    ordering = ['-created_at']
