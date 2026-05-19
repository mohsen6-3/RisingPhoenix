from decimal import Decimal

from django.shortcuts import get_object_or_404, render, redirect
from .forms import CustomUserCreationForm, ProfileForm, ArtisanProfileForm, CustomUserUpdateForm, ReviewForm
from django.http import HttpRequest, HttpResponse
from django.contrib import messages
from django.db import transaction
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from .models import Profile, ArtisanProfile, Review, ArtisanRevenue
from django.contrib.auth.models import Group, User
from django.db.models import Avg, Sum, Count, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone
import datetime
import calendar
from twilio.rest import Client
from django.conf import settings
from django.contrib.auth.forms import PasswordResetForm
from notification.utils import send_welcome_email, send_artisan_welcome_email
import stripe
from django.urls import reverse
from progress.models import Contract
from django.core.paginator import Paginator
from request.models import Request
from staff.views import submit_report_view, my_reports_view  # re-export for account URLs
# Create your views here.

stripe.api_key = settings.STRIPE_SECRET_KEY


def signup_view(request: HttpRequest):
    if request.user.is_authenticated:
        return redirect('main:home_view')

    if request.method == 'POST':
        user_form = CustomUserCreationForm(request.POST)
        profile_form = ProfileForm(request.POST, request.FILES)

        if user_form.is_valid() and profile_form.is_valid():
            with transaction.atomic():
                new_user = user_form.save()
                profile = profile_form.save(commit=False)
                profile.user = new_user

                selected_default_avatar = request.POST.get('default_avatar')

                if not request.FILES.get('avatar') and selected_default_avatar:
                    profile.avatar = f'images/avatars/defaults/{selected_default_avatar}'

                profile.save()
                messages.success(request, "You have been register")

            send_welcome_email(new_user)
            return redirect('account:login_view')
        else:
            print(user_form.errors)
            print(profile_form.errors)
            messages.error(request, "something goes Wrong")
            return render(request, 'account/signup.html', {
                'user_form': user_form,
                'profile_form': profile_form,
                'default_avatar_choices': [
                    'avatar1.png',
                    'avatar2.png',
                    'avatar3.png',
                    'avatar4.png',
                ]
            })

    return render(request, 'account/signup.html', {
        'user_form': CustomUserCreationForm(),
        'profile_form': ProfileForm(),
        'default_avatar_choices': [
            'avatar1.png',
            'avatar2.png',
            'avatar3.png',
            'avatar4.png',
        ]
    })


def artisan_signup_view(request:HttpRequest):
    if request.user.is_authenticated:
        return redirect('main:home_view')
    if request.method == 'POST':
        user_form = CustomUserCreationForm(request.POST)
        profile_form = ArtisanProfileForm(request.POST,request.FILES)
        if user_form.is_valid() and profile_form.is_valid():
            with transaction.atomic():
                new_user = user_form.save()
                artisan_group, create = Group.objects.get_or_create(name='artisan')
                new_user.groups.add(artisan_group)
                profile = profile_form.save(commit=False)
                profile.user = new_user

                selected_default_avatar = request.POST.get('default_avatar')

                if not request.FILES.get('avatar') and selected_default_avatar:
                    profile.avatar = f'images/avatars/defaults/{selected_default_avatar}'


                profile.save()
                messages.success(request, "You have been register")
            send_artisan_welcome_email(new_user)
            return redirect('account:login_view')
        else:
            print(user_form.errors)
            messages.error(request, "something goes Wrong")
            return render(request, 'account/artisan_signup.html', {'user_form': user_form, 'profile_form': profile_form,
                'default_avatar_choices': [
                    'avatar1.png',
                    'avatar2.png',
                    'avatar3.png',
                    'avatar4.png',
                ]
})
        
    return render(request, 'account/artisan_signup.html',{
        'default_avatar_choices': [
            'avatar1.png',
            'avatar2.png',
            'avatar3.png',
            'avatar4.png',
        ]

    })

        


def login_view(request:HttpRequest):
    if request.user.is_authenticated:
        return redirect('main:home_view')

    if request.method == 'POST':
        user = authenticate(request, username = request.POST['username'], password = request.POST['password'])

        if user:
            login(request,user)
            messages.success(request, "Logged in successufly")
            #redirect to the staff id the user is staff
            if user.is_staff:
                return redirect('staff:staff_dashboard_view')
            if user.groups.filter(name='artisan').exists():
                print('artisan')
                return redirect('account:artisan_dashboard_view')
            return redirect('main:home_view')
        else:
            messages.error(request, "Your Username or Password is wrong, try again")
            
    
    return render(request, 'account/login.html')

