import json
import unittest
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
import sys

# 项目路径配置
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 模块导入
from application.risk_guard import one_gate, apply_constraints_to_actions
from application.intent_router import route as route_intent
from application.planner import draft_plan
from application.verify import verify_actions, verify_draft
from application.FitForU_web import _run_one_gate, normalize_route_result

# 测试数据和报告路径
TEST_DATA_PATH = PROJECT_ROOT / "data" / "evaluation_test_cases.json"
REPORT_DIR = PROJECT_ROOT / "reports"
REPORT_DIR.mkdir(exist_ok=True)
REPORT_PATH = REPORT_DIR / "full_evaluation_report.json"


class TestRiskGuard(unittest.TestCase):
    """风险检测模块测试（从外部文件加载用例）"""

    @classmethod
    def setUpClass(cls):
        with open(TEST_DATA_PATH, 'r', encoding='utf-8') as f:
            test_data = json.load(f)
        cls.test_cases = test_data.get("risk_guard", [])
        cls.results = []

    def test_risk_detection(self):
        """测试风险等级判断准确性"""
        for case in self.test_cases:
            with self.subTest(input=case["input"]):
                # 执行风险检测
                result = one_gate(case["input"])
                actual_level = result.level
                expected_level = case["expected_level"]
                passed = actual_level == expected_level

                # 记录结果
                self.results.append({
                    "module": "risk_guard",
                    "test_type": "level_detection",
                    "input": case["input"],
                    "expected": expected_level,
                    "actual": actual_level,
                    "passed": passed
                })

                self.assertEqual(actual_level, expected_level)

    def test_constraint_application(self):
        """测试约束条件应用正确性"""
        # 从测试数据中筛选需要验证约束的用例
        constraint_cases = [
            case for case in self.test_cases
            if case["expected_level"] == "CAUTION" and "constraints" in case
        ]

        for case in constraint_cases:
            with self.subTest(input=case["input"]):
                # 获取风险检测结果中的约束
                risk_result = one_gate(case["input"])
                test_actions = case["test_actions"]

                # 应用约束
                adjusted_actions = apply_constraints_to_actions(
                    test_actions, risk_result.constraints
                )

                # 验证约束应用结果
                passed = all(
                    constraint in adjusted_actions[0]["desc"]
                    for constraint in case["expected_constraints"]
                )

                self.results.append({
                    "module": "risk_guard",
                    "test_type": "constraint_application",
                    "input": case["input"],
                    "expected": case["expected_constraints"],
                    "actual": [a["desc"] for a in adjusted_actions],
                    "passed": passed
                })

                self.assertTrue(passed)


class TestIntentRouter(unittest.TestCase):
    """意图路由模块测试（从外部文件加载用例）"""

    @classmethod
    def setUpClass(cls):
        with open(TEST_DATA_PATH, 'r', encoding='utf-8') as f:
            test_data = json.load(f)
        cls.test_cases = test_data.get("intent_router", [])
        cls.results = []

    def test_intent_classification(self):
        """测试意图分类准确性"""
        for case in self.test_cases:
            with self.subTest(input=case["input"]):
                # 执行意图路由
                raw_result = route_intent(case["input"])
                normalized = normalize_route_result(raw_result)
                actual_intent = normalized["intent"]
                expected_intent = case["expected_intent"]
                passed = actual_intent == expected_intent

                # 记录结果
                self.results.append({
                    "module": "intent_router",
                    "input": case["input"],
                    "expected": expected_intent,
                    "actual": actual_intent,
                    "confidence": normalized["confidence"],
                    "passed": passed
                })

                self.assertEqual(actual_intent, expected_intent)


class TestPlannerAndVerify(unittest.TestCase):
    """计划生成与验证模块测试"""

    @classmethod
    def setUpClass(cls):
        with open(TEST_DATA_PATH, 'r', encoding='utf-8') as f:
            test_data = json.load(f)
        cls.plan_cases = test_data.get("planner", [])
        cls.verify_cases = test_data.get("verifier", [])
        cls.results = []

    def test_plan_generation(self):
        """测试计划生成基本结构"""
        for case in self.plan_cases:
            with self.subTest(input=case["input"]):
                # 生成计划
                plan = draft_plan(case["input"], case["config"])

                # 验证基本结构
                passed = (
                        isinstance(plan, dict) and
                        plan.get("horizon_days") == case["config"]["horizon_days"] and
                        len(plan.get("modules", [])) > 0
                )

                self.results.append({
                    "module": "planner",
                    "input": case["input"],
                    "expected": f"horizon_days={case['config']['horizon_days']}, modules>0",
                    "actual": f"horizon_days={plan.get('horizon_days')}, modules={len(plan.get('modules', []))}",
                    "passed": passed
                })

                self.assertTrue(passed)

    def test_plan_verification(self):
        """测试计划验证功能"""
        for case in self.verify_cases:
            with self.subTest(case=case["name"]):
                # 执行验证
                result = verify_draft(case["draft"])
                passed = result.ok == case["expected_ok"]

                # 记录结果
                self.results.append({
                    "module": "verifier",
                    "test_name": case["name"],
                    "expected": f"ok={case['expected_ok']}",
                    "actual": f"ok={result.ok}, errors={result.counts['ERROR']}",
                    "passed": passed
                })

                self.assertEqual(result.ok, case["expected_ok"])


