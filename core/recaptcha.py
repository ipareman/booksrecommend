import requests
from django.conf import settings


def verify(token: str, remote_ip: str = "") -> bool:
    """Проверить reCAPTCHA v2 токен. Возвращает True если прошёл."""
    secret = settings.RECAPTCHA_PRIVATE_KEY
    if not secret:
        return True  # Если ключ не задан — пропускаем (dev режим)
    if not token:
        return False
    try:
        r = requests.post(
            "https://www.google.com/recaptcha/api/siteverify",
            data={"secret": secret, "response": token, "remoteip": remote_ip},
            timeout=5,
        )
        return r.json().get("success", False)
    except requests.RequestException:
        return False