def logout_view(request:HttpRequest):
    logout(request)
    #response = redirect(request.GET.get("next"))
    #return response
    return redirect('main:home_view')


def is_artisan(user):
    """Check if user is an artisan."""
    return user.groups.filter(name='artisan').exists()
@login_required(login_url='account:login_view')
@user_passes_test(is_artisan, login_url='main:home_view')
def artisan_dashboard_view(request: HttpRequest):
    artisan = request.user
    now = timezone.now()

    revenues = (
        ArtisanRevenue.objects
        .filter(artisan=artisan)
        .select_related('contract', 'escrow_payment')
        .order_by('-created_at')
    )

    total_earned = revenues.filter(
        status__in=[ArtisanRevenue.Status.EARNED, ArtisanRevenue.Status.PAID]
    ).aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')

    total_paid = revenues.filter(
        status=ArtisanRevenue.Status.PAID
    ).aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')

    current_balance = revenues.filter(
        status=ArtisanRevenue.Status.EARNED
    ).aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')

    this_month_total = revenues.filter(
        created_at__year=now.year,
        created_at__month=now.month,
        status__in=[ArtisanRevenue.Status.EARNED, ArtisanRevenue.Status.PAID]
    ).aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')

    this_month_jobs = revenues.filter(
        created_at__year=now.year,
        created_at__month=now.month,
        status__in=[ArtisanRevenue.Status.EARNED, ArtisanRevenue.Status.PAID]
    ).aggregate(count=Count('id'))['count'] or 0

    recent_revenues = revenues[:10]

    monthly_revenues = (
        revenues.filter(status__in=[ArtisanRevenue.Status.EARNED, ArtisanRevenue.Status.PAID])
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(
            total=Sum('net_amount'),
            jobs=Count('id')
        )
        .order_by('month')
    )

    chart_labels = [item['month'].strftime('%b %Y') for item in monthly_revenues if item['month']]
    chart_totals = [float(item['total'] or 0) for item in monthly_revenues]

    active_requests = Contract.objects.filter(
        proposal__artisan=artisan,
        status=Contract.Status.IN_PROGRESS,
    ).select_related('proposal__request', 'proposal__artisan').order_by('-created_at')

    completed_requests = Contract.objects.filter(
        proposal__artisan=artisan,
        status=Contract.Status.COMPLETED,
    ).select_related('proposal__request', 'proposal__artisan').order_by('-created_at')[:5]

    stripe_connected = False
    stripe_payouts_enabled = False
    stripe_charges_enabled = False
    stripe_details_submitted = False
    stripe_status_message = ''
    stripe_requirements_due = 0

    stripe_account_id = getattr(getattr(artisan, 'artisanprofile', None), 'stripe_connected_account_id', None)

    if stripe_account_id:
        stripe_connected = True
        try:
            stripe_account = stripe.Account.retrieve(stripe_account_id)

            stripe_payouts_enabled = getattr(stripe_account, 'payouts_enabled', False)
            stripe_charges_enabled = getattr(stripe_account, 'charges_enabled', False)
            stripe_details_submitted = getattr(stripe_account, 'details_submitted', False)

            requirements = getattr(stripe_account, 'requirements', None)
            currently_due = getattr(requirements, 'currently_due', []) if requirements else []
            stripe_requirements_due = len(currently_due)
            disabled_reason = getattr(requirements, 'disabled_reason', None) if requirements else None

            if stripe_payouts_enabled:
                stripe_status_message = 'Your Stripe account is connected and ready for payouts.'
            elif disabled_reason == 'requirements.past_due':
                stripe_status_message = 'More information is required to enable payouts.'
            elif disabled_reason == 'requirements.pending_verification':
                stripe_status_message = 'Stripe is reviewing your information.'
            elif disabled_reason:
                stripe_status_message = disabled_reason.replace('.', ' ').replace('_', ' ').title()
            else:
                stripe_status_message = 'Complete your Stripe onboarding to receive payouts.'

        except stripe.error.StripeError:
            stripe_status_message = 'Unable to load Stripe account status right now.'

    context = {
        'total_earned': total_earned,
        'total_paid': total_paid,
        'current_balance': current_balance,
        'this_month_total': this_month_total,
        'this_month_jobs': this_month_jobs,
        'recent_revenues': recent_revenues,
        'monthly_revenues': monthly_revenues,
        'chart_labels': chart_labels,
        'chart_totals': chart_totals,
        'active_requests': active_requests,
        'completed_requests': completed_requests,
        'stripe_connected': stripe_connected,
        'stripe_payouts_enabled': stripe_payouts_enabled,
        'stripe_charges_enabled': stripe_charges_enabled,
        'stripe_details_submitted': stripe_details_submitted,
        'stripe_status_message': stripe_status_message,
        'stripe_requirements_due': stripe_requirements_due,
        'page_title': 'Earnings Dashboard',
    }

    return render(request, 'account/artisan_dashboard.html', context)

