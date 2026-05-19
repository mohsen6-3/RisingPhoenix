from django.conf import settings
from django.db import models


class Invitation(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        VIEWED = 'viewed', 'Viewed'
        PROPOSED = 'proposed', 'Proposed'

    request = models.ForeignKey(
        'request.Request',
        on_delete=models.CASCADE,
        related_name='invitations',
    )
    artisan = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='received_invitations',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    viewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['request', 'artisan'],
                name='unique_request_artisan_invitation',
            ),
        ]

    def __str__(self):
        return f"Invitation: {self.artisan.username} -> '{self.request.title}' ({self.status})"
