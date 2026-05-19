from django.shortcuts import redirect, render
from django.http import HttpRequest, HttpResponse
from django.contrib.auth.decorators import login_required
# from django.contrib.admin.views.decorators import staff_member_required
from account.models import Profile, ArtisanProfile
from workshop.models import Category, WorkshopProfile
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404
from django.contrib import messages
from django.db.models import Count
from django.utils import timezone
from django.urls import reverse
import datetime
import mimetypes
from django.conf import settings
from .models import Report, StaffProfile
from .forms import ReportForm, StaffProfileForm


# Create your views here.


def staff_required(view_func):

    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            return redirect('main:home_view')
        return view_func(request, *args, **kwargs)
    return wrapper



@staff_required
def staff_dashboard_view(request: HttpRequest):
    profiles = Profile.objects.select_related('user').order_by('-created_at')
    artisan_profiles = ArtisanProfile.objects.select_related('user').order_by('-created_at')
    categories = Category.objects.all()
    
    categories = Category.objects.annotate(
    workshop_count=Count('workshopprofile')
    )
 
    context = {
        'profiles': profiles,
        'artisan_profiles': artisan_profiles,
        'artisan_requests': artisan_profiles.filter(is_verified=False, is_banned=False),
        'categories': categories,
        
        
        'total_users': profiles.count(),
        'banned_users': profiles.filter(is_banned=True).count(),
        'total_artisans': artisan_profiles.count(),
        'verified_artisans': artisan_profiles.filter(is_verified=True).count(),
        'featured_artisans': artisan_profiles.filter(is_featured=True).count(),
        'banned_artisans': artisan_profiles.filter(is_banned=True).count(),
        'pending_reports_count': Report.objects.filter(status=Report.Status.PENDING).count(),
        'pending_disputes_count': _pending_disputes_count(),
    }
    return render(request, 'staff/staff_dashboard.html', context)


def _pending_disputes_count():
    from dispute.models import Dispute
    return Dispute.objects.filter(status__in=[Dispute.Status.OPEN, Dispute.Status.IN_REVIEW]).count()


@staff_required
def staff_profile_view(request: HttpRequest):
    profile, _ = StaffProfile.objects.get_or_create(
        user=request.user,
        defaults={
            'display_name': request.user.get_full_name() or request.user.username,
        },
    )
    return render(request, 'staff/staff_profile.html', {'staff_profile': profile})


@staff_required
def update_staff_profile_view(request: HttpRequest):
    profile, _ = StaffProfile.objects.get_or_create(
        user=request.user,
        defaults={
            'display_name': request.user.get_full_name() or request.user.username,
        },
    )

    if request.method == 'POST':
        form = StaffProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, 'Staff profile updated successfully.')
            return redirect('staff:staff_profile_view')
        messages.error(request, 'Please fix the errors below.')
    else:
        form = StaffProfileForm(instance=profile)

    return render(request, 'staff/update_staff_profile.html', {
        'form': form,
        'staff_profile': profile,
    })
 

@staff_required
@require_POST
def ban_user_view(request: HttpRequest, user_id: int):
    profile = get_object_or_404(Profile, user__id=user_id)
 
    if profile.is_banned:
        # Unban
        profile.is_banned = False
        profile.ban_reason = ''
        profile.user.is_active = True
        profile.user.save()
        profile.save()
        messages.success(request, f'{profile.user.username} has been unbanned.')
    else:
        # Ban
        ban_reason = request.POST.get('ban_reason', '').strip()
        profile.is_banned = True
        profile.ban_reason = ban_reason
        profile.user.is_active = False
        profile.user.save()
        profile.save()
        messages.warning(request, f'{profile.user.username} has been banned.')
 
    return redirect('staff:staff_dashboard_view')
 
#same thing but for artisans
@staff_required
@require_POST
def ban_artisan_view(request: HttpRequest, user_id: int):
    artisan = get_object_or_404(ArtisanProfile, user__id=user_id)
 
    if artisan.is_banned:
        artisan.is_banned = False
        artisan.ban_reason = ''
        artisan.user.is_active = True
        artisan.user.save()
        artisan.save()
        messages.success(request, f'{artisan.user.username} has been unbanned.')
    else:
        ban_reason = request.POST.get('ban_reason', '').strip()
        artisan.is_banned = True
        artisan.ban_reason = ban_reason
        artisan.user.is_active = False
        artisan.user.save()
        artisan.save()
        messages.warning(request, f'{artisan.user.username} has been banned.')
 
    return redirect('staff:staff_dashboard_view')
 
 
