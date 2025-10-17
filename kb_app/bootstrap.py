"""Bootstrap helpers for preparing the application database with demo data."""
from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

from .corpus_service import CorpusService
from .history_service import HistoryService
from .user_service import UserService


DEMO_USERNAME = "admin"
DEMO_PASSWORD = "Admin@123"
DEMO_CORPUS_NAME = "示例知识库"


def _copy_sample_corpus(target_root: Path) -> None:
    package_root = resources.files("kb_app.sample_data").joinpath("demo_corpus")
    target_root.mkdir(parents=True, exist_ok=True)
    for item in package_root.iterdir():
        destination = target_root / item.name
        if item.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(item, destination)
        else:
            shutil.copyfile(item, destination)


def ensure_seed_data(db_path: Path) -> None:
    """Ensure the database ships with a demo user, corpus and histories."""
    user_service = UserService(db_path)
    existing_users = user_service.list_users()
    if not existing_users:
        user_service.register_user(DEMO_USERNAME, DEMO_PASSWORD, is_admin=True)

    corpus_service = CorpusService(db_path)
    corpora = corpus_service.list_corpora()
    demo_base = Path.home() / "OfflineKnowledge" / "demo_corpus"
    if not any(corpus.name == DEMO_CORPUS_NAME for corpus in corpora):
        _copy_sample_corpus(demo_base)
        corpus = corpus_service.ensure_corpus(DEMO_CORPUS_NAME, base_path=demo_base)
        corpus_service.ingest_directory(corpus.id, demo_base, recursive=True)
    else:
        # refresh local mirror if files missing, but avoid re-ingest on every run
        if not demo_base.exists():
            _copy_sample_corpus(demo_base)

    history_service = HistoryService(db_path)
    if not history_service.list_histories():
        scenario_id = history_service.add_history(
            title="热处理炉异常停机决策",
            context=(
                "在夜班回火炉运行时，氧含量探头连续 5 分钟读数高于 0.35%，"
                "报警系统自动联锁停机，需判定是传感器故障还是气氛异常。"
            ),
            steps=(
                "1. 通知班组长现场确认安全状态并记录停机时间。\n"
                "2. 使用备用便携式分析仪复核氧含量数据。\n"
                "3. 检查混配气阀门与流量计是否卡滞，必要时切换至备用气源。"
            ),
            outcome="经排查发现混配阀卡涩，更换后恢复生产，并更新巡检保养计划。",
            tags=["热处理", "安全", "停机分析"],
        )
        history_service.add_comment(
            scenario_id,
            author=DEMO_USERNAME,
            comment="按照 SOP 执行后，停机时间控制在 40 分钟内，符合 KPI 要求。",
            rating=5,
        )
        backup_id = history_service.add_history(
            title="CNC 主轴震动快速处理决策",
            context="当主轴震动传感器超过 3.0 mm/s RMS 时的应对策略。",
            steps=(
                "1. 降低主轴转速 10% 并记录波形。\n"
                "2. 停机检查刀具夹持力，必要时重新夹紧或更换刀具。\n"
                "3. 若震动仍超限，通知维护工程师检查主轴轴承润滑。"
            ),
            outcome="更换刀具后震动恢复正常，同时补充主轴润滑油 30ml。",
            tags=["CNC", "维护", "震动监测"],
        )
        history_service.add_comment(
            backup_id,
            author="process_lead",
            comment="建议在每周例检中加入主轴夹头清洁项目。",
            rating=4,
        )


__all__ = ["ensure_seed_data", "DEMO_USERNAME", "DEMO_PASSWORD", "DEMO_CORPUS_NAME"]