class TestEndToEnd(unittest.TestCase):
    """端到端流程测试"""

    @classmethod
    def setUpClass(cls):
        with open(TEST_DATA_PATH, 'r', encoding='utf-8') as f:
            test_data = json.load(f)
        cls.test_cases = test_data.get("end_to_end", [])
        cls.results = []

    def test_full_flow(self):
        """测试完整流程：输入→风险检测→意图路由→计划生成→验证"""
        for case in self.test_cases:
            with self.subTest(input=case["input"]):
                # 1. 风险检测
                risk_result = _run_one_gate(case["input"])
                risk_passed = risk_result["level"] == case["expected_risk"]

                # 2. 意图路由
                intent_result = normalize_route_result(route_intent(case["input"]))
                intent_passed = intent_result["intent"] == case["expected_intent"]

                # 3. 计划生成与验证（仅当无风险时）
                plan_passed = True
                if risk_result["level"] == "OK":
                    plan = draft_plan(case["input"], case["planner_config"])
                    verify_result = verify_draft(plan)
                    plan_passed = verify_result.ok == case["expected_plan_valid"]

                # 综合结果
                passed = risk_passed and intent_passed and plan_passed

                # 记录结果
                self.results.append({
                    "module": "end_to_end",
                    "input": case["input"],
                    "expected": {
                        "risk_level": case["expected_risk"],
                        "intent": case["expected_intent"],
                        "plan_valid": case["expected_plan_valid"]
                    },
                    "actual": {
                        "risk_level": risk_result["level"],
                        "intent": intent_result["intent"],
                        "plan_valid": plan_passed
                    },
                    "passed": passed
                })

                self.assertTrue(passed)


def generate_evaluation_report(all_results: List[Dict[str, Any]]):
    """生成综合评估报告"""
    # 计算整体统计
    total = len(all_results)
    passed = sum(1 for r in all_results if r["passed"])
    overall_accuracy = (passed / total * 100) if total > 0 else 0

    # 按模块统计
    modules = set(r["module"] for r in all_results)
    module_stats = {}
    for module in modules:
        module_cases = [r for r in all_results if r["module"] == module]
        module_passed = sum(1 for r in module_cases if r["passed"])
        module_total = len(module_cases)
        module_stats[module] = {
            "total": module_total,
            "passed": module_passed,
            "failed": module_total - module_passed,
            "accuracy": (module_passed / module_total * 100) if module_total > 0 else 0
        }

    # 详细结果分类
    details = {
        "correct": [r for r in all_results if r["passed"]],
        "incorrect": [r for r in all_results if not r["passed"]]
    }

    # 生成报告
    report = {
        "evaluation_time": datetime.now().isoformat(),
        "summary": {
            "total_cases": total,
            "passed_cases": passed,
            "failed_cases": total - passed,
            "overall_accuracy": f"{overall_accuracy:.2f}%",
            "module_stats": module_stats
        },
        "details": details
    }

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"评估报告已生成：{REPORT_PATH}")


if __name__ == "__main__":
    # 加载所有测试
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # 添加所有测试类
    suite.addTests(loader.loadTestsFromTestCase(TestRiskGuard))
    suite.addTests(loader.loadTestsFromTestCase(TestIntentRouter))
    suite.addTests(loader.loadTestsFromTestCase(TestPlannerAndVerify))
    suite.addTests(loader.loadTestsFromTestCase(TestEndToEnd))

    # 运行测试并收集结果
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # 收集所有测试结果
    all_results = []
    all_results.extend(TestRiskGuard.results)
    all_results.extend(TestIntentRouter.results)
    all_results.extend(TestPlannerAndVerify.results)
    all_results.extend(TestEndToEnd.results)

    # 生成报告
    generate_evaluation_report(all_results)