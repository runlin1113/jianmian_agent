"""领域层契约测试：模块注册表、文档、事实守卫、提案原子性、迁移。

这些测试保护的是"错误写入为零"这条硬要求：
AI 可以改表达，但改了数字/日期就必须失败，且整批不写。
"""

from __future__ import annotations

import pytest

from jianmian.domain import errors
from jianmian.domain.facts import check_guarded_rewrite, extract_facts, fact_tokens
from jianmian.domain.migration import migrate_legacy
from jianmian.domain.modules import MODULE_SPECS, get_spec
from jianmian.domain.proposals import (
    AddModuleOp,
    ChangeProposal,
    RemoveModuleOp,
    ReplaceFieldOp,
    apply_proposal,
    validate_proposal_payload,
)
from jianmian.domain.resume import (
    add_module,
    change_appearance,
    new_document,
    remove_module,
    validate_document,
)


# ---------------------------------------------------------------- 模块注册表
def test_module_registry_is_closed_and_complete():
    types = {spec.type for spec in MODULE_SPECS}
    assert types == {
        "basic",
        "portrait",
        "education",
        "project",
        "internship",
        "skills",
        "honor",
        "summary",
    }
    for spec in MODULE_SPECS:
        assert spec.fields, f"{spec.type} 没有字段"
    # 除肖像（纯资源位）外，每个模块都必须有可编辑的文本字段
    for spec in MODULE_SPECS:
        if spec.type == "portrait":
            continue
        assert any(f.kind != "image" for f in spec.fields), spec.type


def test_unknown_module_type_rejected():
    with pytest.raises(errors.DomainError) as exc:
        get_spec("hack_module")
    assert exc.value.code == "unknown_module_type"


def test_document_rejects_unknown_field():
    doc = new_document().model_dump(mode="json")
    doc["modules"] = [
        {"id": "m1", "type": "project", "order": 1, "data": {"proj_name": "x", "evil": "y"}}
    ]
    with pytest.raises(errors.DomainError):
        validate_document(doc)


def test_document_rejects_dangerous_keys():
    payload = new_document().model_dump(mode="json")
    payload["modules"] = [{"id": "m1", "type": "project", "order": 1, "data": {"__proto__": "x"}}]
    with pytest.raises(errors.DomainError):
        validate_document(payload)


def test_field_length_limit_enforced():
    payload = new_document().model_dump(mode="json")
    payload["modules"] = [
        {"id": "m1", "type": "basic", "order": 1, "data": {"name": "名" * 500}}
    ]
    with pytest.raises(errors.DomainError):
        validate_document(payload)


# ---------------------------------------------------------------- 文档与版本
def test_revision_and_hash_change_on_edit():
    doc = new_document()
    before = doc.content_hash()
    doc = add_module(doc, "project", {"proj_name": "选课系统"})
    assert doc.revision == 1
    assert doc.content_hash() != before
    # 同样的内容哈希稳定（可用于提案基准比对）
    clone = validate_document(doc.model_dump(mode="json"))
    assert clone.content_hash() == doc.content_hash()


def test_appearance_change_bumps_revision():
    doc = new_document()
    doc2 = change_appearance(doc, {"theme": "rose"})
    assert doc2.revision == doc.revision + 1
    assert doc2.appearance.theme == "rose"


def test_remove_module_keeps_order_dense():
    doc = new_document()
    doc = add_module(doc, "project", {"proj_name": "A"})
    doc = add_module(doc, "project", {"proj_name": "B"})
    doc = add_module(doc, "project", {"proj_name": "C"})
    first = doc.by_type("project")[0]
    doc = remove_module(doc, first.id)
    orders = [m.order for m in doc.sorted_modules()]
    assert orders == list(range(len(orders))), "删除后 order 必须连续，否则排序与哈希会漂移"
    assert first.id not in {m.id for m in doc.modules}


# ---------------------------------------------------------------- 事实守卫
def test_guarded_rewrite_keeps_numbers():
    result = check_guarded_rewrite("服务 300 名学生", "支持 300 名学生同时选课")
    assert result.ok, result.violations


def test_guarded_rewrite_blocks_invented_number():
    result = check_guarded_rewrite("服务 300 名学生", "服务 800 名学生")
    assert not result.ok
    assert any(v.kind == "new_fact_token" for v in result.violations)


def test_guarded_rewrite_blocks_dropped_fact():
    result = check_guarded_rewrite("服务 300 名学生", "负责选课功能")
    assert not result.ok


def test_fact_tokens_extract_dates_and_numbers():
    doc = new_document()
    doc = add_module(doc, "project", {"proj_name": "P", "time": "2025.03-2025.06", "desc": "服务 300 人"})
    tokens = fact_tokens(extract_facts(doc))
    assert "300" in tokens.numbers
    assert any(year in tokens.years for year in ("2025", "2026"))


