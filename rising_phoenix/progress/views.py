from decimal import Decimal
import logging
import mimetypes

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from notification.models import Notification
from notification.utils import notify
from rising_phoenix.moderation import image_is_clean, text_is_clean
from .models import Contract, ContractEvent, ContractEventImage, ProgressComment, ProgressCommentImage, ProgressImage, ProgressUpdate
import stripe
from django.db import transaction
from account.models import ArtisanRevenue
from message.models import Message, Conversation
from request.models import Request


stripe.api_key = settings.STRIPE_SECRET_KEY


logger = logging.getLogger(__name__)


def _save_images(model_cls, fk_field, fk_obj, request_files, captions=None):
    """Generic image saver — reads 'images' from FILES, creates model_cls records."""
    max_size_bytes = int(float(getattr(settings, 'REQUEST_IMAGE_MAX_SIZE_MB', 5)) * 1024 * 1024)
    allowed_types = list(getattr(settings, 'REQUEST_IMAGE_ALLOWED_TYPES', ['image/jpeg', 'image/png', 'image/webp', 'image/gif']))
    captions = captions or []
    skipped = []

    for index, image_file in enumerate(request_files.getlist('images')[:5]):
        if image_file.size > max_size_bytes:
            skipped.append(f'"{image_file.name}" exceeds the size limit.')
            continue
        ct = (getattr(image_file, 'content_type', '') or '').lower()
        if not ct or ct == 'application/octet-stream':
            ct = (mimetypes.guess_type(image_file.name)[0] or '').lower()
        if ct not in allowed_types:
            skipped.append(f'"{image_file.name}" is not an accepted image type.')
            continue
        if not image_is_clean(image_file):
            skipped.append(f'"{image_file.name}" was removed: explicit content detected.')
            continue
        try:
            caption = (captions[index] if index < len(captions) else '').strip()[:160]
            if caption and not text_is_clean(caption):
                caption = ''
            model_cls.objects.create(**{fk_field: fk_obj, 'image': image_file, 'caption': caption})
        except Exception:
            logger.exception('Failed to save image "%s"', image_file.name)
            skipped.append(f'"{image_file.name}" could not be saved.')

    return skipped


@login_required
def contract_detail_view(request, contract_id):
    
    contract = get_object_or_404(
        Contract.objects.select_related(
            'proposal__artisan',
            'proposal__request__requester',
            'proposal__request__category',
        ),
        id=contract_id,
    )
    allowed_statuses = (
        Contract.Status.IN_PROGRESS,
        Contract.Status.COMPLETION_REQUESTED,
        Contract.Status.COMPLETED
    )

    if contract.status not in allowed_statuses or not (
        contract.requester_accepted_at and contract.artisan_accepted_at
    ):
        messages.error(request, 'This contract is not active yet. Both parties must accept the contract first.')
        return redirect('main:home_view')

    is_artisan   = request.user == contract.artisan
    is_requester = request.user == contract.requester

    if not (is_artisan or is_requester):
        messages.error(request, 'You do not have access to this project.')
        return redirect('main:home_view')

    updates = list(
        contract.updates
        .prefetch_related('images', 'comments__author', 'comments__images')
        .order_by('created_at')
    )
    events = list(
        contract.events
        .select_related('actor')
        .prefetch_related('images')
        .order_by('created_at')
    )
    timeline = sorted(
        [{'kind': 'update', 'obj': u} for u in updates] +
        [{'kind': 'event',  'obj': e} for e in events],
        key=lambda x: x['obj'].created_at,
    )

    latest_update_id = updates[-1].id if updates else None

    from dispute.models import Dispute
    my_open_dispute = contract.disputes.filter(
        opened_by=request.user,
        status__in=[Dispute.Status.OPEN, Dispute.Status.IN_REVIEW],
    ).first()
    dispute_eligible_status = contract.status in (
        Contract.Status.IN_PROGRESS,
        Contract.Status.COMPLETION_REQUESTED,
    )
    can_raise_dispute = (
        (is_requester or is_artisan)
        and dispute_eligible_status
        and my_open_dispute is None
    )

    return render(request, 'progress/contract_detail.html', {
        'contract': contract,
        'timeline': timeline,
        'is_artisan': is_artisan,
        'is_requester': is_requester,
        'latest_update_id': latest_update_id,
        'can_raise_dispute': can_raise_dispute,
        'my_open_dispute': my_open_dispute,
    })


