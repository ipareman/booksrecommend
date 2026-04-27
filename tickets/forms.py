from django import forms

from .models import Ticket


class TicketCreateForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ["subject", "body", "priority"]
        widgets = {
            "subject": forms.TextInput(attrs={"class": "form-input", "placeholder": "Кратко опишите вопрос"}),
            "body": forms.Textarea(attrs={"class": "form-input", "rows": 6, "placeholder": "Расскажите, что произошло"}),
            "priority": forms.Select(attrs={"class": "form-input"}),
        }


class TicketReportForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ["body", "priority"]
        widgets = {
            "body": forms.Textarea(attrs={"class": "form-input", "rows": 5, "placeholder": "Почему нужно обратить внимание на этот материал?"}),
            "priority": forms.Select(attrs={"class": "form-input"}),
        }


class TicketResponseForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = ["admin_response", "status"]
        widgets = {
            "admin_response": forms.Textarea(attrs={"class": "form-input", "rows": 6, "placeholder": "Ответ пользователю"}),
            "status": forms.Select(attrs={"class": "form-input"}),
        }
