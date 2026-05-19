import base64
import logging

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils.html import strip_tags

logger = logging.getLogger(__name__)


def notify(recipient, notif_type, title, body='', link=''):
    from .models import Notification, NotificationPreference
    try:
        prefs, _ = NotificationPreference.objects.get_or_create(user=recipient)
        if prefs.wants_insite(notif_type):
            Notification.objects.create(
                recipient=recipient,
                notif_type=notif_type,
                title=title,
                body=body,
                link=link,
            )
        if prefs.wants_email(notif_type):
            _send_notification_email(recipient, title, body, link)
    except Exception:
        logger.exception('notify() failed for %s (%s)', recipient, notif_type)


def send_welcome_email(user):
    email = _get_email(user)
    if not email:
        return
    try:
        context = {'user': user, 'site_url': _site_url()}
        _dispatch(
            to=email,
            subject='Welcome to Saaf',
            template='notification/email/welcome_user.html',
            context=context,
        )
    except Exception:
        logger.exception('Failed to send welcome email to %s', user.username)


def send_artisan_welcome_email(user):
    email = _get_email(user)
    if not email:
        return
    try:
        context = {'user': user, 'site_url': _site_url()}
        _dispatch(
            to=email,
            subject='Welcome to Saaf — Your Artisan Profile is Live',
            template='notification/email/welcome_artisan.html',
            context=context,
        )
    except Exception:
        logger.exception('Failed to send artisan welcome email to %s', user.username)


# ── internals ────────────────────────────────────────────────────────────────

def _site_url():
    return getattr(settings, 'SITE_URL', 'http://127.0.0.1:8000')


def _get_email(recipient):
    if not getattr(settings, 'EMAIL_HOST_USER', None):
        return None
    return getattr(recipient, 'email', '') or None


def _logo_data_uri():
    path = finders.find('images/logo.webp')
    if not path:
        return ''
    with open(path, 'rb') as f:
        data = base64.b64encode(f.read()).decode()
    return f'data:image/webp;base64,{data}'


def _dispatch(*, to, subject, template, context):
    context.setdefault('logo', _logo_data_uri())
    html_message = render_to_string(template, context)
    logger.debug('Sending email "%s" to %s', subject, to)
    send_mail(
        subject=subject,
        message=strip_tags(html_message),
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[to],
        html_message=html_message,
        fail_silently=True,
    )
    logger.debug('Email sent successfully to %s', to)


def _send_notification_email(recipient, title, body, link):
    email = _get_email(recipient)
    if not email:
        return
    try:
        base_url = _site_url()
        context = {
            'recipient': recipient,
            'title': title,
            'body': body,
            'link': base_url + link if link else '',
            'site_url': base_url,
        }
        _dispatch(
            to=email,
            subject=f'Saaf — {title}',
            template='notification/email/notification_email.html',
            context=context,
        )
    except Exception:
        logger.exception('Failed to send notification email to %s', recipient.username)
