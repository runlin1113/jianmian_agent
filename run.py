"""便捷启动：`python run.py`。

等价于 `uvicorn jianmian.main:app`，但会打印出可点的地址与当前模型模式。
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        print("缺少依赖。请先执行：python -m pip install -r requirements.txt", file=sys.stderr)
        return 1

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    provider = os.getenv("JIANMIAN_MODEL_PROVIDER", "mock")
    print(f"简面智能体 → http://{host}:{port}/  模型模式：{provider}")
    if provider == "mock":
        print("  （离线确定性模式：不需要 Key，可跑通全链路；设置 JIANMIAN_MODEL_PROVIDER=deepseek 可切真实模型）")
    import uvicorn

    uvicorn.run("jianmian.main:app", host=host, port=port, reload=bool(os.getenv("JIANMIAN_RELOAD")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
