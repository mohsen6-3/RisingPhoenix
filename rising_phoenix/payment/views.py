from datetime import timedelta
from django.utils import timezone
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from notification.utils import notify
from .models import StripeCustomer, PaymentMethod, EscrowPayment
from django.conf import settings
from django.contrib import messages
import stripe
from request.models import Request
from proposal.models import Proposal
from django.db import transaction
from progress.models import Contract, ContractEvent
from notification.models import Notification
from .services import process_monthly_artisan_payouts
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
import logging
from .utils import send_contract_pdf_email
from message.models import Conversation

# Create your views here.

stripe.api_key = settings.STRIPE_SECRET_KEY



def my_cards_view(request):

    cards = PaymentMethod.objects.filter(user=request.user).order_by('-is_default', '-created_at')
    return render(request, 'payment/my_cards.html', {'cards': cards})

def get_or_create_stripe_customer(user):
    customer_obj, created = StripeCustomer.objects.get_or_create(user=user)

    if customer_obj.stripe_customer_id:
        return customer_obj.stripe_customer_id

    customer = stripe.Customer.create(
        email=user.email,
        name=user.username
    )
    customer_obj.stripe_customer_id = customer.id
    customer_obj.save()
    return customer.id



def add_card_view(request):

    stripe_customer_id = get_or_create_stripe_customer(request.user)
    setup_intent = stripe.SetupIntent.create(
        customer=stripe_customer_id,
        payment_method_types=['card'],
        usage='off_session'
    )

    return render(request, 'payment/add_card.html', {
        'client_secret': setup_intent.client_secret,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
    })

@require_POST
def remove_card_view(request, card_id):
    card = get_object_or_404(
        PaymentMethod,
        id=card_id,
        user=request.user,
    )
    
    try:
        stripe.PaymentMethod.detach(card.stripe_payment_method_id)
    except stripe.error.StripeError:
        messages.error(request, 'Could not remove this card right now. Please try again.')
        return redirect('payment:my_cards')

    was_default = card.is_default
    user = card.user
    card.delete()

    if was_default:
        next_card = user.payment_methods.order_by('-created_at').first()
        if next_card:
            next_card.is_default = True
            next_card.save(update_fields=['is_default'])

    messages.success(request, 'Card removed successfully.')
    return redirect('payment:my_cards')



def save_card_success(request):

    setup_intent_id = request.GET.get('setup_intent')
    if not setup_intent_id:
        return redirect('payment:add_card')

    setup_intent = stripe.SetupIntent.retrieve(setup_intent_id)
    payment_method_id = setup_intent.payment_method
    stripe_customer_id = setup_intent.customer
    payment_method = stripe.PaymentMethod.retrieve(payment_method_id)

    obj, created = PaymentMethod.objects.get_or_create(
        stripe_payment_method_id=payment_method_id,
        defaults={
            'user': request.user,
            'stripe_customer_id': stripe_customer_id,
            'brand': payment_method.card.brand,
            'last4': payment_method.card.last4,
            'exp_month': payment_method.card.exp_month,
            'exp_year': payment_method.card.exp_year,
            'is_default': not PaymentMethod.objects.filter(user=request.user).exists(),
        }
    )

    return redirect('payment:my_cards')


def proposal_checkout_view(request, proposal_id):
    proposal = get_object_or_404(
        Proposal.objects.select_related('request', 'artisan'),
        id=proposal_id
    )
    project_request = proposal.request

    if project_request.requester != request.user:
        messages.error(request, 'Only the requester can pay for this proposal.')
        return redirect('request:request_detail_view', request_id=project_request.id)

    if not proposal.is_pending:
        messages.error(request, 'This proposal is no longer pending.')
        return redirect('request:request_detail_view', request_id=project_request.id)

    if project_request.status == Request.Status.CLOSED:
        messages.error(request, 'This request is already closed.')
        return redirect('request:request_detail_view', request_id=project_request.id)

    cards = request.user.payment_methods.all().order_by('-is_default', '-created_at')

    context = {
        'proposal': proposal,
        'project_request': project_request,
        'cards': cards,
        'default_card': cards.filter(is_default=True).first(),
    }
    return render(request, 'payment/proposal_checkout.html', context)


