from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from rising_phoenix.moderation import image_is_clean, text_is_clean
from .models import Conversation, Message
from notification.models import Notification
from notification.utils import notify
from proposal.models import Proposal

@login_required
def start_conversation_view(request: HttpRequest, proposal_id: int) -> HttpResponse:
    proposal = get_object_or_404(Proposal, id=proposal_id)

    requester = proposal.request.requester
    artisan = proposal.artisan

    if request.user not in (requester, artisan):
        messages.error(request, "You are not allowed to start this conversation.")
        return redirect('main:home_view')

    conversation, created = Conversation.objects.get_or_create(
        proposal=proposal,
        defaults={
            'requester': requester,
            'artisan': artisan,
        }
    )

    if created:
        messages.success(request, "Conversation started successfully.")
        recipient = artisan if request.user == requester else requester
        notify(
            recipient=recipient,
            notif_type=Notification.NotifType.MESSAGE_RECEIVED,
            title=f'{request.user.username} wants to chat',
            body=f'About: {proposal.request.title}',
            link=reverse('message:conversation_detail_view', args=[conversation.id]),
        )

    return redirect('message:conversation_detail_view', conversation_id=conversation.id)


@login_required
def conversation_list_view(request: HttpRequest) -> HttpResponse:
    conversations = Conversation.objects.filter(
        Q(requester=request.user) | Q(artisan=request.user)
    ).select_related(
        'proposal',
        'requester',
        'artisan'
    ).order_by('-updated_at')

    context = {
        'conversations': conversations,
    }
    return render(request, 'message/conversation_list.html', context)


@login_required
def conversation_detail_view(request, conversation_id):
    conversation = get_object_or_404(Conversation, id=conversation_id)

    if request.user not in [conversation.requester, conversation.artisan]:
        return redirect('message:conversation_list_view')

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == "POST":
        if not conversation.is_active:
            error_message = 'This conversation is closed. You can still view the message history.'

            if is_ajax:
                return JsonResponse({'error': error_message, 'conversation_closed': True}, status=403)

            messages.warning(request, error_message)
            return redirect('message:conversation_detail_view', conversation_id=conversation.id)

        body = request.POST.get("body", "").strip()
        image = request.FILES.get("image")

        if body and not text_is_clean(body):
            if is_ajax:
                return JsonResponse({'error': 'Your message contains inappropriate language. Please revise it.'}, status=400)
            messages.error(request, 'Your message contains inappropriate language. Please revise it.')
            return redirect('message:conversation_detail_view', conversation_id=conversation.id)

        image_error = None
        if image:
            allowed_types = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
            if image.size > 5 * 1024 * 1024:
                image_error = 'Image must be under 5 MB.'
                image = None
            elif (getattr(image, 'content_type', '') or '').lower() not in allowed_types:
                image_error = 'Only JPEG, PNG, WebP, and GIF images are allowed.'
                image = None
            elif not image_is_clean(image):
                image_error = 'Your image was rejected: explicit content detected.'
                image = None

            if image_error:
                if is_ajax:
                    return JsonResponse({'error': image_error}, status=400)
                messages.error(request, image_error)

        if body or image:
            Message.objects.create(
                conversation=conversation,
                sender=request.user,
                body=body,
                image=image
            )
            recipient = (
                conversation.artisan
                if request.user == conversation.requester
                else conversation.requester
            )
            notify(
                recipient=recipient,
                notif_type=Notification.NotifType.MESSAGE_RECEIVED,
                title=f'New message from {request.user.username}',
                body=body[:120] if body else 'Sent an image',
                link=reverse('message:conversation_detail_view', args=[conversation.id]),
            )
            if is_ajax:
                return JsonResponse({'ok': True})
            return redirect('message:conversation_detail_view', conversation_id=conversation.id)

    conversation_messages = conversation.messages.select_related("sender").order_by("created_at")

    context = {
        "conversation": conversation,
        "conversation_messages": conversation_messages,
    }
    return render(request, "message/conversation_detail.html", context)


def conversation_messages_json_view(request, conversation_id):
    conversation = get_object_or_404(
        Conversation,
        id=conversation_id
    )

    if request.user not in [conversation.requester, conversation.artisan]:
        return JsonResponse({"error": "Unauthorized"}, status=403)

    messages = conversation.messages.select_related("sender").order_by("created_at")

    data = [
        {
            "id": msg.id,
            "body": msg.body,
            "sender_name": msg.sender.get_full_name() or msg.sender.username,
            "is_mine": msg.sender == request.user,
            "created_at": msg.created_at.strftime("%b %d, %Y %I:%M %p"),
            "image_url": msg.image.url if msg.image else "",
        }
        for msg in messages
    ]

    return JsonResponse({"messages": data})

