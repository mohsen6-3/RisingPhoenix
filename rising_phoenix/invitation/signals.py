from django.db.models.signals import post_save
from django.dispatch import receiver

from proposal.models import Proposal

from .models import Invitation


@receiver(post_save, sender=Proposal)
def mark_invitation_proposed(sender, instance, created, **kwargs):
    if not created:
        return
    Invitation.objects.filter(
        request=instance.request,
        artisan=instance.artisan,
        status__in=[Invitation.Status.PENDING, Invitation.Status.VIEWED],
    ).update(status=Invitation.Status.PROPOSED)
