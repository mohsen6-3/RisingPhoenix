from django import forms

from .models import Dispute, DisputeMessage


class DisputeForm(forms.ModelForm):
    class Meta:
        model = Dispute
        fields = ['reason', 'description']
        widgets = {
            'reason': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 5,
                'placeholder': 'Describe the issue in detail. Include any context that will help staff understand the problem...',
            }),
        }
        labels = {
            'reason': 'Reason for dispute',
            'description': 'What is the issue?',
        }


class DisputeMessageForm(forms.ModelForm):
    class Meta:
        model = DisputeMessage
        fields = ['body', 'image']
        widgets = {
            'body': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Write your message to the staff...',
            }),
            'image': forms.ClearableFileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*',
            }),
        }
        labels = {
            'body': 'Message',
            'image': 'Attach image (optional)',
        }


class DisputeResolutionForm(forms.Form):
    ACTION_CHOICES = [
        (Dispute.Status.IN_REVIEW, 'Mark Under Review'),
        (Dispute.Status.RESOLVED,  'Resolve'),
        (Dispute.Status.DISMISSED, 'Dismiss'),
    ]
    action = forms.ChoiceField(choices=ACTION_CHOICES, widget=forms.Select(attrs={'class': 'form-select'}))
    resolution_note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Explain the outcome...'}),
    )
