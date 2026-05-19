from django.contrib.auth.models import User
from django.db import models

from progress.models import Contract


class Dispute(models.Model):
    class Reason(models.TextChoices):
        QUALITY          = 'quality',   'Quality Issue'
        TIMELINE         = 'timeline',  'Missed Timeline'
        MISCOMMUNICATION = 'miscomm',   'Miscommunication'
        PAYMENT          = 'payment',   'Payment Issue'
        OTHER            = 'other',     'Other'

    class Status(models.TextChoices):
        OPEN      = 'open',      'Open'
        IN_REVIEW = 'in_review', 'In Review'
        RESOLVED  = 'resolved',  'Resolved'
        DISMISSED = 'dismissed', 'Dismissed'

    contract        = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name='disputes')
    opened_by       = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name='disputes_opened')
    reason          = models.CharField(max_length=20, choices=Reason.choices)
    description     = models.TextField()
    status          = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    resolution_note = models.TextField(blank=True)
    resolved_by     = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='disputes_resolved')
    resolved_at     = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Dispute #{self.id} on contract #{self.contract_id} ({self.status})'

    @property
    def is_open(self):
        return self.status in (self.Status.OPEN, self.Status.IN_REVIEW)

    def other_party(self, user):
        if user == self.contract.requester:
            return self.contract.artisan
        if user == self.contract.artisan:
            return self.contract.requester
        return None

    def involves(self, user):
        return user == self.contract.requester or user == self.contract.artisan


class DisputeMessage(models.Model):
    """A message in a 1:1 staff↔party channel for a dispute.

    `party` identifies which 1:1 channel this message belongs to
    (filter by party=requester for the staff↔requester channel,
    or party=artisan for the staff↔artisan channel).
    `sender` is the actual author — either the party or any staff user.
    """
    dispute    = models.ForeignKey(Dispute, on_delete=models.CASCADE, related_name='messages')
    party      = models.ForeignKey(User, on_delete=models.CASCADE, related_name='dispute_thread_party_in')
    sender     = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_dispute_messages')
    body       = models.TextField()
    image      = models.ImageField(upload_to='images/disputes/', blank=True, null=True)
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f'DisputeMessage #{self.id} by {self.sender.username} in dispute #{self.dispute_id}'