def artisan_contract_review_view(request, contract_id):
    contract = get_object_or_404(
        Contract.objects.select_related(
            'proposal',
            'proposal__request',
            'proposal__artisan',
            'proposal__request__requester',
            'escrow_payment',
        ).prefetch_related(
            'proposal__images',
            'proposal__request__images',
        ),
        id=contract_id
    )

    if request.user != contract.artisan:
        messages.error(request, 'Only the artisan can review this contract.')
        return redirect('request:request_detail_view', request_id=contract.proposal.request.id)

    if contract.status == Contract.Status.CANCELED:
        messages.error(request, 'This contract has been canceled.')
        return redirect('progress:contract_detail_view', contract_id=contract.id)

    if contract.status == Contract.Status.COMPLETED:
        messages.info(request, 'This contract has already been completed.')
        return redirect('progress:contract_detail_view', contract_id=contract.id)

    if not contract.requester_accepted_at:
        messages.error(request, 'The requester has not accepted this contract yet.')
        return redirect('request:request_detail_view', request_id=contract.proposal.request.id)

    escrow_payment = getattr(contract, 'escrow_payment', None)
    if not escrow_payment or escrow_payment.status != 'authorized' or escrow_payment.captured:
        messages.error(request, 'This contract does not have a valid authorized payment hold.')
        return redirect('request:request_detail_view', request_id=contract.proposal.request.id)

    context = {
        'contract': contract,
        'proposal': contract.proposal,
        'project_request': contract.proposal.request,
        'escrow_payment': escrow_payment,
    }
    return render(request, 'payment/artisan_contract_review.html', context)



def confirm_proposal_payment_view(request, proposal_id):
    proposal = get_object_or_404(
        Proposal.objects.select_related('request', 'artisan'),
        id=proposal_id
    )
    project_request = proposal.request

    if project_request.requester != request.user:
        messages.error(request, 'Only the requester can pay for this proposal.')
        return redirect('request:request_detail_view', request_id=project_request.id)

    if proposal.status != Proposal.Status.PENDING:
        messages.error(request, 'This proposal is no longer available for payment.')
        return redirect('request:request_detail_view', request_id=project_request.id)

    payment_method_id = request.POST.get('payment_method')
    if not payment_method_id:
        messages.error(request, 'Please select a payment method.')
        return redirect('payment:proposal_checkout_view', proposal_id=proposal.id)

    stripe_customer = getattr(request.user, 'stripe_customer', None)
    if not stripe_customer:
        messages.error(request, 'Please add a card first.')
        return redirect('payment:add_card')

    selected_card = request.user.payment_methods.filter(
        stripe_payment_method_id=payment_method_id
    ).first()

    if not selected_card:
        messages.error(request, 'Selected payment method is invalid.')
        return redirect('payment:proposal_checkout_view', proposal_id=proposal.id)

    amount_in_halalas = int(Decimal(proposal.price) * 100)

    try:
        payment_intent = stripe.PaymentIntent.create(
            amount=amount_in_halalas,
            currency='sar',
            customer=stripe_customer.stripe_customer_id,
            payment_method=selected_card.stripe_payment_method_id,
            confirm=True,
            off_session=True,
            capture_method='manual',
            metadata={
                'proposal_id': str(proposal.id),
                'request_id': str(project_request.id),
                'requester_id': str(request.user.id),
                'artisan_id': str(proposal.artisan.id),
            }
        )
    except stripe.error.CardError as e:
        messages.error(request, e.user_message or 'Your card was declined.')
        return redirect('payment:proposal_checkout_view', proposal_id=proposal.id)
    except stripe.error.StripeError:
        messages.error(request, 'Unable to process payment right now.')
        return redirect('payment:proposal_checkout_view', proposal_id=proposal.id)

    if payment_intent.status != 'requires_capture':
        messages.error(request, f'Payment authorization failed. Status: {payment_intent.status}')
        return redirect('payment:proposal_checkout_view', proposal_id=proposal.id)

    with transaction.atomic():
        proposal.status = Proposal.Status.CONTRACT_APPROVAL
        proposal.save(update_fields=['status', 'updated_at'])

        rejected_artisans = list(
            project_request.proposals
            .filter(status=Proposal.Status.PENDING)
            .exclude(id=proposal.id)
            .values_list('artisan', flat=True)
        )

        project_request.proposals.filter(
            status=Proposal.Status.PENDING
        ).exclude(id=proposal.id).update(
            status=Proposal.Status.REJECTED
        )

        contract, created = Contract.objects.get_or_create(
            proposal=proposal,
            defaults={
                'status': Contract.Status.PENDING_ARTISAN,
                'requester_accepted_at': timezone.now(),
            }
        )

        if not created:
            contract.requester_accepted_at = timezone.now()
            contract.status = Contract.Status.PENDING_ARTISAN
            contract.save(update_fields=['requester_accepted_at', 'status', 'updated_at'])

        EscrowPayment.objects.create(
            requester=request.user,
            proposal=proposal,
            contract=contract,
            stripe_payment_intent_id=payment_intent.id,
            stripe_customer_id=stripe_customer.stripe_customer_id,
            stripe_payment_method_id=selected_card.stripe_payment_method_id,
            amount=proposal.price,
            currency='sar',
            status='authorized',
            captured=False,
        )

    for artisan in get_user_model().objects.filter(id__in=rejected_artisans):
        notify(
            artisan,
            Notification.NotifType.PROPOSAL_REJECTED,
            'Your proposal was not selected',
            body=f'The requester went with another proposal for "{project_request.title}". Good luck with your other proposals!',
            link=reverse('request:request_detail_view', kwargs={'request_id': project_request.id}),
        )

    notify(
        proposal.artisan,
        Notification.NotifType.PROPOSAL_ACCEPTED,
        'Contract awaiting your approval',
        body=f'The requester selected your proposal for "{project_request.title}" and authorized the payment hold. Please review and accept the contract.',
        link=reverse('progress:contract_detail_view', kwargs={'contract_id': contract.id}),
    )

    messages.success(request, 'Payment authorized successfully. The contract was sent to the artisan for approval.')
    return redirect('progress:contract_detail_view', contract_id=contract.id)





