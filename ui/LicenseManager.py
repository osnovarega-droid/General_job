import hashlib
import os
import platform
import uuid
from datetime import datetime, timezone

import requests


class LicenseManager:
    def __init__(self, settings_manager):
        self.settings = settings_manager

    def get_hwid(self):
        source = "|".join([
            platform.node() or "",
            platform.system() or "",
            platform.machine() or "",
            hex(uuid.getnode() or 0),
            self._read_machine_id(),
        ])
        return hashlib.sha256(source.encode("utf-8", errors="ignore")).hexdigest()[:24].upper()

    def _read_machine_id(self):
        candidates = [
            "/etc/machine-id",
            "/var/lib/dbus/machine-id",
        ]
        for path in candidates:
            try:
                if os.path.exists(path):
                    return open(path, "r", encoding="utf-8").read().strip()
            except Exception:
                pass
        return ""

    def check_subscription(self, hwid):
        vercel_url = (self.settings.get("LicenseVercelCheckUrl", "") or "").strip()
        if vercel_url:
            ok, message = self._check_vercel(vercel_url, hwid)
            return ok, message

        firebase_base = (self.settings.get("LicenseFirebaseUrl", "") or "").strip().rstrip("/")
        if not firebase_base:
            return False, "Укажите LicenseFirebaseUrl в разделе License"

        token = (self.settings.get("LicenseFirebaseToken", "") or "").strip()
        return self._check_firebase(firebase_base, token, hwid)

    def _check_vercel(self, endpoint, hwid):
        try:
            response = requests.get(endpoint, params={"hwid": hwid}, timeout=8)
            response.raise_for_status()
            payload = response.json() if response.content else {}
            if self._is_active(payload):
                return True, "Подписка активна (через Vercel API)"
            return False, "Подписка не активна (через Vercel API)"
        except Exception as exc:
            return False, f"Ошибка Vercel API: {exc}"

    def _check_firebase(self, base, token, hwid):
        try:
            url = f"{base}/licenses/{hwid}.json"
            params = {"auth": token} if token else None
            response = requests.get(url, params=params, timeout=8)
            response.raise_for_status()
            payload = response.json()
            if self._is_active(payload):
                return True, "Подписка активна (Firebase)"
            return False, "HWID не найден или подписка просрочена"
        except Exception as exc:
            return False, f"Ошибка Firebase: {exc}"

    def _is_active(self, payload):
        if not payload:
            return False
        if isinstance(payload, bool):
            return payload
        if not isinstance(payload, dict):
            return False

        if payload.get("active") is True:
            return not self._is_expired(payload)

        status = str(payload.get("status", "")).lower()
        if status in {"active", "ok", "paid"}:
            return not self._is_expired(payload)

        return False

    def _is_expired(self, payload):
        expires_at = payload.get("expiresAt") or payload.get("expires_at")
        if not expires_at:
            return False

        if isinstance(expires_at, (int, float)):
            return datetime.now(timezone.utc).timestamp() > float(expires_at)

        if isinstance(expires_at, str):
            try:
                normalized = expires_at.replace("Z", "+00:00")
                dt = datetime.fromisoformat(normalized)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return datetime.now(timezone.utc) > dt.astimezone(timezone.utc)
            except Exception:
                return False

        return False