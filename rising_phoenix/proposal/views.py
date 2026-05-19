import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from notification.models import Notification
from notification.utils import notify
from rising_phoenix.moderation import image_is_clean, text_is_clean
from request.models import Request
from .forms import ProposalForm
from .models import Proposal, ProposalImage
from progress.models import Contract

logger = logging.getLogger(__name__)


def _is_artisan(user):
    return user.groups.filter(name='artisan').exists()


def _save_proposal_images(proposal, request_files, captions=None):
    max_size_mb = float(getattr(settings, 'REQUEST_IMAGE_MAX_SIZE_MB', 5))
    max_size_bytes = int(max_size_mb * 1024 * 1024)
    allowed_types = list(getattr(settings, 'REQUEST_IMAGE_ALLOWED_TYPES', ['image/jpeg', 'image/png', 'image/webp', 'image/gif']))
    max_count = 5
    captions = captions or []
    skipped = []

    existing_count = proposal.images.count()
    slots_remaining = max(0, max_count - existing_count)
    incoming = request_files.getlist('proposal_images')

    if len(incoming) > slots_remaining:
        overflow = len(incoming) - slots_remaining
        skipped.append(f'{overflow} image(s) skipped — proposals are limited to {max_count} images total.')
        incoming = incoming[:slots_remaining]

    for index, image_file in enumerate(incoming):
        if image_file.size > max_size_bytes:
            skipped.append(f'"{image_file.name}" exceeds the {max_size_mb:.0f} MB size limit.')
            continue
        content_type = getattr(image_file, 'content_type', '') or ''
        if content_type.lower() not in allowed_types:
            skipped.append(f'"{image_file.name}" is not an accepted image type.')
            continue
        if not image_is_clean(image_file):
            skipped.append(f'"{image_file.name}" was removed: explicit content detected.')
            continue
        try:
            caption = (captions[index] if index < len(captions) else '').strip()
            if caption and not text_is_clean(caption):
                caption = ''
            ProposalImage.objects.create(proposal=proposal, image=image_file, caption=caption[:160])
        except Exception:
            logger.exception('Failed to save proposal image "%s"', image_file.name)
            skipped.append(f'"{image_file.name}" could not be saved.')

    return skipped


@login_required
def submit_proposal_view(request, request_id):
    project_request = get_object_or_404(
        Request.objects.select_related('requester', 'category').prefetch_related('images'),
        id=request_id,
    )

    if not _is_artisan(request.user):
        messages.error(request, 'Only artisans can submit proposals.')
        return redirect('request:request_detail_view', request_id=request_id)

    if project_request.requester == request.user:
        messages.error(request, 'You cannot submit a proposal for your own request.')
        return redirect('request:request_detail_view', request_id=request_id)

    if project_request.status not in [Request.Status.OPEN, Request.Status.IN_REVIEW]:
        messages.error(request, 'This request is no longer accepting proposals.')
        return redirect('request:request_detail_view', request_id=request_id)

    existing = Proposal.objects.filter(request=project_request, artisan=request.user).first()
    if existing and existing.status != Proposal.Status.WITHDRAWN:
        messages.info(request, 'You have already submitted a proposal for this request.')
        return redirect('request:request_detail_view', request_id=request_id)

    if request.method == 'POST':
        # Re-use the withdrawn proposal record instead of creating a duplicate
        form = ProposalForm(request.POST, request.FILES, instance=existing if existing else None)
        if form.is_valid():
            try:
                proposal = form.save(commit=False)
                proposal.request = project_request
                proposal.artisan = request.user
                proposal.status = Proposal.Status.PENDING
                proposal.save()
                captions = request.POST.getlist('proposal_image_captions')
                skipped = _save_proposal_images(proposal, request.FILES, captions)
                for msg in skipped:
                    messages.warning(request, f'Image skipped: {msg}')
                if project_request.status == Request.Status.OPEN:
                    project_request.status = Request.Status.IN_REVIEW
                    project_request.save(update_fields=['status'])
                messages.success(request, 'Your proposal has been submitted.')
                notify(
                    project_request.requester,
                    Notification.NotifType.PROPOSAL_RECEIVED,
                    f'{request.user.username} submitted a proposal for your request',
                    body=f'"{project_request.title}" — review it and decide.',
                    link=reverse('request:request_detail_view', kwargs={'request_id': request_id}),
                )
                return redirect('request:request_detail_view', request_id=request_id)
            except IntegrityError:
                messages.error(request, 'You have already submitted a proposal for this request.')
                return redirect('request:request_detail_view', request_id=request_id)
    else:
        form = ProposalForm(instance=existing if existing else None)

    return render(request, 'proposal/proposal_form.html', {
        'form': form,
        'project_request': project_request,
        'request_images': list(project_request.images.all()),
        'edit_mode': False,
        'resubmit': existing is not None,
    })


