"""Parsing and templating utilities for knowledge blueprint documents."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Iterable, List, Sequence


class BlueprintParsingError(ValueError):
    """Raised when a blueprint document cannot be parsed."""


@dataclass
class BlueprintEntry:
    """A structured knowledge item extracted from a blueprint document."""

    title: str
    question: str
    answer: str
    tags: List[str]


@dataclass
class BlueprintDocument:
    """Parsed representation of a blueprint document."""

    metadata: dict
    sections: dict[str, str]
    entries: List[BlueprintEntry]


BLUEPRINT_TEMPLATE = """# 工艺知识蓝图

```json
{
  "type": "knowledge_blueprint",
  "process_name": "示例工艺",
  "version": "1.0",
  "owner": "工程师姓名",
  "last_reviewed": "2024-01-01",
  "scope": "适用范围说明",
  "equipment": ["主要设备A", "主要设备B"],
  "tags": ["示例", "工艺"],
  "summary": "一句话概述工艺目标与产出。"
}
```

> 请保持以上 JSON 结构，替换内容时不要删除 `type` 字段。

## 场景描述
介绍工艺应用背景、产线位置以及与其他工序的关系。

## 操作步骤
1. 第一步，描述关键操作动作及注意事项。
2. 第二步，描述测量或质检节点。
3. 第三步，描述交接或产出要求。

## 关键参数
| 参数 | 目标值 | 允许范围 | 监控方式 |
| --- | --- | --- | --- |
| 温度 | 85℃ | 83-87℃ | 在线温控系统 |
| 压力 | 1.2 bar | 1.0-1.4 bar | 仪表读数 |

## 决策要点
- 触发加料的门限为温度连续 3 分钟低于 83℃。
- 样品黏度高于 1200mPa·s 时需要改走再分散流程。

## 风险控制
- 风险点: 搅拌桨卡滞 — 预警信号: 电流骤升 — 应对: 立即停机检查并手动排障。
- 风险点: 物料 pH 异常 — 预警信号: 在线 pH>7.5 — 应对: 补加调节剂并复测。

## 常见问题
### Q: 出现大量气泡时如何处理？
现象: 成品表面出现均匀大小气泡。
原因: 进料阀未完全打开，夹带空气。
措施: 检查并重新调整进料阀开度，必要时延长抽真空时间。
验证: 抽样检测气泡密度小于 2% 即可恢复生产。

### Q: 温度传感器读数波动过大怎么办？
现象: 传感器读数上下波动超过 5℃。
原因: 传感器老化或接线松动。
措施: 更换传感器并复紧接线，按维护手册重新校准。
验证: 重新校准后 10 分钟内波动控制在 1℃ 以内。

## 参考资料
- 《示例工艺作业指导书》文档编号 SOP-001。
- 相关质量体系条款 ISO9001-8.5。

