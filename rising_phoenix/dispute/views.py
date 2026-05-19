import mimetypes

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from notification.models import Notification
from notification.utils import notify
from progress.models import Contract
from rising_phoenix.moderation import image_is_clean, text_is_clean

from .forms import DisputeForm, DisputeMessageForm
from .models import Dispute, DisputeMessage


def _user_is_party(user, contract):
    return user == contract.requester or user == contract.artisan


def _validate_image(image_file):
    """Return (cleaned_image, error_message). Mirrors message app validation."""
    if not image_file:
        return None, None
    allowed_types = list(getattr(settings, 'REQUEST_IMAGE_ALLOWED_TYPES', ['image/jpeg', 'image/png', 'image/webp', 'image/gif']))
    max_size_bytes = int(float(getattr(settings, 'REQUEST_IMAGE_MAX_SIZE_MB', 5)) * 1024 * 1024)

    if image_file.size > max_size_bytes:
        return None, 'Image must be under 5 MB.'

    ct = (getattr(image_file, 'content_type', '') or '').lower()
    if not ct or ct == 'application/octet-stream':
        ct = (mimetypes.guess_type(image_file.name)[0] or '').lower()
    if ct not in allowed_types:
        return None, 'Only JPEG, PNG, WebP, and GIF images are allowed.'

    if not image_is_clean(image_file):
        return None, 'Your image was rejected: explicit content detected.'

    return image_file, None


@login_required
def raise_dispute_view(request: HttpRequest, contract_id: int) -> HttpResponse:
    contract = get_object_or_404(
        Contract.objects.select_related('proposal__artisan', 'proposal__request__requester'),
        id=contract_id,
    )

    if not _user_is_party(request.user, contract):
        messages.error(request, 'You are not part of this project.')
        return redirect('main:home_view')

    eligible_statuses = (Contract.Status.IN_PROGRESS, Contract.Status.COMPLETION_REQUESTED)
    if contract.status not in eligible_statuses:
        messages.error(request, 'A dispute can only be opened on an active project.')
        return redirect('progress:contract_detail_view', contract_id=contract.id)

    existing = contract.disputes.filter(
        opened_by=request.user,
        status__in=[Dispute.Status.OPEN, Dispute.Status.IN_REVIEW],
    ).first()
    if existing:
        messages.warning(request, 'You already have an open dispute on this project.')
        return redirect('dispute:dispute_detail_view', dispute_id=existing.id)

    if request.method == 'POST':
        form = DisputeForm(request.POST)
        if form.is_valid():
            description = form.cleaned_data['description'].strip()
            if not text_is_clean(description):
                messages.error(request, 'Your description contains inappropriate language. Please revise it.')
            else:
                dispute = form.save(commit=False)
                dispute.contract = contract
                dispute.opened_by = request.user
                dispute.save()

                other = dispute.other_party(request.user)
                link = reverse('dispute:dispute_detail_view', kwargs={'dispute_id': dispute.id})
                project_title = contract.proposal.request.title

                if other:
                    notify(
                        other,
                        Notification.NotifType.DISPUTE_RECEIVED,
                        'A dispute has been opened on your project',
                        body=f'{request.user.username} opened a dispute: {dispute.get_reason_display()} — "{project_title}".',
                        link=link,
                    )
                for staff_user in User.objects.filter(is_staff=True):
                    notify(
                        staff_user,
                        Notification.NotifType.DISPUTE_RECEIVED,
                        'New dispute opened',
                        body=f'{request.user.username} opened a dispute on "{project_title}" ({dispute.get_reason_display()}).',
                        link=reverse('staff:dispute_detail_view', kwargs={'dispute_id': dispute.id}),
                    )

                messages.success(request, 'Your dispute has been opened. Our team will review it shortly.')
                return redirect('dispute:dispute_detail_view', dispute_id=dispute.id)
    else:
        form = DisputeForm()

    return render(request, 'dispute/raise_dispute.html', {
        'form': form,
        'contract': contract,
    })


@login_required
def my_disputes_view(request: HttpRequest) -> HttpResponse:
    disputes = (
        Dispute.objects
        .filter(
            Q(contract__proposal__artisan=request.user)
            | Q(contract__proposal__request__requester=request.user)
        )
        .select_related('contract__proposal__request', 'contract__proposal__artisan', 'opened_by')
        .order_by('-created_at')
    )
    return render(request, 'dispute/my_disputes.html', {'disputes': disputes})


@login_required
def dispute_detail_view(request: HttpRequest, dispute_id: int) -> HttpResponse:
    dispute = get_object_or_404(
        Dispute.objects.select_related('contract__proposal__artisan', 'contract__proposal__request__requester'),
        id=dispute_id,
    )

    if not dispute.involves(request.user):
        messages.error(request, 'You do not have access to this dispute.')
        return redirect('main:home_view')

    thread = (
        dispute.messages
        .filter(party=request.user)
        .select_related('sender')
        .order_by('created_at')
    )
    dispute.messages.filter(party=request.user, is_read=False).exclude(sender=request.user).update(is_read=True)

    return render(request, 'dispute/dispute_detail.html', {
        'dispute': dispute,
        'contract': dispute.contract,
        'thread': thread,
        'message_form': DisputeMessageForm(),
        'other_party': dispute.other_party(request.user),
    })


@login_required
@require_POST
def party_send_message_view(request: HttpRequest, dispute_id: int) -> HttpResponse:
    dispute = get_object_or_404(Dispute, id=dispute_id)

    if not dispute.involves(request.user):
        messages.error(request, 'You do not have access to this dispute.')
        return redirect('main:home_view')

    if not dispute.is_open:
        messages.error(request, 'This dispute is already resolved.')
        return redirect('dispute:dispute_detail_view', dispute_id=dispute.id)

    body = (request.POST.get('body') or '').strip()
    image = request.FILES.get('image')

    if not body and not image:
        messages.error(request, 'Please write a message or attach an image.')
        return redirect('dispute:dispute_detail_view', dispute_id=dispute.id)

    if body and not text_is_clean(body):
        messages.error(request, 'Your message contains inappropriate language. Please revise it.')
        return redirect('dispute:dispute_detail_view', dispute_id=dispute.id)

    cleaned_image, image_error = _validate_image(image)
    if image_error:
        messages.error(request, image_error)
        return redirect('dispute:dispute_detail_view', dispute_id=dispute.id)

    DisputeMessage.objects.create(
        dispute=dispute,
        party=request.user,
        sender=request.user,
        body=body,
        image=cleaned_image,
    )

    link_for_staff = reverse('staff:dispute_detail_view', kwargs={'dispute_id': dispute.id})
    for staff_user in User.objects.filter(is_staff=True):
        notify(
            staff_user,
            Notification.NotifType.DISPUTE_MESSAGE_RECEIVED,
            f'New dispute message from {request.user.username}',
            body=body[:120] if body else 'Sent an image',
            link=link_for_staff,
        )

    messages.success(request, 'Message sent.')
    return redirect('dispute:dispute_detail_view', dispute_id=dispute.id)