@login_required
def edit_proposal_view(request, proposal_id):
    proposal = get_object_or_404(
        Proposal.objects.select_related('request__requester', 'request__category').prefetch_related('request__images', 'images'),
        id=proposal_id,
    )

    if proposal.artisan != request.user:
        messages.error(request, 'You can only edit your own proposals.')
        return redirect('request:request_detail_view', request_id=proposal.request_id)

    if not proposal.is_pending:
        messages.error(request, 'You can only edit a pending proposal.')
        return redirect('proposal:my_proposals_view')

    if request.method == 'POST':
        form = ProposalForm(request.POST, request.FILES, instance=proposal)
        if form.is_valid():
            form.save()

            for image in proposal.images.all():
                field_name = f'existing_proposal_image_caption_{image.id}'
                new_caption = (request.POST.get(field_name, '') or '').strip()[:160]
                if image.caption != new_caption:
                    image.caption = new_caption
                    image.save(update_fields=['caption'])

            delete_ids = request.POST.getlist('delete_proposal_image_ids')
            if delete_ids:
                proposal.images.filter(id__in=delete_ids).delete()

            captions = request.POST.getlist('proposal_image_captions')
            skipped = _save_proposal_images(proposal, request.FILES, captions)
            for msg in skipped:
                messages.warning(request, f'Image skipped: {msg}')

            messages.success(request, 'Proposal updated.')
            return redirect('request:request_detail_view', request_id=proposal.request_id)
    else:
        form = ProposalForm(instance=proposal)

    return render(request, 'proposal/proposal_form.html', {
        'form': form,
        'project_request': proposal.request,
        'request_images': list(proposal.request.images.all()),
        'existing_images': list(proposal.images.all()),
        'edit_mode': True,
        'proposal': proposal,
    })


@login_required
def withdraw_proposal_view(request, proposal_id):
    proposal = get_object_or_404(Proposal.objects.select_related('request'), id=proposal_id)
    project_request = proposal.request

    if request.method != 'POST':
        messages.error(request, 'Invalid action.')
        return redirect('request:request_detail_view', request_id=project_request.id)

    if proposal.artisan != request.user:
        messages.error(request, 'You can only withdraw your own proposals.')
        return redirect('request:request_detail_view', request_id=project_request.id)

    if not proposal.is_pending:
        messages.error(request, 'Only pending proposals can be withdrawn.')
        return redirect('request:request_detail_view', request_id=project_request.id)
    proposal.status = Proposal.Status.WITHDRAWN
    proposal.save(update_fields=['status', 'updated_at'])

    # Immediately revert to OPEN if no pending proposals remain and the request hasn't expired
    if project_request.status == Request.Status.IN_REVIEW:
        from django.utils import timezone
        today = timezone.localdate()
        has_pending = project_request.proposals.filter(status=Proposal.Status.PENDING).exists()
        if not has_pending:
            deadline_ok = project_request.deadline is None or project_request.deadline >= today
            if deadline_ok:
                project_request.status = Request.Status.OPEN
                project_request.save(update_fields=['status'])

    messages.success(request, 'Your proposal has been withdrawn.')
    return redirect('request:request_detail_view', request_id=proposal.request_id)


