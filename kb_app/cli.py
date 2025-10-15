"""Command line interface for the offline knowledge base system."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from .history_service import HistoryService
from .knowledge_service import KnowledgeService
from .user_service import UserService

DEFAULT_DB = Path.home() / ".local" / "share" / "offline_kb" / "knowledge.db"


def parse_tags(text: str | None) -> list[str]:
    if not text:
        return []
    return [tag.strip() for tag in text.split(",") if tag.strip()]


def format_tags(tags: Iterable[str]) -> str:
    return ", ".join(tags)


def ensure_actor(actor: str | None) -> str:
    if not actor:
        raise SystemExit("此操作需要使用 --actor 指定执行人。")
    return actor


def add_knowledge(args: argparse.Namespace) -> None:
    service = KnowledgeService(args.database)
    entry_id = service.add_entry(
        title=args.title,
        question=args.question,
        answer=args.answer,
        tags=parse_tags(args.tags),
    )
    print(f"知识条目已保存，编号: {entry_id}")


def list_knowledge(args: argparse.Namespace) -> None:
    service = KnowledgeService(args.database)
    for entry in service.list_entries():
        print(f"[{entry.id}] {entry.title} | 标签: {format_tags(entry.tags)} | 创建于 {entry.created_at}")
        print(f"问题: {entry.question}")
        print(f"答案: {entry.answer}\n")


def ask_question(args: argparse.Namespace) -> None:
    service = KnowledgeService(args.database)
    answers = service.answer(args.question, limit=args.limit)
    if not answers:
        print("知识库中暂无匹配条目，请先添加相关知识。")
        return
    for entry, score in answers:
        print(f"[{entry.id}] {entry.title} (匹配度: {score:.2f})")
        print(f"问题: {entry.question}")
        print(f"答案: {entry.answer}")
        if entry.tags:
            print(f"标签: {format_tags(entry.tags)}")
        print("-")


def add_history(args: argparse.Namespace) -> None:
    service = HistoryService(args.database)
    history_id = service.add_history(
        title=args.title,
        context=args.context,
        steps=args.steps,
        outcome=args.outcome,
        tags=parse_tags(args.tags),
    )
    print(f"决策链已保存，编号: {history_id}")


def list_histories(args: argparse.Namespace) -> None:
    service = HistoryService(args.database)
    for history in service.list_histories():
        print(f"[{history.id}] {history.title} | 标签: {format_tags(history.tags)} | 创建于 {history.created_at}")
        print(f"背景: {history.context}")
        print(f"步骤: {history.steps}")
        if history.outcome:
            print(f"结果: {history.outcome}")
        comments = service.list_comments(history.id)
        if comments:
            print("评论:")
            for comment in comments:
                rating = f" 评分: {comment.rating}" if comment.rating is not None else ""
                print(f" - {comment.author} ({comment.created_at}{rating}): {comment.comment}")
        print("-")


def search_histories(args: argparse.Namespace) -> None:
    service = HistoryService(args.database)
    results = service.search_histories(args.query, limit=args.limit)
    if not results:
        print("未找到匹配的决策链，请尝试其他关键词。")
        return
    for history in results:
        print(f"[{history.id}] {history.title} | 标签: {format_tags(history.tags)}")
        print(f"背景: {history.context}")
        print(f"步骤: {history.steps}")
        if history.outcome:
            print(f"结果: {history.outcome}")
        print("-")


def comment_history(args: argparse.Namespace) -> None:
    service = HistoryService(args.database)
    comment_id = service.add_comment(
        history_id=args.history_id,
        author=args.author,
        comment=args.comment,
        rating=args.rating,
    )
    print(f"评论已保存，编号: {comment_id}")


def register_user(args: argparse.Namespace) -> None:
    service = UserService(args.database)
    try:
        user_id = service.register_user(
            username=args.username,
            password=args.password,
            is_admin=args.admin,
        )
    except ValueError as exc:
        print(f"创建用户失败: {exc}")
        return
    actor = args.actor or args.username
    if args.admin:
        service.record_admin_action(actor, "create_admin", args.username, "创建管理员账户")
    else:
        service.record_admin_action(actor, "register_user", args.username)
    role = "管理员" if args.admin else "普通用户"
    print(f"用户已注册，编号: {user_id}，角色: {role}")


def list_users(args: argparse.Namespace) -> None:
    service = UserService(args.database)
    users = service.list_users()
    if not users:
        print("尚未创建任何用户。")
        return
    for user in users:
        status = "启用" if user.is_active else "停用"
        role = "管理员" if user.is_admin else "用户"
        print(f"[{user.id}] {user.username} | {role} | 状态: {status} | 注册于 {user.created_at}")


def promote_user(args: argparse.Namespace) -> None:
    service = UserService(args.database)
    actor = ensure_actor(args.actor)
    try:
        user = service.require_existing_user(args.username)
        if user.is_admin:
            print("该用户已经是管理员。")
            return
        service.set_admin(user.username, True)
        service.record_admin_action(actor, "promote_admin", user.username)
        print(f"用户 {user.username} 已升级为管理员。")
    except ValueError as exc:
        print(exc)


def demote_user(args: argparse.Namespace) -> None:
    service = UserService(args.database)
    actor = ensure_actor(args.actor)
    try:
        user = service.require_existing_user(args.username)
        if not user.is_admin:
            print("该用户本身不是管理员。")
            return
        service.set_admin(user.username, False)
        service.record_admin_action(actor, "demote_admin", user.username)
        print(f"用户 {user.username} 的管理员权限已移除。")
    except ValueError as exc:
        print(exc)


def activate_user(args: argparse.Namespace) -> None:
    service = UserService(args.database)
    actor = ensure_actor(args.actor)
    try:
        user = service.require_existing_user(args.username)
        if user.is_active:
            print("该用户已经是启用状态。")
            return
        service.set_active(user.username, True)
        service.record_admin_action(actor, "activate_user", user.username)
        print(f"用户 {user.username} 已启用。")
    except ValueError as exc:
        print(exc)


def deactivate_user(args: argparse.Namespace) -> None:
    service = UserService(args.database)
    actor = ensure_actor(args.actor)
    try:
        user = service.require_existing_user(args.username)
        if not user.is_active:
            print("该用户已经是停用状态。")
            return
        service.set_active(user.username, False)
        service.record_admin_action(actor, "deactivate_user", user.username)
        print(f"用户 {user.username} 已停用。")
    except ValueError as exc:
        print(exc)


def reset_password(args: argparse.Namespace) -> None:
    service = UserService(args.database)
    actor = ensure_actor(args.actor)
    try:
        service.require_existing_user(args.username)
        service.reset_password(args.username, args.password)
        service.record_admin_action(actor, "reset_password", args.username)
        print(f"用户 {args.username} 的密码已重置。")
    except ValueError as exc:
        print(exc)


def admin_summary(args: argparse.Namespace) -> None:
    service = UserService(args.database)
    summary = service.summary()
    print("系统总览：")
    print(f" - 知识条目: {summary['knowledge']}")
    print(f" - 决策链: {summary['histories']}")
    print(f" - 评论数量: {summary['comments']}")
    print(f" - 注册用户: {summary['users']}")
    print(f" - 管理员: {summary['admins']}")
    print(f" - 启用用户: {summary['active_users']}")


def view_admin_log(args: argparse.Namespace) -> None:
    service = UserService(args.database)
    events = service.list_admin_events(limit=args.limit)
    if not events:
        print("暂无管理员操作记录。")
        return
    for event in events:
        subject = event.subject or "-"
        details = event.details or ""
        print(f"[{event.id}] {event.created_at} {event.actor} -> {event.action} @ {subject} {details}")


def export_data(args: argparse.Namespace) -> None:
    db_path = args.database
    knowledge_service = KnowledgeService(db_path)
    history_service = HistoryService(db_path)
    data = {
        "knowledge": [entry.__dict__ for entry in knowledge_service.list_entries()],
        "histories": [history.__dict__ for history in history_service.list_histories()],
        "comments": [
            comment.__dict__
            for history in history_service.list_histories()
            for comment in history_service.list_comments(history.id)
        ],
    }
    Path(args.output).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"数据已导出到 {args.output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="离线知识库与决策管理系统")
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DB,
        help=f"数据库文件路径 (默认: {DEFAULT_DB})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_add = subparsers.add_parser("add-knowledge", help="新增知识条目")
    parser_add.add_argument("title", help="标题")
    parser_add.add_argument("question", help="问题描述")
    parser_add.add_argument("answer", help="答案或处理方式")
    parser_add.add_argument("--tags", help="标签，使用逗号分隔")
    parser_add.set_defaults(func=add_knowledge)

    parser_list = subparsers.add_parser("list-knowledge", help="列出所有知识条目")
    parser_list.set_defaults(func=list_knowledge)

    parser_ask = subparsers.add_parser("ask", help="根据知识库自动回答问题")
    parser_ask.add_argument("question", help="提出的问题")
    parser_ask.add_argument("--limit", type=int, default=3, help="返回的答案数量")
    parser_ask.set_defaults(func=ask_question)

    parser_history_add = subparsers.add_parser("add-history", help="新增决策链记录")
    parser_history_add.add_argument("title", help="标题")
    parser_history_add.add_argument("context", help="背景信息")
    parser_history_add.add_argument("steps", help="处理步骤或决策链描述")
    parser_history_add.add_argument("--outcome", help="最终结果")
    parser_history_add.add_argument("--tags", help="标签，使用逗号分隔")
    parser_history_add.set_defaults(func=add_history)

    parser_history_list = subparsers.add_parser("list-history", help="查看全部决策链")
    parser_history_list.set_defaults(func=list_histories)

    parser_history_search = subparsers.add_parser("search-history", help="搜索历史决策")
    parser_history_search.add_argument("query", help="关键词")
    parser_history_search.add_argument("--limit", type=int, default=5, help="返回的记录数量")
    parser_history_search.set_defaults(func=search_histories)

    parser_history_comment = subparsers.add_parser("comment-history", help="给决策链添加评论")
    parser_history_comment.add_argument("history_id", type=int, help="决策链编号")
    parser_history_comment.add_argument("author", help="评论人")
    parser_history_comment.add_argument("comment", help="评论内容")
    parser_history_comment.add_argument("--rating", type=int, help="评分 (0-5)")
    parser_history_comment.set_defaults(func=comment_history)

    parser_user_register = subparsers.add_parser("register-user", help="注册本地用户")
    parser_user_register.add_argument("username", help="用户名")
    parser_user_register.add_argument("password", help="密码")
    parser_user_register.add_argument("--admin", action="store_true", help="将新用户设置为管理员")
    parser_user_register.add_argument("--actor", help="执行该操作的用户名")
    parser_user_register.set_defaults(func=register_user)

    parser_user_list = subparsers.add_parser("list-users", help="查看所有注册用户")
    parser_user_list.set_defaults(func=list_users)

    parser_promote = subparsers.add_parser("promote-user", help="赋予用户管理员权限")
    parser_promote.add_argument("username", help="目标用户名")
    parser_promote.add_argument("--actor", help="执行该操作的管理员用户名")
    parser_promote.set_defaults(func=promote_user)

    parser_demote = subparsers.add_parser("demote-user", help="移除用户的管理员权限")
    parser_demote.add_argument("username", help="目标用户名")
    parser_demote.add_argument("--actor", help="执行该操作的管理员用户名")
    parser_demote.set_defaults(func=demote_user)

    parser_activate = subparsers.add_parser("activate-user", help="启用已停用的用户")
    parser_activate.add_argument("username", help="目标用户名")
    parser_activate.add_argument("--actor", help="执行该操作的管理员用户名")
    parser_activate.set_defaults(func=activate_user)

    parser_deactivate = subparsers.add_parser("deactivate-user", help="停用用户账户")
    parser_deactivate.add_argument("username", help="目标用户名")
    parser_deactivate.add_argument("--actor", help="执行该操作的管理员用户名")
    parser_deactivate.set_defaults(func=deactivate_user)

    parser_reset_password = subparsers.add_parser("reset-password", help="重置用户密码")
    parser_reset_password.add_argument("username", help="目标用户名")
    parser_reset_password.add_argument("password", help="新密码")
    parser_reset_password.add_argument("--actor", help="执行该操作的管理员用户名")
    parser_reset_password.set_defaults(func=reset_password)

    parser_admin_summary = subparsers.add_parser("admin-summary", help="查看系统数据概览")
    parser_admin_summary.set_defaults(func=admin_summary)

    parser_admin_log = subparsers.add_parser("admin-log", help="查看管理员操作记录")
    parser_admin_log.add_argument("--limit", type=int, default=20, help="显示的记录数量")
    parser_admin_log.set_defaults(func=view_admin_log)

    parser_export = subparsers.add_parser("export", help="导出全部数据为 JSON")
    parser_export.add_argument("output", help="输出文件路径")
    parser_export.set_defaults(func=export_data)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.database.parent.mkdir(parents=True, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
