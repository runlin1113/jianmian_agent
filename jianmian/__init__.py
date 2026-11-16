"""简面智能体 · 本地优先的简历编辑内核 + 模块化单体后端。

分层依赖方向（单向，不得回指）::

    api → application → domain
                     ↘ workflows → ports ← adapters
    security 被 api/application 使用，但 security 不导入 domain

domain 层不导入 fastapi / httpx / langgraph，保证简历字段规则可以脱离 Web 框架单独测试。
"""

__version__ = "0.1.0"
SCHEMA_VERSION = "resume-document/1"
