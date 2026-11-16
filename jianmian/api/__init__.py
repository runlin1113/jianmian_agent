"""HTTP 边界层。

只做三件事：认证会话、校验输入契约、把领域错误翻译成统一错误体。
业务逻辑一律在 application/，这里不写规则。
"""

from .app import create_app

__all__ = ["create_app"]