def profile_view(request:HttpRequest, user_name):
    user = get_object_or_404(User, username = user_name)
    if user.is_staff:
        return redirect('staff:staff_profile_view')
    if user.groups.filter(name='artisan').exists():
        messages.warning(request, 'Your are not allowed')
        return redirect('main:home_view')
    user_profile = get_object_or_404(Profile, user=user)
    user_reviews = user.reviews_received.all()
    avg_rating = user_reviews.aggregate(avg_rating=Avg('rating'))['avg_rating']
    return render(request,'account/profile.html',{'user_profile': user_profile, 'user_reviews': user_reviews, 'avg_rating': avg_rating})

def update_profile_view(request:HttpRequest,user_name):
    if request.user.is_staff:
        return redirect('staff:update_staff_profile_view')
    if user_name != request.user.username:
        messages.warning(request,'Your are not allowed')
        return redirect('main:home_view')
    user = User.objects.get(username = user_name)
    if user.is_staff:
        return redirect('staff:update_staff_profile_view')
    if user.groups.filter(name='artisan').exists():
        messages.warning(request, 'Your are not allowed')
        redirect('main:home_view')
    user_profile = get_object_or_404(Profile, user=user)
    if request.method == 'POST':
        user_form = CustomUserUpdateForm(request.POST,instance=request.user)
        profile_form = ProfileForm(request.POST,request.FILES,instance=user_profile)
        if user_form.is_valid() and profile_form.is_valid():
            with transaction.atomic():
                user_form.save()

                profile = profile_form.save(commit=False)

                if 'phone' in profile_form.changed_data:
                    profile.is_phone_verified = False

                profile.save()

                messages.success(request, "Your profile has been updated")

            return redirect('account:profile_view', user_name=request.user.username)
        else:
            print(user_form.errors)
            messages.error(request, "something goes Wrong")
            return render(request, 'account/update_profile.html', {'user_form': user_form, 'user_profile': user_profile, 'profile_form': profile_form})
    return render(request, 'account/update_profile.html',{'user_profile': user_profile})


def verify_phone_view(request: HttpRequest, user_name):
    if user_name != request.user.username:
        messages.warning(request, 'You are not allowed')
        return redirect('main:home_view')

    user = get_object_or_404(User, username=user_name)
    user_profile = user.profile

    if not user_profile.phone:
        messages.error(request, 'Please add your phone number first.')
        return redirect('account:update_profile_view', user_name=user.username)

    if request.method == 'POST':
        code = request.POST.get('code')

        if not code:
            messages.error(request, 'Please enter the verification code.')
            return render(request, 'account/verify_phone.html', {
                'user_profile': user_profile
            })

        try:
            client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
            verification_check = client.verify.v2.services(
                settings.TWILIO_VERIFY_SERVICE_SID
            ).verification_checks.create(
                to=str(user_profile.phone),
                code=code
            )

            if verification_check.status == 'approved':
                user_profile.is_phone_verified = True
                user_profile.save()
                messages.success(request, 'Your phone number has been verified successfully.')
                return redirect('account:profile_view', user_name=user.username)
            else:
                messages.error(request, 'Invalid verification code.')
        except Exception as e:
            messages.error(request, 'Verification failed. Please try again.')

    return render(request, 'account/verified_phone.html', {
        'user_profile': user_profile
    })


def send_phone_verification_view(request: HttpRequest, user_name):
    if user_name != request.user.username:
        messages.warning(request, 'You are not allowed')
        return redirect('main:home_view')

    user = get_object_or_404(User, username=user_name)
    user_profile = user.profile

    if not user_profile.phone:
        messages.error(request, 'Please add your phone number first.')
        return redirect('account:update_profile_view', user_name=user.username)

    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.verify.v2.services(settings.TWILIO_VERIFY_SERVICE_SID).verifications.create(
            to=str(user_profile.phone),
            channel='sms'
        )
        messages.success(request, 'Verification code sent to your phone.')
        return redirect('account:verify_phone_view', user_name=user.username)
    except Exception as e:
        print(e)
        messages.error(request, 'Failed to send verification code.')
        return redirect('account:profile_view', user_name=user.username)


