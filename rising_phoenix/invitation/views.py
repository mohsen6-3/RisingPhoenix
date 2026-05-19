import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from notification.models import Notification
from notification.utils import notify
from request.models import Request

from .models import Invitation

logger = logging.getLogger(__name__)


@login_required
@require_POST
def send_invitation_view(request):
    request_id = request.POST.get('request_id', '').strip()
    artisan_user_id = request.POST.get('artisan_user_id', '').strip()

    if not request_id.isdigit() or not artisan_user_id.isdigit():
        return JsonResponse({'error': 'invalid_params'}, status=400)

    project_request = get_object_or_404(Request, id=int(request_id))

    if project_request.requester_id != request.user.id:
        return JsonResponse({'error': 'not_owner'}, status=403)

    if project_request.status != Request.Status.OPEN:
        return JsonResponse({'error': 'request_not_open'}, status=400)

    User = get_user_model()
    artisan = get_object_or_404(User, id=int(artisan_user_id))

    if not artisan.groups.filter(name='artisan').exists():
        return JsonResponse({'error': 'not_an_artisan'}, status=400)

    artisan_profile = getattr(artisan, 'artisan_profile', None)
    if artisan_profile is not None and getattr(artisan_profile, 'is_banned', False):
        return JsonResponse({'error': 'artisan_unavailable'}, status=400)

    if artisan_user_id == str(request.user.id):
        return JsonResponse({'error': 'cannot_invite_self'}, status=400)

    try:
        invitation, created = Invitation.objects.get_or_create(
            request=project_request,
            artisan=artisan,
        )
    except IntegrityError:
        invitation = Invitation.objects.get(request=project_request, artisan=artisan)
        created = False

    if not created:
        return JsonResponse({
            'error': 'already_invited',
            'status': invitation.status,
        }, status=409)

    notify(
        artisan,
        Notification.NotifType.INVITATION_RECEIVED,
        f'{request.user.username} invited you to a project',
        body=f'"{project_request.title}" — they would like you to submit a proposal.',
        link=reverse('request:request_detail_view', kwargs={'request_id': project_request.id}),
    )

    return JsonResponse({
        'status': invitation.status,
        'invitation_id': invitation.id,
        'created_at': invitation.created_at.isoformat(),
    })
