"""模块注册表（M1/M2 的扩展点）。

对应架构书第 6 章 M1—M14 映射与第 7.3 节字段权限。这里同时是：
- 旧版 8 类中文模块名 → 稳定英文枚举的映射表；
- 字段级事实策略的唯一事实来源（`locked` / `guarded` / `open` / `asset`）；
- 模板槽位与渲染提示（前端的 2 套模板、6 套主题由 `appearance` 承载，不在此处）。

新增模块只需要在 `MODULE_SPECS` 里加一条：声明字段、事实策略、槽位，
编排层、提案校验、迁移器和前端编辑器都会自动获得新能力，不需要改散落各处的 if/else。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal

FieldKind = Literal["line", "text", "image"]
#: locked  = 硬事实，AI 不可写入（人工仍可改）
#: guarded = 可改写表达，但必须保留原文中的数字/日期/实体
#: open    = 表达性字段，允许润色重写
#: asset   = 二进制资源，只允许人工上传
FactPolicy = Literal["locked", "guarded", "open", "asset"]
TemplateSlot = Literal["header", "main", "side"]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    kind: FieldKind = "line"
    policy: FactPolicy = "open"
    max_length: int = 200
    #: 该字段为空时是否允许整块跳过（空模块不渲染）
    optional: bool = True

    @property
    def ai_editable(self) -> bool:
        return self.policy in {"guarded", "open"}


@dataclass(frozen=True)
class ModuleSpec:
    type: str
    zh: str
    icon: str
    fields: tuple[FieldSpec, ...]
    slot: TemplateSlot = "main"
    multiple: bool = True
    #: 依据哪个字段生成"第 N 个 XX"的澄清用标题
    title_field: str | None = None
    #: 单模块润色的默认目标字段
    ai_target: str | None = None
    #: 空模块是否允许跳过（个人肖像在缺少照片时整块不渲染）
    skippable: bool = False

    def field(self, name: str) -> FieldSpec | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)

    @property
    def ai_fields(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.ai_editable)

    @property
    def locked_fields(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.policy == "locked")

    @property
    def fact_fields(self) -> tuple[str, ...]:
        """需要进入事实库的字段（locked + guarded 中的结构化值）。"""
        return tuple(f.name for f in self.fields if f.policy in {"locked", "guarded"})


MODULE_SPECS: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        type="basic",
        zh="基本信息",
        icon="01",
        slot="header",
        multiple=False,
        title_field="name",
        fields=(
            FieldSpec("name", "姓名", policy="locked"),
            FieldSpec("phone", "电话", policy="locked", max_length=40),
            FieldSpec("email", "邮箱", policy="locked", max_length=120),
            FieldSpec("job", "求职意向", policy="guarded"),
            FieldSpec("github", "个人主页 / GitHub", policy="guarded"),
        ),
    ),
    ModuleSpec(
        type="portrait",
        zh="个人肖像",
        icon="02",
        slot="header",
        multiple=False,
        skippable=True,
        fields=(FieldSpec("avatar", "个人肖像", kind="image", policy="asset", max_length=2_800_000),),
    ),
    ModuleSpec(
        type="education",
        zh="教育背景",
        icon="03",
        slot="main",
        title_field="school",
        ai_target="course",
        fields=(
            FieldSpec("school", "学校名称", policy="locked"),
            FieldSpec("major", "专业名称", policy="locked"),
            FieldSpec("degree", "学历", policy="locked", max_length=40),
            FieldSpec("time", "就读时间", policy="locked", max_length=60),
            FieldSpec("course", "主修课程 / GPA", kind="text", policy="guarded", max_length=800),
        ),
    ),
    ModuleSpec(
        type="project",
        zh="项目经历",
        icon="04",
        slot="main",
        title_field="proj_name",
        ai_target="desc",
        fields=(
            FieldSpec("proj_name", "项目名称", policy="locked"),
            FieldSpec("role", "担任角色", policy="locked", max_length=80),
            FieldSpec("time", "起止时间", policy="locked", max_length=60),
            FieldSpec("tech", "核心技术栈", policy="locked", max_length=200),
            FieldSpec("desc", "项目详情（STAR）", kind="text", policy="guarded", max_length=2000),
        ),
    ),
    ModuleSpec(
        type="internship",
        zh="实习经历",
        icon="05",
        slot="main",
        title_field="company",
        ai_target="desc",
        fields=(
            FieldSpec("company", "公司名称", policy="locked"),
            FieldSpec("position", "职位名称", policy="locked", max_length=80),
            FieldSpec("time", "在职时间", policy="locked", max_length=60),
            FieldSpec("desc", "工作内容及产出", kind="text", policy="guarded", max_length=2000),
        ),
    ),
    ModuleSpec(
        type="skills",
        zh="个人技能",
        icon="06",
        slot="side",
        multiple=False,
        ai_target="skills",
        fields=(FieldSpec("skills", "技能清单", kind="text", policy="guarded", max_length=800),),
    ),
    ModuleSpec(
        type="honor",
        zh="个人荣誉",
        icon="07",
        slot="side",
        title_field="honor_name",
        ai_target="level",
        fields=(
            FieldSpec("honor_name", "奖项名称", policy="locked"),
            FieldSpec("time", "获奖时间", policy="locked", max_length=60),
            FieldSpec("level", "获奖级别 / 说明", kind="text", policy="guarded", max_length=400),
        ),
    ),
    ModuleSpec(
        type="summary",
        zh="自我评价",
        icon="08",
        slot="main",
        multiple=False,
        ai_target="eval",
        fields=(FieldSpec("eval", "自我评价", kind="text", policy="guarded", max_length=1200),),
    ),
)

MODULE_BY_TYPE: dict[str, ModuleSpec] = {spec.type: spec for spec in MODULE_SPECS}

#: 旧版中文模块名 → 稳定英文枚举（第 7.2 节：界面继续显示中文，内部用英文）
LEGACY_TYPE_MAP: dict[str, str] = {spec.zh: spec.type for spec in MODULE_SPECS}

#: 旧版字段名 → 新字段名（首版保留旧名称，只做显式映射，避免一次性改所有表单）
LEGACY_FIELD_MAP: dict[str, dict[str, str]] = {
    "education": {"time": "time", "course": "course"},
}

#: 内容档位：字符预算，不是"一页保证"（第 2.2 节差异表）
DENSITY_BUDGETS: dict[str, int] = {"concise": 480, "balanced": 760, "detailed": 1200}

#: 6 套主题令牌（M2）
THEMES: tuple[dict[str, str], ...] = (
    {"id": "navy", "name": "经典藏蓝", "en": "Navy", "accent": "#14365A"},
    {"id": "rose", "name": "粉樱", "en": "Rose", "accent": "#9D174D"},
    {"id": "amber", "name": "暖阳橙", "en": "Amber", "accent": "#B45309"},
    {"id": "emerald", "name": "翡翠绿", "en": "Emerald", "accent": "#14532D"},
    {"id": "violet", "name": "魅影紫", "en": "Violet", "accent": "#4C1D95"},
    {"id": "teal", "name": "青瓷蓝", "en": "Teal", "accent": "#0F5E66"},
)

#: 2 套模板（M3）
TEMPLATES: tuple[dict[str, str], ...] = (
    {"id": "executive", "name": "Executive", "desc": "双栏：左主叙述 + 右侧技能/荣誉"},
    {"id": "modern", "name": "Modern", "desc": "单栏通排：适合内容较多的项目型简历"},
)

DEFAULT_APPEARANCE: dict[str, str] = {"template": "executive", "theme": "navy", "density": "balanced"}


def get_spec(module_type: str) -> ModuleSpec:
    spec = MODULE_BY_TYPE.get(module_type)
    if spec is None:
        from .errors import unknown_module_type

        raise unknown_module_type(module_type)
    return spec


def all_specs() -> tuple[ModuleSpec, ...]:
    return MODULE_SPECS


def empty_data(module_type: str) -> dict[str, str]:
    spec = get_spec(module_type)
    return {f.name: "" for f in spec.fields}


def module_title(module_type: str, data: dict) -> str:
    """用于"删掉第二个项目"这类澄清：给出可读标题。"""
    spec = get_spec(module_type)
    if spec.title_field:
        value = str(data.get(spec.title_field) or "").strip()
        if value:
            return value
    for f in spec.fields:
        value = str(data.get(f.name) or "").strip()
        if value and f.kind != "image":
            return value[:24]
    return spec.zh


def iter_ai_targets(spec: ModuleSpec) -> Iterable[str]:
    return (f.name for f in spec.fields if f.ai_editable)