@login_required(login_url='account:login_view')
def submit_review_view(request: HttpRequest, contract_id):
    from progress.models import Contract
    contract = get_object_or_404(
        Contract.objects.select_related('proposal__artisan', 'proposal__request__requester'),
        id=contract_id,
    )

    if request.user != contract.requester:
        messages.warning(request, 'You are not allowed to review this project.')
        return redirect('main:home_view')

    if not contract.is_completed:
        messages.warning(request, 'You can only leave a review after the project is completed.')
        return redirect('progress:contract_detail_view', contract_id=contract_id)

    request_obj = contract.proposal.request
    if hasattr(request_obj, 'review'):
        messages.warning(request, 'You have already submitted a review for this project.')
        return redirect('workshop:workshop_detail_view', artisan_id=contract.artisan.id)

    if request.method == 'POST':
        form = ReviewForm(request.POST)
        if form.is_valid():
            review = form.save(commit=False)
            review.request = request_obj
            review.reviews_given = request.user
            review.reviews_received = contract.artisan
            review.save()
            messages.success(request, 'Your review has been submitted. Thank you!')
            return redirect('workshop:workshop_detail_view', artisan_id=contract.artisan.id)
    else:
        form = ReviewForm()

    return render(request, 'account/submit_review.html', {
        'form': form,
        'contract': contract,
    })


@login_required(login_url='account:login_view')
def review_history_view(request: HttpRequest):
    reviews = request.user.reviews_given.select_related(
        'request', 'reviews_received'
    ).order_by('-created_at')
    return render(request, 'account/review_history.html', {'reviews': reviews})


def password_reset_view(request: HttpRequest):
    if request.method == 'POST':
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            form.save(
                request=request,
                use_https=request.is_secure(),
                from_email=None,
                email_template_name='account/password_reset_email.html',
                subject_template_name='account/password_reset_subject.txt',
            )
            messages.success(request, "Password reset email sent.")
            return redirect('account:password_reset_done')
    else:
        form = PasswordResetForm()

    return render(request, 'account/password_reset.html', {'form': form})

@login_required(login_url='account:login_view')
@user_passes_test(is_artisan, login_url='main:home_view')
def completed_orders_view(request):
    from proposal.models import Proposal

    completed_requests = (
        Request.objects.filter(
            status=Request.Status.CLOSED,
            proposals__artisan=request.user,
            proposals__status=Proposal.Status.ACCEPTED,
        )
        .distinct()
        .order_by('-created_at')
    )

    paginator = Paginator(
        completed_requests,
        6
    )

    page_number = request.GET.get('page')

    page_obj = paginator.get_page(
        page_number
    )

    return render(
        request,
        'account/completed_orders.html',
        {
            'requests': page_obj,
            'page_obj': page_obj
        }
    )


@login_required
def artisan_revenue_dashboard_view(request):
    artisan = request.user
    now = timezone.now()

    revenues = (
        ArtisanRevenue.objects
        .filter(artisan=artisan)
        .select_related('contract', 'escrow_payment')
        .order_by('-created_at')
    )

    total_earned = revenues.filter(
        status__in=[ArtisanRevenue.Status.EARNED, ArtisanRevenue.Status.PAID]
    ).aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')

    total_paid = revenues.filter(
        status=ArtisanRevenue.Status.PAID
    ).aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')

    current_balance = revenues.filter(
        status=ArtisanRevenue.Status.EARNED
    ).aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')

    this_month_total = revenues.filter(
        created_at__year=now.year,
        created_at__month=now.month,
        status__in=[ArtisanRevenue.Status.EARNED, ArtisanRevenue.Status.PAID]
    ).aggregate(total=Sum('net_amount'))['total'] or Decimal('0.00')

    this_month_jobs = revenues.filter(
        created_at__year=now.year,
        created_at__month=now.month,
        status__in=[ArtisanRevenue.Status.EARNED, ArtisanRevenue.Status.PAID]
    ).aggregate(count=Count('id'))['count'] or 0

    recent_revenues = revenues[:10]

    monthly_revenues = (
        revenues.filter(status__in=[ArtisanRevenue.Status.EARNED, ArtisanRevenue.Status.PAID])
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(
            total=Sum('net_amount'),
            jobs=Count('id')
        )
        .order_by('month')
    )

    chart_labels = [item['month'].strftime('%b %Y') for item in monthly_revenues if item['month']]
    chart_totals = [float(item['total'] or 0) for item in monthly_revenues]

    active_requests = Contract.objects.filter(
        proposal__artisan=artisan,
        status=Contract.Status.IN_PROGRESS,
    ).select_related('proposal__request', 'proposal__artisan').order_by('-created_at')

    completed_requests = Contract.objects.filter(
        proposal__artisan=artisan,
        status=Contract.Status.COMPLETED,
    ).select_related('proposal__request', 'proposal__artisan').order_by('-created_at')[:5]

    context = {
        'total_earned': total_earned,
        'total_paid': total_paid,
        'current_balance': current_balance,
        'this_month_total': this_month_total,
        'this_month_jobs': this_month_jobs,
        'recent_revenues': recent_revenues,
        'monthly_revenues': monthly_revenues,
        'chart_labels': chart_labels,
        'chart_totals': chart_totals,
        'active_requests': active_requests,
        'completed_requests': completed_requests,
        'page_title': 'Earnings Dashboard',
    }
    return render(request, 'account/artisan_revenue_dashboard.html', context)



