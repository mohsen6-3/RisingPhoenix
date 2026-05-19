from io import BytesIO

from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string


def generate_contract_pdf_bytes(contract):
    from weasyprint import HTML

    proposal = contract.proposal
    project_request = proposal.request

    html_string = render_to_string('payment/contract_pdf.html', {
        'contract': contract,
        'proposal': proposal,
        'project_request': project_request,
    })

    pdf_bytes = HTML(string=html_string, base_url=settings.BASE_DIR).write_pdf()
    return pdf_bytes


def send_contract_pdf_email(contract):
    proposal = contract.proposal
    project_request = proposal.request

    pdf_bytes = generate_contract_pdf_bytes(contract)

    recipients = [
        project_request.requester.email,
        proposal.artisan.email,
    ]
    recipients = [email for email in recipients if email]

    if not recipients:
        return

    email = EmailMessage(
        subject=f'Contract #{contract.id} accepted',
        body=(
            f'The contract for "{project_request.title}" has been accepted.\n\n'
            f'Please find the signed contract attached as a PDF.'
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipients,
    )
    email.attach(
        f'contract-{contract.id}.pdf',
        pdf_bytes,
        'application/pdf'
    )
    email.send(fail_silently=False)