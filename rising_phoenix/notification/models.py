from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()

_NOTIF_TYPES = [
    'proposal_received', 'proposal_accepted', 'proposal_rejected',
    'progress_update', 'comment_added', 'completion_requested',
    'completion_confirmed', 'completion_rejected', 'message_received',
    'report_received', 'report_status_update', 'invitation_received',
    'dispute_received', 'dispute_message_received', 'dispute_status_update',
]


class NotificationPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_preference')

    # Email toggles
    email_proposal_received    = models.BooleanField(default=True)
    email_proposal_accepted    = models.BooleanField(default=True)
    email_proposal_rejected    = models.BooleanField(default=True)
    email_progress_update      = models.BooleanField(default=True)
    email_comment_added        = models.BooleanField(default=True)
    email_completion_requested = models.BooleanField(default=True)
    email_completion_confirmed = models.BooleanField(default=True)
    email_completion_rejected  = models.BooleanField(default=True)
    email_message_received     = models.BooleanField(default=True)
    email_invitation_received  = models.BooleanField(default=True)
    email_dispute_received        = models.BooleanField(default=True)
    email_dispute_message_received = models.BooleanField(default=True)
    email_dispute_status_update    = models.BooleanField(default=True)

    # In-site toggles
    insite_proposal_received    = models.BooleanField(default=True)
    insite_proposal_accepted    = models.BooleanField(default=True)
    insite_proposal_rejected    = models.BooleanField(default=True)
    insite_progress_update      = models.BooleanField(default=True)
    insite_comment_added        = models.BooleanField(default=True)
    insite_completion_requested = models.BooleanField(default=True)
    insite_completion_confirmed = models.BooleanField(default=True)
    insite_completion_rejected  = models.BooleanField(default=True)
    insite_message_received     = models.BooleanField(default=True)
    insite_invitation_received  = models.BooleanField(default=True)
    insite_dispute_received        = models.BooleanField(default=True)
    insite_dispute_message_received = models.BooleanField(default=True)
    insite_dispute_status_update    = models.BooleanField(default=True)

    def wants_email(self, notif_type):
        return getattr(self, f'email_{notif_type}', True)

    def wants_insite(self, notif_type):
        return getattr(self, f'insite_{notif_type}', True)


class Notification(models.Model):
    class NotifType(models.TextChoices):
        PROPOSAL_RECEIVED    = 'proposal_received',    'New Proposal'
        PROPOSAL_ACCEPTED    = 'proposal_accepted',    'Proposal Accepted'
        PROPOSAL_REJECTED    = 'proposal_rejected',    'Proposal Rejected'
        PROGRESS_UPDATE      = 'progress_update',      'Progress Update'
        COMMENT_ADDED        = 'comment_added',        'New Feedback'
        COMPLETION_REQUESTED = 'completion_requested', 'Completion Requested'
        COMPLETION_CONFIRMED = 'completion_confirmed', 'Project Completed'
        COMPLETION_REJECTED  = 'completion_rejected',  'Completion Sent Back'
        MESSAGE_RECEIVED     = 'message_received',     'New Message'
        REPORT_RECEIVED      = 'report_received',      'New Report'
        REPORT_STATUS_UPDATE = 'report_status_update', 'Report Update'
        INVITATION_RECEIVED  = 'invitation_received',  'Project Invitation'
        DISPUTE_RECEIVED         = 'dispute_received',         'New Dispute'
        DISPUTE_MESSAGE_RECEIVED = 'dispute_message_received', 'New Dispute Message'
        DISPUTE_STATUS_UPDATE    = 'dispute_status_update',    'Dispute Update'

    recipient  = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    notif_type = models.CharField(max_length=30, choices=NotifType.choices)
    title      = models.CharField(max_length=200)
    body       = models.CharField(max_length=500, blank=True)
    link       = models.CharField(max_length=500, blank=True)
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.recipient.username} — {self.get_notif_type_display()}'

    @property
    def icon_class(self):
        return {
            'proposal_received':    'bi-envelope-fill',
            'proposal_accepted':    'bi-check-circle-fill',
            'proposal_rejected':    'bi-x-circle-fill',
            'progress_update':      'bi-image',
            'comment_added':        'bi-chat-dots-fill',
            'completion_requested': 'bi-hourglass-split',
            'completion_confirmed': 'bi-trophy-fill',
            'completion_rejected':  'bi-arrow-counterclockwise',
            'message_received':     'bi-chat-fill',
            'report_received':      'bi-flag-fill',
            'report_status_update': 'bi-shield-check',
            'invitation_received':  'bi-person-plus-fill',
            'dispute_received':         'bi-exclamation-octagon-fill',
            'dispute_message_received': 'bi-chat-square-text-fill',
            'dispute_status_update':    'bi-shield-check',
        }.get(self.notif_type, 'bi-bell')

    @property
    def icon_color(self):
        return {
            'proposal_received':    '#1a6fa8',
            'proposal_accepted':    '#1a7a4a',
            'proposal_rejected':    '#8a7a6e',
            'progress_update':      '#c2724f',
            'comment_added':        '#c2724f',
            'completion_requested': '#b07c00',
            'completion_confirmed': '#1a7a4a',
            'completion_rejected':  '#b07c00',
            'message_received':     '#1a6fa8',
            'report_received':      '#c2374f',
            'report_status_update': '#1a7a4a',
            'invitation_received':  '#1a6fa8',
            'dispute_received':         '#c2374f',
            'dispute_message_received': '#c2724f',
            'dispute_status_update':    '#1a7a4a',
        }.get(self.notif_type, '#8a7a6e')