@staff_required
@require_POST
def feature_artisan_view(request: HttpRequest, user_id: int):
    artisan = get_object_or_404(ArtisanProfile, user__id=user_id)
    artisan.is_featured = not artisan.is_featured
    artisan.save()
 
    state = 'featured' if artisan.is_featured else 'unfeatured'
    messages.success(request, f'{artisan.user.username} has been {state}.')
 
    return redirect('staff:staff_dashboard_view')

@staff_required
@require_POST
def verify_artisan_view(request: HttpRequest, user_id: int):
    artisan = get_object_or_404(ArtisanProfile, user__id=user_id)
    artisan.is_verified = not artisan.is_verified
    artisan.save()
 
    state = 'verified' if artisan.is_verified else 'not verified'
    messages.success(request, f'{artisan.user.username} has been {state}.')
 
    return redirect('staff:staff_dashboard_view')

@staff_required
@require_POST
def add_category_view(request: HttpRequest):
    name = request.POST.get('name', '').strip()
    description = request.POST.get('description', '').strip()
    if name:
        Category.objects.create(name=name, description=description)
        messages.success(request, f'Category "{name}" has been added.')
    else:
        messages.error(request, 'Category name cannot be empty.')
    return redirect('staff:staff_dashboard_view')


# ── Report & Flagging ─────────────────────────────────────────────────────────

def _resolve_report_target(content_type, object_id):
    """Return (target_object, field_name) or (None, None) if invalid."""
    from request.models import Request as ItemRequest
    from workshop.models import PortfolioImage
    from account.models import Review
    from message.models import Message
    from django.contrib.auth.models import User

    mapping = {
        Report.ContentType.USER:            (User,          'reported_user'),
        Report.ContentType.REQUEST:         (ItemRequest,   'reported_request'),
        Report.ContentType.PORTFOLIO_IMAGE: (PortfolioImage,'reported_portfolio_image'),
        Report.ContentType.REVIEW:          (Review,        'reported_review'),
        Report.ContentType.MESSAGE:         (Message,       'reported_message'),
    }
    entry = mapping.get(content_type)
    if not entry:
        return None, None
    model_class, field_name = entry
    try:
        obj = model_class.objects.get(pk=object_id)
    except model_class.DoesNotExist:
        return None, None
    return obj, field_name


@login_required
def submit_report_view(request: HttpRequest, content_type: str, object_id: int):
    from urllib.parse import urlparse

    target, field_name = _resolve_report_target(content_type, object_id)
    if target is None:
        messages.error(request, 'The content you are trying to report could not be found.')
        return redirect('main:home_view')

    def get_safe_next(url):
        """Return a safe local path, stripping host if needed. Falls back to '/'."""
        if not url:
            return '/'
        parsed = urlparse(url)
        path = parsed.path or '/'
        return path if path.startswith('/') else '/'

    cutoff = timezone.now() - datetime.timedelta(hours=24)

    if request.method == 'POST':
        next_url = get_safe_next(request.POST.get('next', '/'))

        existing = Report.objects.filter(
            reporter=request.user,
            content_type=content_type,
            created_at__gte=cutoff,
            **{field_name: target},
        ).exists()
        if existing:
            messages.warning(request, 'You have already submitted a report on this content recently. Please wait before reporting again.')
            return redirect(next_url)

        form = ReportForm(request.POST)
        if form.is_valid():
            report = form.save(commit=False)
            report.reporter = request.user
            report.content_type = content_type
            setattr(report, field_name, target)
            report.save()

            from notification.utils import notify
            from django.contrib.auth.models import User as AuthUser
            for staff_user in AuthUser.objects.filter(is_staff=True):
                notify(
                    recipient=staff_user,
                    notif_type='report_received',
                    title='New report submitted',
                    body=f'{request.user.username} reported a {content_type.replace("_", " ")}.',
                    link='/staff/reports/',
                )

            messages.success(request, 'Your report has been submitted. Our team will review it shortly.')
            return redirect(next_url)
    else:
        next_url = get_safe_next(request.META.get('HTTP_REFERER', '/'))

        existing = Report.objects.filter(
            reporter=request.user,
            content_type=content_type,
            created_at__gte=cutoff,
            **{field_name: target},
        ).exists()
        if existing:
            messages.warning(request, 'You have already submitted a report on this content recently. Please wait before reporting again.')
            return redirect(next_url)

        form = ReportForm()

    return render(request, 'staff/report_form.html', {
        'form': form,
        'content_type': content_type,
        'target': target,
        'next': next_url,
    })