@login_required
def accept_proposal_view(request, proposal_id):
    proposal = get_object_or_404(Proposal.objects.select_related('request'), id=proposal_id)
    project_request = proposal.request

    if request.method != 'POST':
        messages.error(request, 'Invalid action.')
        return redirect('request:request_detail_view', request_id=project_request.id)

    if project_request.requester != request.user:
        messages.error(request, 'Only the requester can accept proposals.')
        return redirect('request:request_detail_view', request_id=project_request.id)

    if not proposal.is_pending:
        messages.error(request, 'This proposal is no longer pending.')
        return redirect('request:request_detail_view', request_id=project_request.id)

    if project_request.status == Request.Status.CLOSED:
        messages.error(request, 'This request is already closed.')
        return redirect('request:request_detail_view', request_id=project_request.id)

    proposal.status = Proposal.Status.ACCEPTED
    proposal.save(update_fields=['status', 'updated_at'])

    rejected_artisans = list(
        project_request.proposals
        .filter(status=Proposal.Status.PENDING)
        .exclude(id=proposal.id)
        .values_list('artisan', flat=True)
    )
    project_request.proposals.filter(status=Proposal.Status.PENDING).exclude(id=proposal.id).update(
        status=Proposal.Status.REJECTED
    )

    for artisan in get_user_model().objects.filter(id__in=rejected_artisans):
        notify(
            artisan,
            Notification.NotifType.PROPOSAL_REJECTED,
            'Your proposal was not selected',
            body=f'The requester went with another proposal for "{project_request.title}". Good luck with your other proposals!',
            link=reverse('request:request_detail_view', kwargs={'request_id': project_request.id}),
        )

    project_request.status = Request.Status.CLOSED
    project_request.save(update_fields=['status'])

    contract, _ = Contract.objects.get_or_create(proposal=proposal)

    messages.success(request, f"You accepted {proposal.artisan.username}'s proposal. The request is now closed.")
    notify(
        proposal.artisan,
        Notification.NotifType.PROPOSAL_ACCEPTED,
        'Your proposal was accepted!',
        body=f'You were chosen for "{project_request.title}". Head to the project page to get started.',
        link=reverse('progress:contract_detail_view', kwargs={'contract_id': contract.id}),
    )
    return redirect('request:request_detail_view', request_id=project_request.id)


@login_required
def reject_proposal_view(request, proposal_id):
    proposal = get_object_or_404(Proposal.objects.select_related('request'), id=proposal_id)
    project_request = proposal.request

    if request.method != 'POST':
        messages.error(request, 'Invalid action.')
        return redirect('request:request_detail_view', request_id=project_request.id)

    if project_request.requester != request.user:
        messages.error(request, 'Only the requester can reject proposals.')
        return redirect('request:request_detail_view', request_id=project_request.id)

    if not proposal.is_pending:
        messages.error(request, 'This proposal is no longer pending.')
        return redirect('request:request_detail_view', request_id=project_request.id)

    proposal.status = Proposal.Status.REJECTED
    proposal.save(update_fields=['status', 'updated_at'])
    messages.success(request, f"{proposal.artisan.username}'s proposal has been rejected.")
    notify(
        proposal.artisan,
        Notification.NotifType.PROPOSAL_REJECTED,
        'Your proposal was not selected',
        body=f'The requester passed on your proposal for "{project_request.title}".',
        link=reverse('request:request_detail_view', kwargs={'request_id': project_request.id}),
    )
    return redirect('request:request_detail_view', request_id=project_request.id)


@login_required
def my_proposals_view(request):
    if not _is_artisan(request.user):
        messages.error(request, 'Only artisans have proposals.')
        return redirect('main:home_view')

    qs = (
        Proposal.objects.filter(artisan=request.user)
        .select_related('request', 'request__category', 'request__requester', 'contract')
        .prefetch_related('images')
        .order_by('-created_at')
    )
    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'proposal/my_proposals.html', {'proposals': page_obj, 'page_obj': page_obj})

