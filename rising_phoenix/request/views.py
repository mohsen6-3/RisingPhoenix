import hashlib
import json
import logging
import time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.conf import settings
from django.utils import timezone

from rising_phoenix.moderation import image_is_clean, text_is_clean
from .forms import RequestForm
from .models import AIRefineLog, Request, RequestImage
from workshop.models import Category, WorkshopProfile

logger = logging.getLogger(__name__)


def _extract_first_json_object(raw_text: str):
    start = raw_text.find('{')
    end = raw_text.rfind('}')
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(raw_text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None

    return None


def _call_with_retry(call_fn, attempts: int, base_delay_seconds: float):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return call_fn()
        except Exception as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(base_delay_seconds * (2 ** (attempt - 1)))

    if last_error is not None:
        raise last_error

    raise RuntimeError('Retry helper failed without an explicit error.')


def _save_uploaded_request_images(request_instance: Request, request_files, captions=None):
    max_size_mb = float(getattr(settings, 'REQUEST_IMAGE_MAX_SIZE_MB', 5))
    max_size_bytes = int(max_size_mb * 1024 * 1024)
    allowed_types = list(getattr(settings, 'REQUEST_IMAGE_ALLOWED_TYPES', ['image/jpeg', 'image/png', 'image/webp', 'image/gif']))
    max_count = int(getattr(settings, 'REQUEST_IMAGE_MAX_COUNT', 5))
    captions = captions or []
    skipped = []

    existing_count = request_instance.images.count()
    slots_remaining = max(0, max_count - existing_count)
    incoming = request_files.getlist('reference_images')

    if len(incoming) > slots_remaining:
        overflow = len(incoming) - slots_remaining
        skipped.append(f'{overflow} image(s) skipped — requests are limited to {max_count} images total.')
        incoming = incoming[:slots_remaining]

    for index, image_file in enumerate(incoming):
        if image_file.size > max_size_bytes:
            logger.warning('Rejected oversized image upload "%s" (%d bytes) for request id=%s', image_file.name, image_file.size, request_instance.id)
            skipped.append(f'"{image_file.name}" exceeds the {max_size_mb:.0f} MB size limit.')
            continue
        content_type = getattr(image_file, 'content_type', '') or ''
        if content_type.lower() not in allowed_types:
            logger.warning('Rejected disallowed content type "%s" for image "%s" on request id=%s', content_type, image_file.name, request_instance.id)
            skipped.append(f'"{image_file.name}" is not an accepted image type (JPEG, PNG, WebP, GIF).')
            continue
        if not image_is_clean(image_file):
            logger.warning('Rejected explicit image "%s" for request id=%s', image_file.name, request_instance.id)
            skipped.append(f'"{image_file.name}" was removed: explicit content detected.')
            continue
        try:
            caption = (captions[index] if index < len(captions) else '').strip()
            if caption and not text_is_clean(caption):
                caption = ''
            RequestImage.objects.create(request=request_instance, image=image_file, caption=caption[:160])
        except Exception:
            logger.exception('Failed to save uploaded image "%s"', image_file.name)
            skipped.append(f'"{image_file.name}" could not be saved.')
    return skipped


def _refresh_time_based_statuses():
    cache_key = 'request_statuses_refreshed'
    if cache.get(cache_key):
        return
    today = timezone.localdate()
    Request.objects.filter(
        status__in=[Request.Status.OPEN, Request.Status.IN_REVIEW],
        deadline__isnull=False,
        deadline__lt=today,
    ).update(status=Request.Status.TIME_ENDED)
    # Revert IN_REVIEW → OPEN when every proposal has been withdrawn/rejected
    # (and the request hasn't expired yet).
    # Use exclude+subquery instead of annotate+update (annotate+update is unreliable in Django).
    from proposal.models import Proposal as _Proposal
    requests_with_pending = (
        _Proposal.objects.filter(status='pending').values('request_id').distinct()
    )
    Request.objects.filter(
        status=Request.Status.IN_REVIEW,
    ).filter(
        Q(deadline__isnull=True) | Q(deadline__gte=today)
    ).exclude(
        id__in=requests_with_pending
    ).update(status=Request.Status.OPEN)
    cache.set(cache_key, True, timeout=60)


def request_list_view(request: HttpRequest):
    _refresh_time_based_statuses()
    project_requests = (
        Request.objects
        .select_related('requester', 'category')
        .prefetch_related('images')
        .annotate(proposal_count=Count('proposals'))
    )

    is_artisan = request.user.is_authenticated and request.user.groups.filter(name='artisan').exists()

    # Non-artisan visitors (guests + regular requesters) only see closed requests,
    # except requesters can also see their own open ones.
    if not is_artisan:
        if request.user.is_authenticated:
            project_requests = project_requests.filter(
                Q(status=Request.Status.CLOSED) | Q(requester=request.user)
            )
        else:
            project_requests = project_requests.filter(status=Request.Status.CLOSED)

    search_query = request.GET.get('q', '').strip()
    category = request.GET.get('category', '').strip()
    status = request.GET.get('status', '').strip()
    sort = request.GET.get('sort', 'newest').strip()
    mine = request.GET.get('mine', '').strip()

    valid_statuses = {choice[0] for choice in Request.Status.choices}

    if mine == '1' and request.user.is_authenticated:
        project_requests = project_requests.filter(requester=request.user)

    if search_query:
        project_requests = project_requests.filter(
            Q(title__icontains=search_query)
            | Q(description__icontains=search_query)
            | Q(category__name__icontains=search_query)
            | Q(requester__username__icontains=search_query)
        )

    if category.isdigit():
        project_requests = project_requests.filter(category_id=int(category))

    if status in valid_statuses:
        project_requests = project_requests.filter(status=status)

    if sort == 'deadline_soon':
        project_requests = project_requests.order_by(F('deadline').asc(nulls_last=True), '-created_at')
    elif sort == 'budget_high':
        project_requests = project_requests.order_by(F('budget_max').desc(nulls_last=True), '-created_at')
    elif sort == 'budget_low':
        project_requests = project_requests.order_by(F('budget_max').asc(nulls_last=True), '-created_at')
    elif sort == 'oldest':
        project_requests = project_requests.order_by('created_at')
    else:
        project_requests = project_requests.order_by('-created_at')

    total_count = project_requests.count()
    paginator = Paginator(project_requests, 9)
    page_obj = paginator.get_page(request.GET.get('page'))

    context = {
        'project_requests': page_obj.object_list,
        'page_obj': page_obj,
        'total_count': total_count,
        'category_choices': Category.objects.order_by('name'),
        'status_choices': Request.Status.choices,
        'current_q': search_query,
        'current_category': category,
        'current_status': status,
        'current_sort': sort,
        'current_mine': mine,
    }
    return render(request, 'request/request_list.html', context)


@login_required
def my_requests_view(request: HttpRequest):
    _refresh_time_based_statuses()
    qs = (
        Request.objects
        .filter(requester=request.user)
        .select_related('category')
        .prefetch_related('images')
        .annotate(proposal_count=Count('proposals'))
        .order_by('-created_at')
    )
    paginator = Paginator(qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(request, 'request/my_requests.html', {'page_obj': page_obj})


def suggested_artisans_view(request: HttpRequest):
    category_id = request.GET.get('category_id', '').strip()
    if not category_id.isdigit():
        return JsonResponse({'artisans': []})

    workshops = (
        WorkshopProfile.objects.select_related('artisan__user')
        .filter(
            is_published=True,
            categories__id=int(category_id),
            artisan__is_banned=False,
        )
        .order_by('-artisan__is_verified', '-artisan__average_rating', '-id')
        .distinct()[:6]
    )

    artisans = []
    for workshop in workshops:
        artisans.append(
            {
                'workshop_name': workshop.workshop_name,
                'tagline': workshop.tagline,
                'location': workshop.location,
                'artisan_username': workshop.artisan.user.username,
                'artisan_user_id': workshop.artisan.user_id,
                'workshop_url': reverse('workshop:workshop_detail_view', args=[workshop.artisan.user_id]),
            }
        )

    return JsonResponse({'artisans': artisans})


@login_required
def my_open_requests_view(request: HttpRequest):
    """Return the current user's OPEN requests as JSON (used by the workshop invite modal)."""
    open_requests = (
        Request.objects.filter(requester=request.user, status=Request.Status.OPEN)
        .order_by('-created_at')
        .values('id', 'title')
    )
    return JsonResponse({'requests': list(open_requests)})


def request_detail_view(request: HttpRequest, request_id: int):
    _refresh_time_based_statuses()
    project_request = get_object_or_404(
        Request.objects.select_related('requester', 'category').prefetch_related('images'),
        id=request_id,
    )
    images = list(project_request.images.all())

    proposals = []
    user_proposal = None
    is_artisan = request.user.is_authenticated and request.user.groups.filter(name='artisan').exists()
    is_requester = request.user.is_authenticated and project_request.requester == request.user

    # Match list-view rules: non-artisan visitors can only see CLOSED requests
    # (plus their own). Direct-URL access to OPEN/IN_REVIEW/TIME_ENDED is denied.
    if not is_artisan and not is_requester and project_request.status != Request.Status.CLOSED:
        messages.error(request, 'This request is not available.')
        return redirect('request:request_list_view')

    invitations = []
    if is_requester:
        proposals = list(
            project_request.proposals.select_related('artisan', 'contract').prefetch_related('images').order_by('-created_at')
        )
        invitations = list(
            project_request.invitations.select_related('artisan').order_by('-created_at')
        )
    elif is_artisan:
        user_proposal = project_request.proposals.select_related('contract').prefetch_related('images').filter(artisan=request.user).first()
        # Mark any pending invitation to this artisan as VIEWED.
        from invitation.models import Invitation
        Invitation.objects.filter(
            request=project_request,
            artisan=request.user,
            status=Invitation.Status.PENDING,
        ).update(status=Invitation.Status.VIEWED, viewed_at=timezone.now())

    can_submit = (
        is_artisan
        and not is_requester
        and user_proposal is None
        and project_request.status in [Request.Status.OPEN, Request.Status.IN_REVIEW]
    )

    return render(request, 'request/request_detail.html', {
        'project_request': project_request,
        'images': images,
        'has_images': bool(images),
        'proposals': proposals,
        'user_proposal': user_proposal,
        'is_requester': is_requester,
        'is_artisan': is_artisan,
        'can_submit': can_submit,
        'invitations': invitations,
    })


@login_required
def request_create_view(request: HttpRequest):
    _refresh_time_based_statuses()
    if request.method == 'POST':
        form = RequestForm(request.POST, request.FILES)
        if form.is_valid():
            request_instance = form.save(commit=False)
            request_instance.requester = request.user
            request_instance.save()
            captions = request.POST.getlist('reference_image_captions')
            skipped = _save_uploaded_request_images(request_instance, request.FILES, captions)
            for msg in skipped:
                messages.warning(request, f'Image skipped: {msg}')
            messages.success(request, 'Your request has been posted.')
            return redirect('request:request_list_view')
    else:
        form = RequestForm()

    return render(request, 'request/request_form.html', {'form': form, 'edit_mode': False})


@login_required
def request_edit_view(request: HttpRequest, request_id: int):
    _refresh_time_based_statuses()
    request_instance = get_object_or_404(Request.objects.prefetch_related('images'), id=request_id)

    if request_instance.requester_id != request.user.id:
        messages.error(request, 'You can only edit your own requests.')
        return redirect('request:request_list_view')

    if request_instance.status in [Request.Status.CLOSED, Request.Status.TIME_ENDED]:
        messages.warning(request, 'This request is no longer editable.')
        return redirect('request:request_list_view')

    if request.method == 'POST':
        form = RequestForm(request.POST, request.FILES, instance=request_instance)
        if form.is_valid():
            form.save()
            for image in request_instance.images.all():
                field_name = f'existing_image_caption_{image.id}'
                new_caption = (request.POST.get(field_name, '') or '').strip()[:160]
                if image.caption != new_caption:
                    image.caption = new_caption
                    image.save(update_fields=['caption'])

            delete_image_ids = request.POST.getlist('delete_image_ids')
            if delete_image_ids:
                request_instance.images.filter(id__in=delete_image_ids).delete()
            captions = request.POST.getlist('reference_image_captions')
            skipped = _save_uploaded_request_images(request_instance, request.FILES, captions)
            for msg in skipped:
                messages.warning(request, f'Image skipped: {msg}')
            messages.success(request, 'Request updated successfully.')
            return redirect('request:request_detail_view', request_id=request_instance.id)
    else:
        form = RequestForm(instance=request_instance)

    context = {
        'form': form,
        'edit_mode': True,
        'request_instance': request_instance,
        'existing_images': request_instance.images.all(),
    }
    return render(request, 'request/request_form.html', context)


@login_required
def reopen_request_view(request: HttpRequest, request_id: int):
    request_instance = get_object_or_404(Request, id=request_id)

    if request.method != 'POST':
        messages.error(request, 'Invalid action.')
        return redirect('request:request_detail_view', request_id=request_id)

    if request_instance.requester_id != request.user.id:
        messages.error(request, 'Only the requester can reopen this request.')
        return redirect('request:request_detail_view', request_id=request_id)

    if request_instance.status != Request.Status.TIME_ENDED:
        messages.error(request, 'Only time-ended requests can be reopened.')
        return redirect('request:request_detail_view', request_id=request_id)

    new_deadline_str = request.POST.get('new_deadline', '').strip()
    if not new_deadline_str:
        messages.error(request, 'Please provide a new deadline.')
        return redirect('request:request_detail_view', request_id=request_id)

    try:
        from datetime import date
        new_deadline = date.fromisoformat(new_deadline_str)
        if new_deadline <= timezone.localdate():
            messages.error(request, 'The new deadline must be in the future.')
            return redirect('request:request_detail_view', request_id=request_id)
    except ValueError:
        messages.error(request, 'Invalid date format.')
        return redirect('request:request_detail_view', request_id=request_id)

    # If any proposals are still pending, go back to IN_REVIEW; otherwise OPEN
    has_pending = request_instance.proposals.filter(status='pending').exists()
    request_instance.deadline = new_deadline
    request_instance.status = Request.Status.IN_REVIEW if has_pending else Request.Status.OPEN
    request_instance.save(update_fields=['deadline', 'status'])
    messages.success(request, 'Your request has been reopened with the new deadline.')
    return redirect('request:request_detail_view', request_id=request_id)


@login_required
@require_POST
def refine_request_view(request: HttpRequest):
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON payload.'}, status=400)

    user_text = (payload.get('text') or '').strip()
    category_name = (payload.get('category_name') or '').strip()[:80]
    previous_suggestion = (payload.get('previous_suggestion') or '').strip()
    if not user_text:
        return JsonResponse({'error': 'Please provide request text to refine.'}, status=400)

    max_input_chars = int(getattr(settings, 'OPENAI_REFINE_MAX_INPUT_CHARS', 1200))
    if len(user_text) > max_input_chars:
        return JsonResponse({'error': f'Please keep the description under {max_input_chars} characters.'}, status=400)

    # Rate limiting
    rate_limit = int(getattr(settings, 'OPENAI_REFINE_RATE_LIMIT', 10))
    rate_window = int(getattr(settings, 'OPENAI_REFINE_RATE_WINDOW_SECONDS', 3600))
    rate_key = f'ai_refine_rate:{request.user.id}'
    current_count = cache.get(rate_key, 0)
    if current_count >= rate_limit:
        return JsonResponse({'error': f'You have reached the limit of {rate_limit} AI refinements per hour. Please try again later.'}, status=429)

    # Prompt caching
    cache_ttl = int(getattr(settings, 'OPENAI_REFINE_CACHE_TTL_SECONDS', 300))
    model_for_cache = getattr(settings, 'OPENAI_MODEL', 'gpt-4o-mini')
    cache_key = None
    if cache_ttl > 0:
        cache_input = f'{model_for_cache}:{category_name}:{previous_suggestion}:{user_text}'
        text_hash = hashlib.sha256(cache_input.encode('utf-8')).hexdigest()
        cache_key = f'ai_refine_cache:{text_hash}'
        cached_response = cache.get(cache_key)
        if cached_response is not None:
            AIRefineLog.objects.create(
                user=request.user,
                input_chars=len(user_text),
                was_flagged=False,
                was_cached=True,
                success=True,
                confidence=cached_response.get('confidence'),
                latency_ms=0,
            )
            return JsonResponse(cached_response)

    api_key = getattr(settings, 'OPENAI_API_KEY', '').strip()
    if not api_key:
        logger.warning('OPENAI_API_KEY not configured')
        return JsonResponse({'error': 'AI service is not configured. Add OPENAI_API_KEY in environment settings.'}, status=503)

    try:
        from openai import OpenAI # type: ignore
    except ImportError:
        logger.error('OpenAI package not installed')
        return JsonResponse({'error': 'OpenAI package is not installed. Add it to requirements and install dependencies.'}, status=503)

    model_name = getattr(settings, 'OPENAI_MODEL', 'gpt-4o-mini')
    moderation_model = getattr(settings, 'OPENAI_MODERATION_MODEL', 'omni-moderation-latest')
    timeout_seconds = float(getattr(settings, 'OPENAI_REFINE_TIMEOUT_SECONDS', 15))
    retries = int(getattr(settings, 'OPENAI_REFINE_RETRIES', 2))
    retry_base_delay_seconds = float(getattr(settings, 'OPENAI_REFINE_RETRY_BASE_DELAY_SECONDS', 0.7))
    max_output_tokens = int(getattr(settings, 'OPENAI_REFINE_MAX_OUTPUT_TOKENS', 300))
    temperature = float(getattr(settings, 'OPENAI_REFINE_TEMPERATURE', 0.5))

    retries = max(1, min(retries, 5))
    timeout_seconds = max(5.0, min(timeout_seconds, 60.0))
    max_output_tokens = max(60, min(max_output_tokens, 400))
    temperature = max(0.0, min(temperature, 1.2))
    retry_base_delay_seconds = max(0.2, min(retry_base_delay_seconds, 3.0))

    category_line = f' The request is in the category: {category_name}.' if category_name else ''
    system_prompt = (
        f'You are an expert consultant for a Saudi custom-item marketplace.{category_line} '
        'Rewrite the buyer\'s request in clear, natural first-person English. '
        'Stay under 80 words. Include only details that are stated or clearly implied — do not invent specifics. '
        'Return JSON only: {"refined_text":"string","missing_details":["string"],"confidence":0.0}. '
        'Each item in missing_details must be a short question the buyer should answer to strengthen their request '
        '(e.g. "What size do you need?", "Do you have a preferred material?"). '
        'Include up to 4 questions. Keep confidence between 0 and 1.'
    )

    start_time = time.monotonic()
    try:
        client = OpenAI(api_key=api_key, timeout=timeout_seconds)

        moderation_response = _call_with_retry(
            lambda: client.moderations.create(model=moderation_model, input=user_text),
            attempts=retries,
            base_delay_seconds=retry_base_delay_seconds,
        )
        moderation_results = getattr(moderation_response, 'results', []) or []
        is_flagged = bool(moderation_results and getattr(moderation_results[0], 'flagged', False))
        if is_flagged:
            AIRefineLog.objects.create(
                user=request.user,
                input_chars=len(user_text),
                was_flagged=True,
                was_cached=False,
                success=False,
            )
            return JsonResponse({'error': 'Your text could not be processed. Please rephrase and try again.'}, status=400)

        if previous_suggestion:
            messages_payload = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_text},
                {'role': 'assistant', 'content': previous_suggestion},
                {'role': 'user', 'content': 'Please refine this further, making it clearer and more specific.'},
            ]
        else:
            messages_payload = [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_text},
            ]

        response = _call_with_retry(
            lambda: client.chat.completions.create(
                model=model_name,
                messages=messages_payload,
                temperature=temperature,
                max_tokens=max_output_tokens,
                response_format={'type': 'json_object'},
            ),
            attempts=retries,
            base_delay_seconds=retry_base_delay_seconds,
        )

        raw_content = (response.choices[0].message.content or '').strip()
        parsed = _extract_first_json_object(raw_content)
        if not parsed:
            logger.warning('OpenAI returned non-JSON content in refine_request_view for user_id=%s', request.user.id)
            return JsonResponse({'error': 'AI response was invalid. Please try again.'}, status=502)

        refined_text = str(parsed.get('refined_text', '')).strip()
        missing_details_raw = parsed.get('missing_details', [])
        confidence_raw = parsed.get('confidence', None)

        if isinstance(missing_details_raw, list):
            missing_details = [str(item).strip() for item in missing_details_raw if str(item).strip()][:6]
        else:
            missing_details = []

        try:
            confidence = float(confidence_raw)
            confidence = max(0.0, min(confidence, 1.0))
        except (TypeError, ValueError):
            confidence = None
    except Exception:
        latency_ms_err = int((time.monotonic() - start_time) * 1000)
        AIRefineLog.objects.create(
            user=request.user,
            input_chars=len(user_text),
            was_flagged=False,
            was_cached=False,
            success=False,
            latency_ms=latency_ms_err,
        )
        logger.exception('OpenAI refine request failed for user_id=%s', request.user.id)
        return JsonResponse({'error': 'AI service is temporarily unavailable. Please try again.'}, status=502)

    if not refined_text:
        return JsonResponse({'error': 'AI returned an empty response. Please try again.'}, status=502)

    latency_ms = int((time.monotonic() - start_time) * 1000)
    tokens_used = None
    try:
        usage = getattr(response, 'usage', None)
        if usage:
            tokens_used = int(getattr(usage, 'total_tokens', None) or 0) or None
    except Exception:
        pass

    # Increment rate limit counter
    try:
        new_count = cache.get(rate_key, 0) + 1
        cache.set(rate_key, new_count, timeout=rate_window)
    except Exception:
        pass

    result = {'refined_text': refined_text, 'missing_details': missing_details, 'confidence': confidence}

    # Store in prompt cache
    if cache_key and cache_ttl > 0:
        try:
            cache.set(cache_key, result, timeout=cache_ttl)
        except Exception:
            pass

    AIRefineLog.objects.create(
        user=request.user,
        input_chars=len(user_text),
        was_flagged=False,
        was_cached=False,
        success=True,
        confidence=confidence,
        latency_ms=latency_ms,
        tokens_used=tokens_used,
    )

    return JsonResponse(result)