@login_required
def my_reports_view(request: HttpRequest):
    reports = Report.objects.filter(reporter=request.user).order_by('-created_at')
    return render(request, 'staff/my_reports.html', {'reports': reports})


@staff_required
def report_list_view(request: HttpRequest):
    status_filter = request.GET.get('status', Report.Status.PENDING)
    reports = Report.objects.filter(status=status_filter).select_related('reporter').order_by('-created_at')
    return render(request, 'staff/report_list.html', {
        'reports': reports,
        'status_filter': status_filter,
        'status_choices': Report.Status.choices,
    })


@staff_required
@require_POST
def resolve_report_view(request: HttpRequest, report_id: int):
    report = get_object_or_404(Report, pk=report_id)
    action = request.POST.get('action', '')
    resolution_note = request.POST.get('resolution_note', '').strip()

    if action not in (Report.Status.RESOLVED, Report.Status.DISMISSED, Report.Status.REVIEWED):
        messages.error(request, 'Invalid action.')
        return redirect('staff:report_list_view')

    report.status = action
    report.resolution_note = resolution_note
    report.reviewed_by = request.user
    report.reviewed_at = timezone.now()
    report.save()

    # Notify the reporter
    if report.reporter:
        from notification.utils import notify
        status_label = report.get_status_display()
        notify(
            recipient=report.reporter,
            notif_type='report_status_update',
            title=f'Your report has been {status_label.lower()}',
            body=resolution_note or 'The moderation team has reviewed your report.',
            link='/account/my-reports/',
        )

    messages.success(request, f'Report marked as {report.get_status_display()}.')
    return redirect('staff:report_list_view')


# ── Dispute management (staff only) ──────────────────────────────────────────

def _staff_validate_image(image_file):
    if not image_file:
        return None, None
    allowed_types = list(getattr(settings, 'REQUEST_IMAGE_ALLOWED_TYPES', ['image/jpeg', 'image/png', 'image/webp', 'image/gif']))
    max_size_bytes = int(float(getattr(settings, 'REQUEST_IMAGE_MAX_SIZE_MB', 5)) * 1024 * 1024)
    from rising_phoenix.moderation import image_is_clean

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


@staff_required
def dispute_list_view(request: HttpRequest):
    from dispute.models import Dispute
    status_filter = request.GET.get('status', Dispute.Status.OPEN)
    disputes = (
        Dispute.objects
        .filter(status=status_filter)
        .select_related('contract__proposal__request', 'contract__proposal__artisan', 'opened_by')
        .order_by('-created_at')
    )
    return render(request, 'staff/dispute_list.html', {
        'disputes': disputes,
        'status_filter': status_filter,
        'status_choices': Dispute.Status.choices,
    })


