"""Shared login account. Multiple sessions may sign in at the same time."""
from __future__ import annotations

import secrets

USERNAME = "cmcc"
PASSWORD = "CMCC123456"


def try_login(username, password):
    user = (username or "").strip()
    pwd = password or ""
    if not user or not pwd:
        return False, "请输入用户名和密码。"
    if not (
        secrets.compare_digest(user, USERNAME)
        and secrets.compare_digest(pwd, PASSWORD)
    ):
        return False, "用户名或密码错误。"
    return True, None
