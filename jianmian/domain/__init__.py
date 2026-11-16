"""领域层。

本层是纯 Python + Pydantic：不导入 FastAPI、httpx、langgraph 或任何云 SDK。
新增模块、字段规则、事实策略、提案契约都只在这里改，编排层与适配器不必改动。
"""
