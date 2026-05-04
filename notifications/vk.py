import logging
import random

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

API_BASE = "https://api.vk.com/method"


def _request(method_name: str, *, params: dict | None = None, timeout: int = 10) -> dict | None:
    token = getattr(settings, "VK_BOT_TOKEN", "")
    if not token:
        logger.warning("VK_BOT_TOKEN не задан, уведомление пропущено")
        return None

    payload = {
        "access_token": token,
        "v": getattr(settings, "VK_API_VERSION", "5.199"),
    }
    payload.update(params or {})

    try:
        response = requests.post(f"{API_BASE}/{method_name}", data=payload, timeout=timeout)
        data = response.json()
    except requests.RequestException as exc:
        logger.error("VK request failed: %s", exc)
        return None
    except ValueError:
        logger.error("VK returned non-JSON response")
        return None

    if data.get("error"):
        logger.error("VK API error %s: %s", method_name, data.get("error"))
        return None
    return data.get("response")


def _html_to_text(text: str) -> str:
    return (
        (text or "")
        .replace("<b>", "")
        .replace("</b>", "")
        .replace("<i>", "")
        .replace("</i>", "")
        .replace("<br>", "\n")
        .replace("<br/>", "\n")
        .replace("<br />", "\n")
    )


def send_message(user_id: str | int, text: str) -> bool:
    if not user_id:
        return False
    result = _request(
        "messages.send",
        params={
            "user_id": str(user_id),
            "message": _html_to_text(text),
            "random_id": random.randint(1, 2_147_483_647),
        },
    )
    return bool(result)


def groups_get_long_poll_server() -> dict | None:
    group_id = getattr(settings, "VK_GROUP_ID", "")
    if not group_id:
        logger.warning("VK_GROUP_ID не задан")
        return None
    return _request("groups.getLongPollServer", params={"group_id": group_id})


def get_updates(server: str, key: str, ts: str, wait: int = 25) -> dict | None:
    try:
        response = requests.get(
            server,
            params={"act": "a_check", "key": key, "ts": ts, "wait": wait},
            timeout=wait + 10,
        )
        return response.json()
    except requests.RequestException as exc:
        logger.error("VK Long Poll request failed: %s", exc)
        return None
    except ValueError:
        logger.error("VK Long Poll returned non-JSON response")
        return None


def get_user(user_id: str | int) -> dict | None:
    response = _request("users.get", params={"user_ids": str(user_id), "fields": "screen_name"})
    if isinstance(response, list) and response:
        return response[0]
    return None