@login_required
def post_update_view(request, contract_id):
    contract = get_object_or_404(Contract, id=contract_id)

    if request.method != 'POST':
        messages.error(request, 'Invalid action.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    if request.user != contract.artisan:
        messages.error(request, 'Only the artisan can post progress updates.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    if contract.is_completed:
        messages.error(request, 'This project is already completed.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    body = request.POST.get('body', '').strip()
    has_images = bool(request.FILES.getlist('images'))

    if not body and not has_images:
        messages.error(request, 'Please add a message or at least one image.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    if body and not text_is_clean(body):
        messages.error(request, 'Your update contains inappropriate language. Please revise it.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    update = ProgressUpdate.objects.create(contract=contract, body=body)
    captions = request.POST.getlist('image_captions')
    for msg in _save_images(ProgressImage, 'update', update, request.FILES, captions):
        messages.warning(request, f'Image skipped: {msg}')
    messages.success(request, 'Progress update posted.')
    notify(
        contract.requester,
        Notification.NotifType.PROGRESS_UPDATE,
        'New progress update on your project',
        body=body[:200] if body else '',
        link=reverse('progress:contract_detail_view', kwargs={'contract_id': contract_id}),
    )
    return redirect('progress:contract_detail_view', contract_id=contract_id)


@login_required
def add_comment_view(request, update_id):
    update = get_object_or_404(ProgressUpdate.objects.select_related('contract'), id=update_id)
    contract = update.contract

    if request.method != 'POST':
        messages.error(request, 'Invalid action.')
        return redirect('progress:contract_detail_view', contract_id=contract.id)

    if request.user not in (contract.artisan, contract.requester):
        messages.error(request, 'You do not have access to this project.')
        return redirect('main:home_view')

    if contract.is_completed:
        messages.error(request, 'This project is already completed.')
        return redirect('progress:contract_detail_view', contract_id=contract.id)

    body = request.POST.get('body', '').strip()
    has_images = bool(request.FILES.getlist('images'))

    if not body and not has_images:
        messages.error(request, 'Please add a message or at least one image.')
        return redirect('progress:contract_detail_view', contract_id=contract.id)

    if body and not text_is_clean(body):
        messages.error(request, 'Your feedback contains inappropriate language. Please revise it.')
        return redirect('progress:contract_detail_view', contract_id=contract.id)

    comment = ProgressComment.objects.create(
        update=update,
        author=request.user,
        body=body,
    )
    captions = request.POST.getlist('image_captions')
    for msg in _save_images(ProgressCommentImage, 'comment', comment, request.FILES, captions):
        messages.warning(request, f'Image skipped: {msg}')
    messages.success(request, 'Feedback posted.')
    other_party = contract.artisan if request.user == contract.requester else contract.requester
    notify(
        other_party,
        Notification.NotifType.COMMENT_ADDED,
        'New feedback on your project',
        body=body[:200] if body else '',
        link=reverse('progress:contract_detail_view', kwargs={'contract_id': contract.id}),
    )
    return redirect('progress:contract_detail_view', contract_id=contract.id)


@login_required
def request_completion_view(request, contract_id):
    contract = get_object_or_404(Contract, id=contract_id)

    if request.method != 'POST':
        messages.error(request, 'Invalid action.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    if request.user != contract.artisan:
        messages.error(request, 'Only the artisan can mark a project as complete.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    if not contract.is_in_progress:
        messages.error(request, 'Completion can only be requested while the project is in progress.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    if contract.has_open_dispute:
        messages.error(request, 'This project has an open dispute. Completion actions are paused until staff resolves it.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    body = request.POST.get('body', '').strip()[:5000]
    if body and not text_is_clean(body):
        messages.error(request, 'Your message contains inappropriate language. Please revise it.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    contract.status = Contract.Status.COMPLETION_REQUESTED
    contract.save(update_fields=['status', 'updated_at'])
    event = ContractEvent.objects.create(
        contract=contract,
        event_type=ContractEvent.EventType.COMPLETION_REQUESTED,
        actor=request.user,
        message=body,
    )
    captions = request.POST.getlist('image_captions')
    for msg in _save_images(ContractEventImage, 'event', event, request.FILES, captions):
        messages.warning(request, f'Image skipped: {msg}')
    messages.success(request, 'Completion requested. Waiting for the requester to confirm.')
    notify(
        contract.requester,
        Notification.NotifType.COMPLETION_REQUESTED,
        'Your artisan has marked the project as complete',
        body='Please review the work and confirm or send it back.',
        link=reverse('progress:contract_detail_view', kwargs={'contract_id': contract_id}),
    )
    return redirect('progress:contract_detail_view', contract_id=contract_id)


@login_required
def confirm_completion_view(request, contract_id):
    contract = get_object_or_404(
        Contract.objects.select_related(
            'proposal',
            'proposal__artisan',
            'proposal__request',
        ),
        id=contract_id
    )

    if request.user != contract.requester:
        messages.error(request, 'Only the requester can confirm completion.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    if not contract.is_completion_requested:
        messages.error(request, 'There is no pending completion request.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    if contract.has_open_dispute:
        messages.error(request, 'This project has an open dispute. Confirmation is paused until staff resolves it.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    escrow_payment = getattr(contract, 'escrow_payment', None)
    if not escrow_payment:
        messages.error(request, 'No payment record was found for this contract.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    gross_amount = contract.proposal.price
    platform_fee = Decimal('0.00')   # replace later with your fee logic
    net_amount = gross_amount - platform_fee

    with transaction.atomic():
        contract.status = Contract.Status.COMPLETED
        contract.completed_at = timezone.now()
        contract.save(update_fields=['status', 'completed_at', 'updated_at'])
        
        Conversation.objects.filter(
            proposal__request=contract.proposal.request
        ).update(is_active=False)

        project_request = contract.proposal.request
        if project_request.status != Request.Status.CLOSED:
            project_request.status = Request.Status.CLOSED
            project_request.save(update_fields=['status', 'updated_at'])

        ContractEvent.objects.create(
            contract=contract,
            event_type=ContractEvent.EventType.COMPLETED,
            actor=request.user,
        )

        ArtisanRevenue.objects.get_or_create(
            contract=contract,
            defaults={
                'artisan': contract.artisan,
                'escrow_payment': escrow_payment,
                'amount': gross_amount,
                'platform_fee': platform_fee,
                'net_amount': net_amount,
                'status': ArtisanRevenue.Status.EARNED,
            }
        )

    messages.success(request, 'Project confirmed as complete. Thank you!')

    notify(
        contract.artisan,
        Notification.NotifType.COMPLETION_CONFIRMED,
        'Your project has been confirmed as complete',
        body='Congratulations! The requester has confirmed the work is done.',
        link=reverse('progress:contract_detail_view', kwargs={'contract_id': contract_id}),
    )

    return redirect('progress:contract_detail_view', contract_id=contract_id)

# def confirm_completion_view(request, contract_id):
#     contract = get_object_or_404(
#         Contract.objects.select_related(
#             'proposal',
#             'proposal__request',
#             'proposal__artisan',
#             'escrow_payment',
#         ),
#         id=contract_id
#     )

#     if request.method != 'POST':
#         messages.error(request, 'Invalid action.')
#         return redirect('progress:contract_detail_view', contract_id=contract_id)

#     if request.user != contract.requester:
#         messages.error(request, 'Only the requester can confirm completion.')
#         return redirect('progress:contract_detail_view', contract_id=contract_id)

#     if not contract.is_completion_requested:
#         messages.error(request, 'There is no pending completion request.')
#         return redirect('progress:contract_detail_view', contract_id=contract_id)

#     escrow_payment = getattr(contract, 'escrow_payment', None)
#     if not escrow_payment:
#         messages.error(request, 'No escrow payment was found for this contract.')
#         return redirect('progress:contract_detail_view', contract_id=contract_id)

#     if escrow_payment.captured:
#         messages.info(request, 'This payment has already been captured.')
#         return redirect('progress:contract_detail_view', contract_id=contract_id)

#     try:
#         payment_intent = stripe.PaymentIntent.capture(
#             escrow_payment.stripe_payment_intent_id
#         )
#     except stripe.error.StripeError:
#         messages.error(request, 'Unable to release the escrow payment right now. Please try again.')
#         return redirect('progress:contract_detail_view', contract_id=contract_id)

#     if payment_intent.status != 'succeeded':
#         messages.error(request, f'Payment capture was not completed. Stripe status: {payment_intent.status}')
#         return redirect('progress:contract_detail_view', contract_id=contract_id)

#     with transaction.atomic():
#         escrow_payment.status = 'captured'
#         escrow_payment.captured = True
#         escrow_payment.save(update_fields=['status', 'captured', 'updated_at'])

#         contract.status = Contract.Status.COMPLETED
#         contract.completed_at = timezone.now()
#         contract.save(update_fields=['status', 'completed_at', 'updated_at'])

#         ContractEvent.objects.create(
#             contract=contract,
#             event_type=ContractEvent.EventType.COMPLETED,
#             actor=request.user,
#         )

#     messages.success(request, 'Project confirmed as complete and payment has been released successfully.')

#     notify(
#         contract.artisan,
#         Notification.NotifType.COMPLETION_CONFIRMED,
#         'Your project has been confirmed as complete',
#         body='Congratulations! The requester has confirmed the work is done and the payment has been released.',
#         link=reverse('progress:contract_detail_view', kwargs={'contract_id': contract_id}),
#     )

#     return redirect('progress:contract_detail_view', contract_id=contract_id)



@login_required
def reject_completion_view(request, contract_id):
    contract = get_object_or_404(Contract, id=contract_id)

    if request.method != 'POST':
        messages.error(request, 'Invalid action.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    if request.user != contract.requester:
        messages.error(request, 'Only the requester can reject a completion request.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    if not contract.is_completion_requested:
        messages.error(request, 'There is no pending completion request.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    body = request.POST.get('body', '').strip()[:1000]
    if body and not text_is_clean(body):
        messages.error(request, 'Your message contains inappropriate language. Please revise it.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    contract.status = Contract.Status.IN_PROGRESS
    contract.save(update_fields=['status', 'updated_at'])
    event = ContractEvent.objects.create(
        contract=contract,
        event_type=ContractEvent.EventType.COMPLETION_REJECTED,
        actor=request.user,
        message=body,
    )
    captions = request.POST.getlist('image_captions')
    for msg in _save_images(ContractEventImage, 'event', event, request.FILES, captions):
        messages.warning(request, f'Image skipped: {msg}')
    messages.success(request, 'Sent back. The project is back in progress.')
    notify(
        contract.artisan,
        Notification.NotifType.COMPLETION_REJECTED,
        'Completion request was sent back',
        body=body if body else 'The requester sent the project back for more work.',
        link=reverse('progress:contract_detail_view', kwargs={'contract_id': contract_id}),
    )
    return redirect('progress:contract_detail_view', contract_id=contract_id)
