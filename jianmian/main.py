"""启动入口：`python -m jianmian.main` 或 `uvicorn jianmian.main:app`。

默认 mock 模型，零 Key、零联网即可跑通全链路；
设置 JIANMIAN_MODEL_PROVIDER=deepseek 且提供 JIANMIAN_OWNER_KEY 即切到真实模型。
"""

from __future__ import annotations

import os

from .api.app import create_app

app = create_app()


def main() -> None:
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "127.0.0.1")
    uvicorn.run("jianmian.main:app", host=host, port=port, reload=bool(os.getenv("JIANMIAN_RELOAD")))


if __name__ == "__main__":
    main()
