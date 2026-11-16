"""用例集合：把 application/ 里的服务装成一个可注入的对象。

路由层只依赖这个对象，不直接碰容器细节；
测试里可以用同一份配置构造一套服务，不需要起 HTTP。
"""

from __future__ import annotations

from dataclasses import dataclass

from .container import AppContainer, build_container
from .imports import ImportService
from .interviews import InterviewService
from .jobs import JobService
from .profile import ProfileService
from .runs import RunService


@dataclass
class Services:
    container: AppContainer
    runs: RunService
    imports: ImportService
    jobs: JobService
    interviews: InterviewService
    profile: ProfileService

    @classmethod
    def build(cls, container: AppContainer | None = None) -> "Services":
        container = container or build_container()
        return cls(
            container=container,
            runs=RunService(container),
            imports=ImportService(container),
            jobs=JobService(container),
            interviews=InterviewService(container),
            profile=ProfileService(container),
        )

    def purge(self) -> dict[str, int]:
        return {
            **self.runs.purge_expired(),
            "imports": self.imports.purge(),
            "interviews": self.interviews.purge(),
        }

    def shutdown(self) -> None:
        self.runs.shutdown()


__all__ = ["Services", "build_container"]