@login_required
def artisan_connect_stripe_view(request):
    try:
        profile = request.user.artisanprofile
    except ArtisanProfile.DoesNotExist:
        messages.error(request, 'Artisan profile not found.')
        return redirect('main:home_view')

    try:
        account = None

        if profile.stripe_connected_account_id:
            try:
                account = stripe.Account.retrieve(profile.stripe_connected_account_id)
            except stripe.error.InvalidRequestError:
                profile.stripe_connected_account_id = None
                profile.save(update_fields=['stripe_connected_account_id'])

        if not account:
            account = stripe.Account.create(
                type='express',
                country='SA',
                email=request.user.email or None,
                capabilities={
                    'transfers': {'requested': True},
                },
                tos_acceptance={
                    'service_agreement': 'recipient',
                },
                metadata={
                    'user_id': str(request.user.id),
                    'username': request.user.username,
                }
            )
            profile.stripe_connected_account_id = account.id
            profile.save(update_fields=['stripe_connected_account_id'])

        account_link = stripe.AccountLink.create(
            account=account.id,
            refresh_url=request.build_absolute_uri(
                reverse('account:artisan_connect_stripe_refresh_view')
            ),
            return_url=request.build_absolute_uri(
                reverse('account:artisan_connect_stripe_return_view')
            ),
            type='account_onboarding',
        )

        return redirect(account_link.url)

    except stripe.error.StripeError as e:
        messages.error(request, str(e))
        return redirect('account:artisan_dashboard_view')


@login_required
def artisan_connect_stripe_refresh_view(request):
    try:
        profile = request.user.artisanprofile
    except ArtisanProfile.DoesNotExist:
        messages.error(request, 'Artisan profile not found.')
        return redirect('main:home_view')

    if not profile.stripe_connected_account_id:
        messages.error(request, 'Stripe connected account not found.')
        return redirect('account:artisan_dashboard_view')

    try:
        account_link = stripe.AccountLink.create(
            account=profile.stripe_connected_account_id,
            refresh_url=request.build_absolute_uri(
                reverse('account:artisan_connect_stripe_refresh_view')
            ),
            return_url=request.build_absolute_uri(
                reverse('account:artisan_connect_stripe_return_view')
            ),
            type='account_onboarding',
        )
        return redirect(account_link.url)

    except stripe.error.StripeError as e:
        messages.error(request, str(e))
        return redirect('account:artisan_dashboard_view')

@login_required
def artisan_connect_stripe_return_view(request):
    try:
        profile = request.user.artisanprofile
    except ArtisanProfile.DoesNotExist:
        messages.error(request, 'Artisan profile not found.')
        return redirect('main:home_view')

    if not profile.stripe_connected_account_id:
        messages.error(request, 'Stripe connected account not found.')
        return redirect('account:artisan_dashboard_view')

    try:
        account = stripe.Account.retrieve(profile.stripe_connected_account_id)

        if account.details_submitted and account.payouts_enabled:
            messages.success(request, 'Stripe payout setup completed successfully.')
        elif account.details_submitted:
            messages.warning(
                request,
                'Your Stripe account details were submitted, but payouts are not enabled yet.'
            )
        else:
            messages.warning(
                request,
                'Stripe onboarding is not complete yet. Please finish the required details.'
            )

    except stripe.error.StripeError as e:
        messages.error(request, str(e))

    return redirect('account:artisan_dashboard_view')