def test_locked_field_not_ai_writable():
    spec = get_spec("education")
    assert not spec.field("school").ai_editable
    assert spec.field("course").ai_editable


# ---------------------------------------------------------------- 提案
def _proposal(doc, ops) -> ChangeProposal:
    return ChangeProposal(
        resumeId=doc.id,
        baseRevision=doc.revision,
        baseHash=doc.content_hash(),
        operations=ops,
    )


def test_proposal_applies_all_operations_atomically():
    doc = new_document()
    doc = add_module(doc, "project", {"proj_name": "选课系统", "desc": "使用 Flask 实现选课功能"})
    module = doc.by_type("project")[0]
    proposal = _proposal(
        doc,
        [
            ReplaceFieldOp(
                moduleId=module.id,
                field="desc",
                before=module.data["desc"],
                after="基于 Flask 实现选课接口与规则校验",
            ),
            AddModuleOp(moduleType="skills", data={"skills": "Python、Flask"}),
        ],
    )
    outcome = apply_proposal(doc, proposal, allowed_tokens=fact_tokens(extract_facts(doc)))
    assert outcome.document.revision == doc.revision + 1
    assert outcome.document.by_type("project")[0].data["desc"].startswith("基于 Flask")
    assert outcome.document.by_type("skills")[0].data["skills"] == "Python、Flask"


def test_proposal_batch_fails_when_one_operation_changes_fact():
    doc = new_document()
    doc = add_module(doc, "project", {"proj_name": "选课系统", "desc": "服务 300 名学生"})
    module = doc.by_type("project")[0]
    proposal = _proposal(
        doc,
        [
            ReplaceFieldOp(moduleId=module.id, field="desc", before="服务 300 名学生", after="服务 1000 名学生"),
            AddModuleOp(moduleType="skills", data={"skills": "Python"}),
        ],
    )
    with pytest.raises(errors.DomainError) as exc:
        apply_proposal(doc, proposal, allowed_tokens=fact_tokens(extract_facts(doc)))
    assert exc.value.code in {"fact_guard_failed", "fact_protected"}
    # 原文档不受影响：整批不写
    assert doc.by_type("project")[0].data["desc"] == "服务 300 名学生"
    assert not doc.by_type("skills")


def test_proposal_rejects_before_value_mismatch():
    doc = new_document()
    doc = add_module(doc, "project", {"proj_name": "P", "desc": "原文"})
    module = doc.by_type("project")[0]
    proposal = _proposal(
        doc,
        [ReplaceFieldOp(moduleId=module.id, field="desc", before="不存在的原文", after="新文本")],
    )
    with pytest.raises(errors.DomainError):
        apply_proposal(doc, proposal, allowed_tokens=fact_tokens(extract_facts(doc)))


def test_proposal_rejects_unknown_op():
    with pytest.raises(errors.DomainError):
        validate_proposal_payload({"operations": [{"op": "drop_table"}]})


def test_proposal_rejects_script_payload():
    doc = new_document()
    doc = add_module(doc, "project", {"proj_name": "P", "desc": "原文"})
    module = doc.by_type("project")[0]
    # 危险内容在"构造操作"这一步就被纯文本校验拦住，
    # 不依赖后续是否有人记得再检查一遍。
    with pytest.raises(errors.DomainError) as exc:
        ReplaceFieldOp(moduleId=module.id, field="desc", before="原文", after="<script>alert(1)</script>")
    assert exc.value.code == "contract_violation"


def test_remove_module_is_not_a_default_tool_permission():
    """删除/排序不在普通润色工具权限里：提案可以表达，但意图必须显式。"""
    from jianmian.workflows.tools import ALLOWED_BY_INTENT

    assert "remove_module" not in ALLOWED_BY_INTENT["edit"]


# ---------------------------------------------------------------- 迁移
def test_legacy_migration_keeps_content_and_drops_key():
    legacy = {
        "resumeId": "r-old",
        "targetJob": "Python 后端",
        "template": "modern",
        "theme": "rose",
        "density": "concise",
        "api": {"apiKey": "sk-should-not-survive"},
        "modules": [
            {"type": "教育背景", "school": "江城大学", "major": "计算机科学与技术", "degree": "本科"},
            {"type": "项目经历", "proj_name": "选课系统", "desc": "服务 300 名学生"},
            {"type": "未知模块", "foo": "bar"},
        ],
    }
    result = migrate_legacy(legacy)
    assert result.migrated or result.document.modules
    assert result.document.appearance.template == "modern"
    assert result.document.appearance.theme == "rose"
    assert result.document.by_type("education")[0].data["school"] == "江城大学"
    dumped = result.document.model_dump_json()
    assert "sk-should-not-survive" not in dumped
    assert any("apiKey" in warning or "Key" in warning for warning in result.warnings)
    # 未知模块进入 recovery，而不是静默丢弃
    assert result.document.recovery