def artisan_accept_contract_view(request, contract_id):
    contract = get_object_or_404(
        Contract.objects.select_related(
            'proposal',
            'proposal__request',
            'proposal__artisan',
            'proposal__request__requester',
            'proposal__request__category',
            'escrow_payment',
        ),
        id=contract_id
    )

    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('payment:artisan_contract_review_view', contract_id=contract.id)

    if request.user != contract.artisan:
        messages.error(request, 'Only the artisan can accept this contract.')
        return redirect('request:request_detail_view', request_id=contract.proposal.request.id)

    if contract.status == Contract.Status.COMPLETED:
        messages.info(request, 'This contract has already been completed.')
        return redirect('progress:contract_detail_view', contract_id=contract.id)

    if contract.status == Contract.Status.CANCELED:
        messages.error(request, 'This contract has been canceled.')
        return redirect('request:request_detail_view', request_id=contract.proposal.request.id)

    if not contract.requester_accepted_at:
        messages.error(request, 'The requester must accept the contract first.')
        return redirect('payment:artisan_contract_review_view', contract_id=contract.id)

    if contract.artisan_accepted_at:
        messages.info(request, 'You already accepted this contract.')
        return redirect('progress:contract_detail_view', contract_id=contract.id)

    if contract.status != Contract.Status.PENDING_ARTISAN:
        messages.error(request, 'This contract is not waiting for artisan acceptance.')
        return redirect('request:request_detail_view', request_id=contract.proposal.request.id)

    escrow_payment = getattr(contract, 'escrow_payment', None)
    if not escrow_payment:
        messages.error(request, 'No authorized escrow payment was found for this contract.')
        return redirect('payment:artisan_contract_review_view', contract_id=contract.id)

    if escrow_payment.status != 'authorized' or escrow_payment.captured:
        messages.error(request, 'This escrow payment is not in a valid authorized state.')
        return redirect('payment:artisan_contract_review_view', contract_id=contract.id)

    expires_at = escrow_payment.created_at + timedelta(days=7)
    if timezone.now() > expires_at:
        try:
            stripe.PaymentIntent.cancel(
                escrow_payment.stripe_payment_intent_id,
                cancellation_reason='abandoned',
            )
        except stripe.error.StripeError:
            pass

        escrow_payment.status = 'canceled'
        escrow_payment.save(update_fields=['status', 'updated_at'])

        contract.status = Contract.Status.CANCELED
        contract.save(update_fields=['status', 'updated_at'])

        messages.error(request, 'This payment hold expired after 7 days. The contract can no longer be accepted.')
        return redirect('request:request_detail_view', request_id=contract.proposal.request.id)

    try:
        stripe.PaymentIntent.capture(escrow_payment.stripe_payment_intent_id)
    except stripe.error.StripeError:
        messages.error(request, 'The payment could not be captured. Please try again.')
        return redirect('payment:artisan_contract_review_view', contract_id=contract.id)

    with transaction.atomic():
        contract.artisan_accepted_at = timezone.now()
        contract.status = Contract.Status.IN_PROGRESS
        contract.save(update_fields=['artisan_accepted_at', 'status', 'updated_at'])

        proposal = contract.proposal
        proposal.status = Proposal.Status.ACCEPTED
        proposal.save(update_fields=['status', 'updated_at'])

        escrow_payment.status = 'captured'
        escrow_payment.captured = True
        escrow_payment.save(update_fields=['status', 'captured', 'updated_at'])

    try:
        send_contract_pdf_email(contract)
    except Exception:
        messages.warning(request, 'Contract accepted, but the PDF email could not be sent.')

    messages.success(request, 'Contract accepted and payment captured successfully.')
    return redirect('progress:contract_detail_view', contract_id=contract.id)