"""


_METADATA_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_SECTION_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_FAQ_HEADER_RE = re.compile(r"^###\s*Q:\s*(.+)$", re.MULTILINE)
_FIELD_RE = re.compile(r"^(现象|原因|措施|验证|备注)\s*[:：]\s*(.*)$")


def _normalize_tags(tags: Iterable[str] | str | None) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        candidates = [item.strip() for item in tags.split(",")]
    else:
        candidates = [str(item).strip() for item in tags]
    return [item for item in candidates if item]


def _parse_metadata(text: str) -> dict:
    match = _METADATA_BLOCK_RE.search(text)
    if not match:
        raise BlueprintParsingError("缺少 JSON 元信息代码块。")
    try:
        metadata = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise BlueprintParsingError(f"元信息 JSON 解析失败: {exc}") from exc
    if metadata.get("type") != "knowledge_blueprint":
        raise BlueprintParsingError("元信息 type 必须为 knowledge_blueprint。")
    return metadata


def _parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(text))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = match.group(1).strip()
        content = text[start:end].strip()
        sections[title] = content
    return sections


def _parse_steps(section: str) -> list[str]:
    steps: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^(?:\d+[.)]|[-*])\s*(.+)$", stripped)
        if match:
            steps.append(match.group(1).strip())
    return steps


def _parse_table(section: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        inner = stripped.strip("|")
        cells = [cell.strip() for cell in inner.split("|")]
        if all(set(cell) <= {"-", " "} for cell in cells):
            continue
        rows.append(cells)
    return rows


def _format_parameter_lines(section: str) -> list[str]:
    table = _parse_table(section)
    if len(table) >= 2:
        headers = table[0]
        lines: list[str] = []
        for row in table[1:]:
            pairs = []
            for index, cell in enumerate(row):
                if not cell.strip():
                    continue
                header = headers[index] if index < len(headers) else f"字段{index + 1}"
                pairs.append(f"{header}: {cell}")
            if pairs:
                lines.append(" | ".join(pairs))
        return lines

    lines: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.match(r"^[-*]\s*(.+)$", stripped)
        if match:
            lines.append(match.group(1).strip())
    return lines


def _parse_faqs(section: str) -> list[tuple[str, dict[str, str]]]:
    entries: list[tuple[str, dict[str, str]]] = []
    matches = list(_FAQ_HEADER_RE.finditer(section))
    for index, match in enumerate(matches):
        question = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        block = section[start:end]
        fields: dict[str, str] = {}
        current_field: str | None = None
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            field_match = _FIELD_RE.match(stripped)
            if field_match:
                current_field = field_match.group(1)
                fields[current_field] = field_match.group(2).strip()
            elif current_field:
                fields[current_field] += f"\n{stripped}"
        entries.append((question, fields))
    return entries


class KnowledgeBlueprint:
    """Factory helpers for blueprint detection and parsing."""

    @staticmethod
    def looks_like(text: str) -> bool:
        return "knowledge_blueprint" in text and "```json" in text

    @staticmethod
    def parse(text: str) -> BlueprintDocument:
        metadata = _parse_metadata(text)
        sections = _parse_sections(text)
        process_name = (
            metadata.get("process_name")
            or metadata.get("name")
            or metadata.get("title")
            or "该工艺"
        )
        base_tags = _normalize_tags(metadata.get("tags"))
        if "蓝图" not in base_tags:
            base_tags.append("蓝图")

        entries: list[BlueprintEntry] = []

        overview_parts: list[str] = []
        summary = metadata.get("summary")
        scope = metadata.get("scope")
        owner = metadata.get("owner")
        version = metadata.get("version")
        last_reviewed = metadata.get("last_reviewed")
        equipment = metadata.get("equipment")
        if isinstance(equipment, Sequence) and not isinstance(equipment, str):
            equipment_text = "、".join(str(item) for item in equipment if str(item).strip())
        else:
            equipment_text = str(equipment).strip() if equipment else ""

        if summary:
            overview_parts.append(str(summary).strip())
        if scope:
            overview_parts.append(f"适用范围：{scope}")
        if owner or version or last_reviewed:
            details = []
            if owner:
                details.append(f"负责人：{owner}")
            if version:
                details.append(f"版本：{version}")
            if last_reviewed:
                details.append(f"最近审核：{last_reviewed}")
            overview_parts.append("；".join(details))
        if equipment_text:
            overview_parts.append(f"关键设备：{equipment_text}")
        for key in ("工艺概述", "场景描述"):
            section_text = sections.get(key)
            if section_text:
                overview_parts.append(section_text.strip())
        if overview_parts:
            entries.append(
                BlueprintEntry(
                    title=f"{process_name} - 工艺概览",
                    question=f"{process_name} 的背景和适用范围是什么？",
                    answer="\n\n".join(overview_parts).strip(),
                    tags=base_tags + ["概述"],
                )
            )

        steps_text = sections.get("操作步骤")
        if steps_text:
            steps = _parse_steps(steps_text)
            if steps:
                formatted = "\n".join(f"{index + 1}. {step}" for index, step in enumerate(steps))
                entries.append(
                    BlueprintEntry(
                        title=f"{process_name} - 操作步骤",
                        question=f"如何执行 {process_name} 的标准操作流程？",
                        answer=formatted,
                        tags=base_tags + ["操作"],
                    )
                )

        parameters_text = sections.get("关键参数")
        if parameters_text:
            parameters = _format_parameter_lines(parameters_text)
            if parameters:
                entries.append(
                    BlueprintEntry(
                        title=f"{process_name} - 关键参数",
                        question=f"{process_name} 需要关注哪些关键参数？",
                        answer="\n".join(parameters),
                        tags=base_tags + ["参数"],
                    )
                )

        decision_text = sections.get("决策要点")
        if decision_text:
            bullets = [line.strip("-* ") for line in decision_text.splitlines() if line.strip()]
            if bullets:
                entries.append(
                    BlueprintEntry(
                        title=f"{process_name} - 决策要点",
                        question=f"{process_name} 的控制要点是什么？",
                        answer="\n".join(f"- {item}" for item in bullets),
                        tags=base_tags + ["决策"],
                    )
                )

        risk_text = sections.get("风险控制")
        if risk_text:
            risks = [line.strip("-* ") for line in risk_text.splitlines() if line.strip()]
            if risks:
                entries.append(
                    BlueprintEntry(
                        title=f"{process_name} - 风险控制",
                        question=f"如何在 {process_name} 中进行风险预防和应对？",
                        answer="\n".join(f"- {item}" for item in risks),
                        tags=base_tags + ["风险"],
                    )
                )

        faq_text = sections.get("常见问题")
        if faq_text:
            for question, fields in _parse_faqs(faq_text):
                if not question:
                    continue
                parts: list[str] = []
                for label in ("现象", "原因", "措施", "验证", "备注"):
                    value = fields.get(label)
                    if value:
                        parts.append(f"{label}：{value}")
                answer = "\n".join(parts) if parts else faq_text.strip()
                entries.append(
                    BlueprintEntry(
                        title=f"{process_name} - 常见问题: {question}",
                        question=question,
                        answer=answer,
                        tags=base_tags + ["FAQ"],
                    )
                )

        reference_text = sections.get("参考资料")
        if reference_text:
            refs = [line.strip("-* ") for line in reference_text.splitlines() if line.strip()]
            if refs:
                entries.append(
                    BlueprintEntry(
                        title=f"{process_name} - 参考资料",
                        question=f"有哪些资料可进一步学习 {process_name}？",
                        answer="\n".join(f"- {item}" for item in refs),
                        tags=base_tags + ["参考"],
                    )
                )

        if not entries:
            raise BlueprintParsingError("未在蓝图中解析到有效内容。")

        return BlueprintDocument(metadata=metadata, sections=sections, entries=entries)


__all__ = [
    "BlueprintParsingError",
    "BlueprintEntry",
    "BlueprintDocument",
    "KnowledgeBlueprint",
    "BLUEPRINT_TEMPLATE",
]
