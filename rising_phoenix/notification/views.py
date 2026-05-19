from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import redirect, render

from .models import Notification, NotificationPreference

_PREF_FIELDS = [
    'email_proposal_received', 'email_proposal_accepted', 'email_proposal_rejected',
    'email_progress_update', 'email_comment_added', 'email_completion_requested',
    'email_completion_confirmed', 'email_completion_rejected', 'email_message_received',
    'email_invitation_received',
    'email_dispute_received', 'email_dispute_message_received', 'email_dispute_status_update',
    'insite_proposal_received', 'insite_proposal_accepted', 'insite_proposal_rejected',
    'insite_progress_update', 'insite_comment_added', 'insite_completion_requested',
    'insite_completion_confirmed', 'insite_completion_rejected', 'insite_message_received',
    'insite_invitation_received',
    'insite_dispute_received', 'insite_dispute_message_received', 'insite_dispute_status_update',
]


@login_required
def notification_list_view(request):
    qs = Notification.objects.filter(recipient=request.user).order_by('-created_at')
    unread_count = qs.filter(is_read=False).count()
    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'notification/notification_list.html', {
        'notifications': page_obj.object_list,
        'page_obj': page_obj,
        'unread_count': unread_count,
    })


@login_required
def recent_api_view(request):
    qs = list(
        Notification.objects.filter(recipient=request.user).order_by('-created_at')[:5]
    )
    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    data = [
        {
            'id': n.id,
            'title': n.title,
            'body': n.body,
            'link': n.link,
            'icon_class': n.icon_class,
            'icon_color': n.icon_color,
            'is_read': n.is_read,
            'created_at': n.created_at.isoformat(),
        }
        for n in qs
    ]
    return JsonResponse({'count': unread_count, 'notifications': data})


@login_required
def mark_read_view(request, notif_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    Notification.objects.filter(id=notif_id, recipient=request.user).update(is_read=True)
    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return JsonResponse({'count': unread_count})


@login_required
def mark_all_read_view(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'count': 0})


@login_required
def notification_settings_view(request):
    prefs, _ = NotificationPreference.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        for field in _PREF_FIELDS:
            setattr(prefs, field, field in request.POST)
        prefs.save(update_fields=_PREF_FIELDS)
        messages.success(request, 'Notification preferences saved.')
        return redirect('notification:notification_settings_view')
    return render(request, 'notification/notification_settings.html', {'prefs': prefs})