def artisan_reject_contract_view(request, contract_id):
    contract = get_object_or_404(
        Contract.objects.select_related('proposal__request', 'escrow_payment'),
        id=contract_id
    )

    if request.method != 'POST':
        messages.error(request, 'Invalid request method.')
        return redirect('payment:artisan_contract_review_view', contract_id=contract.id)

    if request.user != contract.artisan:
        messages.error(request, 'Only the artisan can reject this contract.')
        return redirect('request:request_detail_view', request_id=contract.proposal.request.id)

    escrow_payment = getattr(contract, 'escrow_payment', None)
    if not escrow_payment:
        messages.error(request, 'No escrow payment was found for this contract.')
        return redirect('payment:artisan_contract_review_view', contract_id=contract.id)

    if escrow_payment.status == 'authorized' and not escrow_payment.captured:
        try:
            stripe.PaymentIntent.cancel(
                escrow_payment.stripe_payment_intent_id,
                cancellation_reason='abandoned',
            )
        except stripe.error.StripeError:
            messages.error(request, 'Unable to cancel the payment hold right now.')
            return redirect('payment:artisan_contract_review_view', contract_id=contract.id)

    with transaction.atomic():
        escrow_payment.status = 'canceled'
        escrow_payment.save(update_fields=['status', 'updated_at'])

        contract.status = Contract.Status.CANCELED
        contract.save(update_fields=['status', 'updated_at'])

        proposal = contract.proposal
        proposal.status = Proposal.Status.REJECTED
        proposal.save(update_fields=['status', 'updated_at'])
        conversation = Conversation.objects.filter(proposal=contract.proposal).first()
        if conversation:
            conversation.is_active = False
            conversation.save(update_fields=['is_active'])


    messages.success(request, 'Contract rejected and payment hold canceled.')
    return redirect('request:request_detail_view', request_id=contract.proposal.request.id)

logger = logging.getLogger(__name__)


def _handle_payout_result(request, result):
    try:
        balance = stripe.Balance.retrieve()
        logger.info("Stripe balance: %s", balance)
    except stripe.error.StripeError as e:
        logger.warning("Unable to retrieve Stripe balance: %s", str(e))

    artisan_count = len(result['processed'])
    failed_count = len(result['failed'])

    total_paid_sar = sum(
        (item['total_sar'] for item in result['processed']),
        Decimal('0.00')
    )
    total_paid_usd = sum(
        (item['total_usd'] for item in result['processed']),
        Decimal('0.00')
    )

    period_label = "current month" if result['period_type'] == 'current' else "previous month"

    if artisan_count:
        messages.success(
            request,
            f"{period_label.capitalize()} payout processed for {artisan_count} artisan(s). "
            f"Earned: {total_paid_sar} SAR. Paid out: {total_paid_usd} USD."
        )

    if failed_count:
        for item in result['failed']:
            messages.warning(
                request,
                f"Artisan {item['artisan_username']} payout failed: {item['reason']}"
            )

    if not artisan_count and not failed_count:
        messages.warning(
            request,
            f"No artisan payouts were processed for the {period_label}."
        )

    return redirect('account:artisan_revenue_dashboard_view')


def run_current_month_artisan_payout_view(request):
    result = process_monthly_artisan_payouts(
        target_date=timezone.localdate(),
        period_type='current'
    )
    return _handle_payout_result(request, result)


def run_previous_month_artisan_payout_view(request):
    result = process_monthly_artisan_payouts(
        target_date=timezone.localdate(),
        period_type='previous'
    )
    return _handle_payout_result(request, result)






    
