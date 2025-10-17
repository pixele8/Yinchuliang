import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kb_app.blueprint import BlueprintParsingError, KnowledgeBlueprint
from kb_app.knowledge_service import KnowledgeService
from kb_app.user_service import UserService


class BaseServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "kb.sqlite3"
        # Services lazily create the schema, so simply instantiating them is enough.
        self.knowledge_service = KnowledgeService(self.db_path)
        self.user_service = UserService(self.db_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class KnowledgeServiceAnswerTests(BaseServiceTestCase):
    def test_answer_returns_score_fallback_when_no_tokens_match(self) -> None:
        first_id = self.knowledge_service.add_entry(
            title="基础安全须知",
            question="如何启动机器？",
            answer="请按照操作手册逐步启动。",
            tags=["安全"],
        )
        second_id = self.knowledge_service.add_entry(
            title="维护提示",
            question="如何进行日常保养？",
            answer="定期清理并检查关键部件。",
            tags=["维护"],
        )

        results = self.knowledge_service.answer("完全无关的问题")

        self.assertEqual(len(results), 2)
        self.assertCountEqual([item[0].id for item in results], [first_id, second_id])
        self.assertTrue(all(score == 0.0 for _, score in results))

    def test_answer_prioritises_entries_with_higher_term_frequency(self) -> None:
        self.knowledge_service.add_entry(
            title="冷却液安全规范",
            question="如何处理冷却液泄漏？",
            answer="立刻停机并检查冷却液状态。",
            tags=["安全", "冷却液"],
        )
        self.knowledge_service.add_entry(
            title="冷却液维护周期",
            question="冷却液多久更换一次？",
            answer="每 200 小时检查一次冷却液状态。",
            tags=["维护", "冷却液"],
        )
        self.knowledge_service.add_entry(
            title="设备润滑计划",
            question="润滑剂需要多久补充？",
            answer="按照计划每月补充润滑剂。",
            tags=["维护"],
        )

        results = self.knowledge_service.answer("冷却液 安全")

        self.assertGreaterEqual(len(results), 2)
        self.assertIn("冷却液", results[0][0].tags)
        self.assertGreater(results[0][1], results[1][1])


class UserServiceTests(BaseServiceTestCase):
    def test_change_password_requires_correct_existing_secret(self) -> None:
        self.user_service.register_user("tester", "secret")

        self.assertFalse(self.user_service.change_password("tester", "wrong", "new-secret"))
        self.assertTrue(self.user_service.authenticate("tester", "secret"))

        self.assertTrue(self.user_service.change_password("tester", "secret", "new-secret"))
        self.assertTrue(self.user_service.authenticate("tester", "new-secret"))


class BlueprintParsingTests(unittest.TestCase):
    def test_parse_generates_entries_from_template_sections(self) -> None:
        blueprint_text = textwrap.dedent(
            """
            # 示例蓝图

            ```json
            {
              "type": "knowledge_blueprint",
              "process_name": "高精度车削",
              "summary": "介绍车削工艺的安全注意事项。",
              "tags": ["机加工"],
              "owner": "测试工程师",
              "version": "2.0",
              "last_reviewed": "2024-06-01"
            }
            ```

            ## 场景描述
            该工艺用于精密零件的最终加工。

            ## 操作步骤
            1. 检查工装夹具。
            2. 按照操作手册设置参数。

            ## 风险控制
            - 风险点: 刀具破损 — 应对: 立即停机并更换刀具。

            ## 常见问题
            ### Q: 刀具磨损过快怎么办？
            现象: 表面粗糙度超出标准。
            原因: 切削速度设置过高。
            措施: 调整切削速度并检查刀具。

            ## 参考资料
            - 《车削作业指导书》
            """
        ).strip()

        document = KnowledgeBlueprint.parse(blueprint_text)

        self.assertGreaterEqual(len(document.entries), 4)
        first_entry = document.entries[0]
        self.assertIn("蓝图", first_entry.tags)
        self.assertTrue(KnowledgeBlueprint.looks_like(blueprint_text))

    def test_missing_metadata_block_raises_error(self) -> None:
        invalid_text = "## 操作步骤\n1. 步骤"
        with self.assertRaises(BlueprintParsingError):
            KnowledgeBlueprint.parse(invalid_text)


if __name__ == "__main__":  # pragma: no cover - allow running directly
    unittest.main()
