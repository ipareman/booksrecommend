from django import forms
from .models import Critique


class CritiqueForm(forms.ModelForm):
    class Meta:
        model = Critique
        fields = ["title", "body", "final_rating", "cover_image"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-input",
                "placeholder": "Заголовок рецензии",
            }),
            "body": forms.Textarea(attrs={
                "id": "id_body",
                "style": "display:none",
            }),
            "cover_image": forms.ClearableFileInput(attrs={
                "class": "form-input",
                "accept": "image/*",
            }),
        }