@staff_required
def dispute_detail_view(request: HttpRequest, dispute_id: int):
    from dispute.models import Dispute, DisputeMessage
    dispute = get_object_or_404(
        Dispute.objects.select_related(
            'contract__proposal__artisan',
            'contract__proposal__request__requester',
            'opened_by',
            'resolved_by',
        ),
        id=dispute_id,
    )

    contract = dispute.contract
    requester = contract.requester
    artisan = contract.artisan

    requester_thread = (
        DisputeMessage.objects.filter(dispute=dispute, party=requester)
        .select_related('sender').order_by('created_at')
    )
    artisan_thread = (
        DisputeMessage.objects.filter(dispute=dispute, party=artisan)
        .select_related('sender').order_by('created_at')
    )

    conversation = getattr(contract.proposal, 'conversation', None)
    party_chat = conversation.messages.select_related('sender').order_by('created_at') if conversation else []

    progress_updates = (
        contract.updates
        .prefetch_related('images', 'comments__author', 'comments__images')
        .order_by('created_at')
    )

    return render(request, 'staff/dispute_detail.html', {
        'dispute': dispute,
        'contract': contract,
        'requester': requester,
        'artisan': artisan,
        'requester_thread': requester_thread,
        'artisan_thread': artisan_thread,
        'party_chat': party_chat,
        'progress_updates': progress_updates,
    })


@staff_required
@require_POST
def staff_dispute_message_view(request: HttpRequest, dispute_id: int, party_id: int):
    from dispute.models import Dispute, DisputeMessage
    from notification.models import Notification
    from notification.utils import notify
    from rising_phoenix.moderation import text_is_clean

    dispute = get_object_or_404(Dispute, id=dispute_id)

    if not dispute.is_open:
        messages.error(request, 'This dispute is already resolved.')
        return redirect('staff:dispute_detail_view', dispute_id=dispute.id)

    contract = dispute.contract
    if party_id == contract.requester.id:
        party = contract.requester
    elif party_id == contract.artisan.id:
        party = contract.artisan
    else:
        messages.error(request, 'That user is not a party to this dispute.')
        return redirect('staff:dispute_detail_view', dispute_id=dispute.id)

    body = (request.POST.get('body') or '').strip()
    image = request.FILES.get('image')

    if not body and not image:
        messages.error(request, 'Please write a message or attach an image.')
        return redirect('staff:dispute_detail_view', dispute_id=dispute.id)
    if body and not text_is_clean(body):
        messages.error(request, 'Your message contains inappropriate language. Please revise it.')
        return redirect('staff:dispute_detail_view', dispute_id=dispute.id)

    cleaned_image, image_error = _staff_validate_image(image)
    if image_error:
        messages.error(request, image_error)
        return redirect('staff:dispute_detail_view', dispute_id=dispute.id)

    DisputeMessage.objects.create(
        dispute=dispute,
        party=party,
        sender=request.user,
        body=body,
        image=cleaned_image,
    )

    notify(
        party,
        Notification.NotifType.DISPUTE_MESSAGE_RECEIVED,
        'New message from the staff on your dispute',
        body=body[:120] if body else 'Sent an image',
        link=reverse('dispute:dispute_detail_view', kwargs={'dispute_id': dispute.id}),
    )

    messages.success(request, f'Message sent to {party.username}.')
    return redirect('staff:dispute_detail_view', dispute_id=dispute.id)


@staff_required
@require_POST
def resolve_dispute_view(request: HttpRequest, dispute_id: int):
    from dispute.models import Dispute
    from notification.models import Notification
    from notification.utils import notify

    dispute = get_object_or_404(Dispute, id=dispute_id)
    action = request.POST.get('action', '')
    resolution_note = (request.POST.get('resolution_note') or '').strip()

    if action not in (Dispute.Status.IN_REVIEW, Dispute.Status.RESOLVED, Dispute.Status.DISMISSED):
        messages.error(request, 'Invalid action.')
        return redirect('staff:dispute_detail_view', dispute_id=dispute.id)

    dispute.status = action
    dispute.resolution_note = resolution_note
    if action in (Dispute.Status.RESOLVED, Dispute.Status.DISMISSED):
        dispute.resolved_by = request.user
        dispute.resolved_at = timezone.now()
    dispute.save()

    contract = dispute.contract
    status_label = dispute.get_status_display()
    link = reverse('dispute:dispute_detail_view', kwargs={'dispute_id': dispute.id})
    for party in (contract.requester, contract.artisan):
        notify(
            party,
            Notification.NotifType.DISPUTE_STATUS_UPDATE,
            f'Your dispute has been {status_label.lower()}',
            body=resolution_note or 'The moderation team has updated your dispute status.',
            link=link,
        )

    messages.success(request, f'Dispute marked as {status_label}.')
    return redirect('staff:dispute_list_view')
