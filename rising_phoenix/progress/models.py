from django.conf import settings
from django.db import models
from django.utils import timezone


class Contract(models.Model):
    class Status(models.TextChoices):
        PENDING_REQUESTER = 'pending_requester', 'Pending Requester Acceptance'
        PENDING_ARTISAN = 'pending_artisan', 'Pending Artisan Acceptance'
        IN_PROGRESS           = 'in_progress',          'In Progress'
        COMPLETION_REQUESTED  = 'completion_requested', 'Completion Requested'
        COMPLETED             = 'completed',            'Completed'
        CANCELED = 'canceled', 'Canceled'


    proposal     = models.OneToOneField(
        'proposal.Proposal',
        on_delete=models.CASCADE,
        related_name='contract',
    )
    status       = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING_ARTISAN)
    requester_accepted_at = models.DateTimeField(null=True, blank=True)
    artisan_accepted_at = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    # Set when requester confirms completion — escrow/reviews hook here
    completed_at = models.DateTimeField(null=True, blank=True)
    earnings_recorded = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Contract for '{self.proposal.request.title}'"

    @property
    def is_in_progress(self):
        return self.status == self.Status.IN_PROGRESS

    @property
    def is_completion_requested(self):
        return self.status == self.Status.COMPLETION_REQUESTED

    @property
    def is_completed(self):
        return self.status == self.Status.COMPLETED

    @property
    def artisan(self):
        return self.proposal.artisan

    @property
    def requester(self):
        return self.proposal.request.requester

    @property
    def has_open_dispute(self):
        from dispute.models import Dispute
        return self.disputes.filter(
            status__in=[Dispute.Status.OPEN, Dispute.Status.IN_REVIEW]
        ).exists()


class ProgressUpdate(models.Model):
    contract   = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='updates')
    body       = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Update on {self.contract} at {self.created_at:%Y-%m-%d}"


class ProgressImage(models.Model):
    update      = models.ForeignKey(ProgressUpdate, on_delete=models.CASCADE, related_name='images')
    image       = models.ImageField(upload_to='images/progress/')
    caption     = models.CharField(max_length=160, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return f"Image for update #{self.update_id}"


class ProgressComment(models.Model):
    update     = models.ForeignKey(ProgressUpdate, on_delete=models.CASCADE, related_name='comments')
    author     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='progress_comments')
    body       = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.author.username} on update #{self.update_id}"


class ProgressCommentImage(models.Model):
    comment     = models.ForeignKey(ProgressComment, on_delete=models.CASCADE, related_name='images')
    image       = models.ImageField(upload_to='images/progress_comments/')
    caption     = models.CharField(max_length=160, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return f"Image for comment #{self.comment_id}"


class ContractEvent(models.Model):
    class EventType(models.TextChoices):
        COMPLETION_REQUESTED = 'completion_requested', 'Marked as Complete'
        COMPLETION_REJECTED  = 'completion_rejected',  'Sent Back'
        COMPLETED            = 'completed',            'Confirmed Complete'

    contract   = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    actor      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='contract_events')
    message    = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"{self.get_event_type_display()} on {self.contract} by {self.actor.username}"


class ContractEventImage(models.Model):
    event       = models.ForeignKey(ContractEvent, on_delete=models.CASCADE, related_name='images')
    image       = models.ImageField(upload_to='images/progress_events/')
    caption     = models.CharField(max_length=160, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']

    def __str__(self):
        return f"Image for event #{self.event_id}"
