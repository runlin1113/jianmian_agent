"""应用层：用例编排入口。

这一层只做"把领域规则、端口实现和安全设施装配成一次业务用例"，
不含 HTTP 细节（在 api/）也不含领域规则（在 domain/）。
"""

from .container import AppContainer, build_container
from .runs import RunService

__all__ = ["AppContainer", "build_container", "RunService"]
