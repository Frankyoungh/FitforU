# # -*- coding: utf-8 -*-
# """
# application/intent_router.py
#
# 轻量级输入分流器：规则 → 关键词，仅做「意图分类」，不直接生成计划。
#
# 主程序约定：
# - 暴露 route_intent(text: str) 或 route(text: str)
# - 返回：
#     - dict: { "intent": str, "confidence": float, "reason": str, ... }
#     - 或 dataclass，主程序的 normalize_route_result 会兼容解析
#
# 意图类别：
#   - HEALTH_PLAN    通用健康/作息/节律计划
#   - FITNESS_GYM    健身/训练
#   - NUTRITION      饮食/营养
#   - REHAB          康复/恢复
#   - HEALTH_QA      一般健康问答
#   - HIGH_RISK      高风险（急症/剂量/孕妇儿童用药等）
#   - SMALL_TALK     闲聊
#
# 策略要点：
# - HIGH_RISK > SMALL_TALK > 具体计划/训练类 > HEALTH_QA > fallback
# - SMALL_TALK 有显式聊天词时优先（修正“今天有点累，不想训练，跟你随便聊聊”被错分成 FITNESS_GYM 的问题）
# """
#
# from dataclasses import dataclass
# from typing import Optional
#
#
# @dataclass
# class RouteResult:
#     intent: str
#     confidence: float
#     via: str = "rule"
#     reason: str = ""
#     triage: str = ""   # 可选：HIGH_RISK 分诊文案
#
#
# def _strip(text: str) -> str:
#     return (text or "").strip()
#
#
# def _has_any(text: str, keywords) -> bool:
#     return any(k in text for k in keywords)
#
#
# # ===== 关键词配置 =====
#
# # 高风险：症状 + 剂量 + 特殊人群
# HIGH_RISK_KEYWORDS = [
#     "胸痛", "胸闷", "胸悶", "呼吸困难", "上不来气", "大出血", "喷射状出血",
#     "昏迷", "昏厥", "抽搐",
#     "心梗", "脑梗", "腦梗", "脑出血", "心绞痛",
#     "猝死", "濒死",
# ]
# HIGH_RISK_MED_KEYWORDS = [
#     "毫升", "ml", "mg", "剂量", "幾毫升", "几毫升", "几粒", "幾粒",
#     "处方药", "处方藥", "布洛芬", "对乙酰氨基酚", "退烧药", "退燒藥",
#     "优甲乐", "胰岛素", "华法林", "肝素",
# ]
# HIGH_RISK_POP_KEYWORDS = [
#     "孕妇能不能用", "怀孕可以吃吗", "怀孕可以用吗",
#     "儿童可以吃吗", "小孩可以吃吗", "小朋友可以吃吗",
# ]
#
# PLAN_KEYWORDS = ["计划", "方案", "表格", "安排", "制定", "出一份", "计划表", "program", "plan"]
#
# FITNESS_KEYWORDS = [
#     "健身", "力量训练", "力量練習",
#     "增肌", "减脂", "減脂",
#     "卧推", "深蹲", "硬拉", "推举", "划船",
#     "HIIT", "有氧", "无氧", "心肺训练",
#     "训练", "練習", "练腿", "练背", "练胸", "练肩", "练手", "练腹",
# "workout", "strength training", "muscle building", "fat loss",
#     "bench press", "squat", "deadlift", "HIIT", "aerobic", "anaerobic"
# ]
#
# NUTRITION_KEYWORDS = [
#     "饮食", "飲食", "配餐", "餐单", "食谱", "食譜", "三餐",
#     "热量", "卡路里", "千卡", "大卡",
#     "蛋白质", "碳水", "脂肪",
#     "减脂餐", "增肌餐",
# "diet", "nutrition", "calorie", "protein", "carb", "fat",
#     "meal plan", "bulk meal", "cut meal"
# ]
#
# REHAB_KEYWORDS = [
#     "康复", "康復", "理疗", "理療",
#     "拉伸", "放松", "放鬆", "恢复训练",
#     "术后恢复", "術後恢復",
#     "肩周炎", "网球肘", "腰痛", "腰酸", "膝盖痛", "膝蓋痛",
#     "肌肉酸痛", "运动损伤", "延迟性肌肉酸痛", "DOMS",
#     "锐痛", "刺痛", "酸胀", "钝痛", "区分疼痛",
# "rehab", "recovery", "stretching", "muscle soreness",
#     "sports injury", "DOMS", "sharp pain", "dull pain"
# ]
#
# HEALTH_QA_KEYWORDS = [
#     "为什么", "為什麼",
#     "原因", "影响", "影響",
#     "有坏处吗", "有壞處嗎",
#     "有危害吗", "有危害嗎",
#     "健康吗", "健康嗎",
#     "注意什么", "注意什麼",
#     "如何区分", "怎么判断", "区别是什么"
# ]
#
# SMALL_TALK_HINTS = [
#     "随便聊聊", "隨便聊聊",
#     "聊聊天", "聊聊",
#     "闲聊", "閒聊",
#     "扯扯淡",
#     "你在吗", "你在嗎", "在吗", "在嗎",
#     "最近怎么样", "最近怎麼樣", "最近如何",
#     "有点无聊", "有點無聊", "好无聊", "好無聊",
#     "陪我聊会儿", "陪我聊會兒",
# ]
#
# NEG_FITNESS_PATTERNS = [
#     "不想训练", "不太想训练", "不想練", "不太想練",
#     "今天有点累", "今天有點累",
#     "累了不想动", "累了不想動",
#     "休息一天", "今天休息",
# ]
# from application.language_utils import detect_language
#
# # ===== 规则实现 =====
#
# def _rule_high_risk(text: str) -> Optional[RouteResult]:
#     if _has_any(text, HIGH_RISK_KEYWORDS) or _has_any(text, HIGH_RISK_MED_KEYWORDS) or _has_any(text, HIGH_RISK_POP_KEYWORDS):
#         return RouteResult(
#             intent="HIGH_RISK",
#             confidence=0.98,
#             via="rule:high_risk",
#             reason="命中高风险症状/用药/特殊人群问药关键词",
#             triage="涉及潜在急症或用药剂量问题，请尽快线下就医或咨询专业医生。"
#         )
#     return None
#
#
# def _rule_small_talk(text: str) -> Optional[RouteResult]:
#     """
#     SMALL_TALK 优先级：
#     - 出现明显聊天意图
#     - 且没有清晰“帮我制定计划/训练/饮食/康复方案”请求
#     - 或「不想训练/很累」+ 聊天意图 → 强制 SMALL_TALK
#     """
#     has_chat = _has_any(text, SMALL_TALK_HINTS)
#     has_neg_fitness = _has_any(text, NEG_FITNESS_PATTERNS)
#     strong_plan_ask = _has_any(text, PLAN_KEYWORDS) or "帮我" in text or "幫我" in text or "出个" in text or "出個" in text
#
#     # 关键修正：今天有点累，不想训练，跟你随便聊聊。
#     if has_chat and has_neg_fitness and not strong_plan_ask:
#         return RouteResult(
#             intent="SMALL_TALK",
#             confidence=0.99,
#             via="rule:small_talk_override",
#             reason="聊天意图 + 不想训练，覆盖训练关键词"
#         )
#
#     if has_chat and not strong_plan_ask:
#         return RouteResult(
#             intent="SMALL_TALK",
#             confidence=0.95,
#             via="rule:small_talk",
#             reason="出现明显聊天意图，且未出现明确计划/训练请求"
#         )
#
#     return None
#
#
# def _rule_fitness(text: str) -> Optional[RouteResult]:
#     # 负向过滤：如果是“不想训练/今天很累”且无计划请求，交给 small_talk 处理，不在这里判 FITNESS_GYM
#     if _has_any(text, NEG_FITNESS_PATTERNS) and not _has_any(text, PLAN_KEYWORDS):
#         return None
#
#     if _has_any(text, FITNESS_KEYWORDS) and _has_any(text, PLAN_KEYWORDS):
#         return RouteResult(
#             intent="FITNESS_GYM",
#             confidence=0.9,
#             via="rule:fitness+plan",
#             reason="训练相关 + 计划/安排关键词"
#         )
#
#     if _has_any(text, FITNESS_KEYWORDS):
#         # 问“动作对不对”“怎么练”之类
#         if "怎么" in text or "如何" in text or "对吗" in text or "對嗎" in text or "标准" in text or "標準" in text:
#             return RouteResult(
#                 intent="FITNESS_GYM",
#                 confidence=0.8,
#                 via="rule:fitness_qa",
#                 reason="训练相关问答"
#             )
#         # 泛训练讨论，略低置信度
#         return RouteResult(
#             intent="FITNESS_GYM",
#             confidence=0.6,
#             via="rule:fitness_generic",
#             reason="出现训练相关关键词"
#         )
#
#     return None
#
#
# def _rule_nutrition(text: str) -> Optional[RouteResult]:
#     if _has_any(text, NUTRITION_KEYWORDS) and _has_any(text, PLAN_KEYWORDS):
#         return RouteResult(
#             intent="NUTRITION",
#             confidence=0.9,
#             via="rule:nutrition+plan",
#             reason="饮食/营养 + 计划/配餐关键词"
#         )
#     if _has_any(text, NUTRITION_KEYWORDS):
#         return RouteResult(
#             intent="NUTRITION",
#             confidence=0.75,
#             via="rule:nutrition",
#             reason="饮食/营养相关问题"
#         )
#     return None
#
#
# def _rule_rehab(text: str) -> Optional[RouteResult]:
#     if _has_any(text, REHAB_KEYWORDS) and _has_any(text, PLAN_KEYWORDS):
#         return RouteResult(
#             intent="REHAB",
#             confidence=0.9,
#             via="rule:rehab+plan",
#             reason="康复/疼痛 + 计划关键词"
#         )
#     if _has_any(text, REHAB_KEYWORDS):
#         return RouteResult(
#             intent="REHAB",
#             confidence=0.8,
#             via="rule:rehab",
#             reason="康复/疼痛管理相关"
#         )
#     return None
#
#
# def _rule_health_plan(text: str) -> Optional[RouteResult]:
#     if _has_any(text, PLAN_KEYWORDS) and any(k in text for k in ["作息", "节律", "節律", "睡眠", "习惯", "習慣"]):
#         return RouteResult(
#             intent="HEALTH_PLAN",
#             confidence=0.85,
#             via="rule:health_plan",
#             reason="作息/节律/习惯 + 计划关键词"
#         )
#     return None
#
#
# def _rule_health_qa(text: str) -> Optional[RouteResult]:
#     if _has_any(text, HEALTH_QA_KEYWORDS) or "健康" in text or "睡眠" in text or "熬夜" in text:
#         return RouteResult(
#             intent="HEALTH_QA",
#             confidence=0.6,
#             via="rule:health_qa",
#             reason="健康相关问答（非急症/非处方剂量）"
#         )
#     return None
#
#
# def _fallback(text: str) -> RouteResult:
#     # 有健康/训练词但没命中具体类：给 HEALTH_QA
#     if any(k in text for k in ["健康", "训练", "健身", "运动", "運動", "饮食", "睡眠", "作息", "肥胖", "减肥", "減肥", "增肌"]):
#         return RouteResult(
#             intent="HEALTH_QA",
#             confidence=0.4,
#             via="fallback:healthish",
#             reason="泛健康语义，未命中更具体规则"
#         )
#     # 否则当闲聊
#     return RouteResult(
#         intent="SMALL_TALK",
#         confidence=0.4,
#         via="fallback:small_talk",
#         reason="未检测到健康相关关键词，按闲聊处理"
#     )
#
#
# # ===== 主入口 =====
#
# def route(text: str) -> RouteResult:
#     msg = _strip(text)
#     if not msg:
#         return RouteResult(
#             intent="SMALL_TALK",
#             confidence=0.1,
#             via="empty",
#             reason="空输入"
#         )
#     lang = detect_language(msg)
#     msg_lower = msg.lower()  # 英文统一小写处理
#
#     # 修改关键词检测函数，适配英文
#     def _has_any(text: str, keywords) -> bool:
#         text_lower = text.lower()
#         return any(k in text_lower for k in keywords)
#     # 1. 高风险最高优先
#     r = _rule_high_risk(msg)
#     if r:
#         return r
#
#     # 2. SMALL_TALK 提前，避免被训练关键词误伤
#     r = _rule_small_talk(msg)
#     if r:
#         return r
#
#     # 3. 明确类目（顺序有意义）
#     for fn in (
#         _rule_fitness,
#         _rule_nutrition,
#         _rule_rehab,
#         _rule_health_plan,
#         _rule_health_qa,
#     ):
#         r = fn(msg)
#         if r:
#             return r
#
#     # 4. 兜底
#     return _fallback(msg)
#
#
from __future__ import annotations
def route_intent(text: str):
    """
    供主应用调用的兼容接口：
    返回 dict，normalize_route_result 会处理。
    """
    r = route(text)
    return {
        "intent": r.intent,
        "confidence": float(r.confidence),
        "reason": f"{r.via}: {r.reason}",
        # "triage": r.triage,
    }


# if __name__ == "__main__":
#     tests = [
#         "帮我做一个7天的作息节律计划，晚8点以后可训练",
#         "我想要一份增肌训练计划，包含深蹲硬拉卧推",
#         "晚餐怎么配餐更健康？控制热量到1800千卡",
#         "膝盖不适，想做一些拉伸康复动作",
#         "为什么睡前喝咖啡会影响睡眠？",
#         "孩子发烧可以吃多少毫升布洛芬？",
#         "今天天气真不错呀",
#         "今天有点累，不想训练，跟你随便聊聊。",
#         "今天有点累，不想训练，帮我看看有没有更轻松的拉伸计划。",
#     ]
#     for t in tests:
#         res = route(t)
#         print(f"[{t}] -> {res.intent} | {res.confidence:.2f} | via={res.via} | {res.reason}")
#         if res.triage:
#             print("  TRIAGE:", res.triage)
#
# -*- coding: utf-8 -*-

from dataclasses import dataclass
from typing import Optional, List
import re

# 新增语言检测工具引用
from application.language_utils import detect_language

# -------------------------- 核心关键词定义（中英双语）--------------------------
# 健身相关关键词
FITNESS_KEYWORDS = [
    # 中文关键词
    "健身", "力量训练", "肌力", "塑形", "减脂", "增肌", "训练", "举重", "卧推", "深蹲",
    "硬拉", "划船", "下拉", "肩推", "HIIT", "有氧", "无氧", "器械", "徒手", "组数", "次数",
    "组间休息", "RM", "训练计划", "分化训练", "全身训练", "核心训练", "上肢训练", "下肢训练",
    # 英文关键词
    "workout", "strength training", "muscle building", "fat loss", "muscle gain",
    "bench press", "squat", "deadlift", "row", "pull down", "shoulder press",
    "HIIT", "aerobic", "anaerobic", "gym equipment", "bodyweight exercise",
    "sets", "reps", "rest time", "RM", "training plan", "split training",
    "full-body workout", "core training", "upper body workout", "lower body workout"
]

# 营养相关关键词
NUTRITION_KEYWORDS = [
    # 中文关键词
    "饮食", "热量", "营养", "蛋白质", "碳水", "脂肪", "卡路里", "配餐", "备餐", "减脂餐",
    "增肌餐", "饮食计划", "宏量营养素", "微量营养素", "膳食纤维", "升糖指数", "饱腹感",
    # 英文关键词
    "diet", "nutrition", "calorie", "protein", "carb", "carbohydrate", "fat",
    "meal plan", "bulk meal", "cut meal", "macronutrient", "micronutrient",
    "dietary fiber", "glycemic index", "satiety", "meal prep", "nutrient intake"
]

# 康复相关关键词
REHAB_KEYWORDS = [
    # 中文关键词
    "康复", "肌肉酸痛", "运动损伤", "拉伸", "理疗", "肩痛", "颈痛", "腰痛", "膝痛", "术后恢复",
    "关节不适", "肌肉拉伤", "韧带扭伤", "DOMS", "钝痛", "锐痛", "活动受限", "恢复训练",
    # 英文关键词
    "rehab", "recovery", "stretching", "physical therapy", "muscle soreness",
    "sports injury", "DOMS", "sharp pain", "dull pain", "shoulder pain",
    "neck pain", "back pain", "knee pain", "post-surgery recovery",
    "joint discomfort", "muscle strain", "ligament sprain", "limited movement"
]

# 高风险相关关键词（需优先拦截）
HIGH_RISK_KEYWORDS = [
    # 中文关键词
    "胸痛", "呼吸困难", "晕厥", "大出血", "意识模糊", "剧烈头痛", "呕吐", "高烧", "骨折", "脱位",
    # 英文关键词
    "chest pain", "difficulty breathing", "shortness of breath", "fainting",
    "severe bleeding", "loss of consciousness", "severe headache", "vomiting",
    "high fever", "fracture", "dislocation"
]

# 健康问答关键词
HEALTH_QA_KEYWORDS = [
    # 中文关键词
    "为什么", "原因", "影响", "危害", "注意什么", "怎么办", "如何", "怎么", "是否", "能不能",
    "可以吗", "应该", "建议", "区别", "区分", "判断",
    # 英文关键词
    "why", "reason", "impact", "harm", "what to note", "how to", "how", "can",
    "whether", "difference", "distinguish", "judge", "suggestion", "advice"
]

# 闲聊关键词（兜底）
SMALL_TALK_KEYWORDS = [
    # 中文关键词
    "你好", "哈喽", "hi", "hello", "早上好", "晚上好", "谢谢", "不客气", "再见", "拜拜",
    # 英文关键词
    "hi", "hello", "good morning", "good evening", "thank you", "you're welcome",
    "goodbye", "bye", "how are you", "nice to meet you"
]

# 否定关键词（过滤无效匹配）
NEG_FITNESS_PATTERNS = ["不想", "不要", "不做", "不需要", "不练", "拒绝", "反感", "讨厌"]
NEG_NUTRITION_PATTERNS = ["不想吃", "不忌口", "不需要饮食", "不控制", "不管"]
NEG_REHAB_PATTERNS = ["不康复", "不拉伸", "不需要理疗", "不恢复"]


# -------------------------- 数据结构与工具函数 --------------------------
@dataclass
class RouteResult:
    intent: str  # 意图类型（FITNESS_GYM/NUTRITION/REHAB/HIGH_RISK/HEALTH_QA/SMALL_TALK）
    confidence: float  # 置信度（0-1）
    via: str  # 匹配方式（keyword/rule/empty）
    reason: str  # 匹配原因


def _strip(text: str) -> str:
    """去除文本中的标点、空格、换行符"""
    if not text:
        return ""
    # 移除中英文标点
    punc_pattern = re.compile(r'[^\u4e00-\u9fff\w\s]')
    return punc_pattern.sub('', text).strip()


# -------------------------- 核心路由函数（完整实现）--------------------------
def route(text: str) -> RouteResult:
    msg = _strip(text)
    if not msg:
        return RouteResult(
            intent="SMALL_TALK",
            confidence=0.1,
            via="empty",
            reason="空输入或仅含无效字符"
        )

    # 1. 检测语言（zh/en），统一转为小写处理（适配英文匹配）
    lang = detect_language(msg)
    msg_lower = msg.lower()

    # 2. 通用关键词检测函数（适配中英文，大小写不敏感）
    def _has_any(target_text: str, keywords: List[str]) -> bool:
        """判断目标文本是否包含任意关键词"""
        return any(keyword.lower() in target_text for keyword in keywords)

    def _has_neg_pattern(target_text: str, neg_patterns: List[str]) -> bool:
        """判断目标文本是否包含否定模式"""
        return any(pattern in target_text for pattern in neg_patterns)

    # 3. 优先判断高风险意图（最高优先级）
    if _has_any(msg_lower, HIGH_RISK_KEYWORDS):
        return RouteResult(
            intent="HIGH_RISK",
            confidence=0.95,
            via="keyword",
            reason=f"包含高风险关键词：{', '.join([k for k in HIGH_RISK_KEYWORDS if k.lower() in msg_lower])}"
        )

    # 4. 判断健身意图
    if _has_any(msg_lower, FITNESS_KEYWORDS) and not _has_neg_pattern(msg_lower, NEG_FITNESS_PATTERNS):
        matched_keywords = [k for k in FITNESS_KEYWORDS if k.lower() in msg_lower]
        confidence = min(0.9 + (len(matched_keywords) * 0.01), 0.95)  # 匹配关键词越多，置信度越高
        return RouteResult(
            intent="FITNESS_GYM",
            confidence=confidence,
            via="keyword",
            reason=f"包含健身相关关键词：{', '.join(matched_keywords[:5])}"  # 最多显示5个关键词
        )

    # 5. 判断营养意图
    if _has_any(msg_lower, NUTRITION_KEYWORDS) and not _has_neg_pattern(msg_lower, NEG_NUTRITION_PATTERNS):
        matched_keywords = [k for k in NUTRITION_KEYWORDS if k.lower() in msg_lower]
        confidence = min(0.85 + (len(matched_keywords) * 0.01), 0.9)
        return RouteResult(
            intent="NUTRITION",
            confidence=confidence,
            via="keyword",
            reason=f"包含营养相关关键词：{', '.join(matched_keywords[:5])}"
        )

    # 6. 判断康复意图
    if _has_any(msg_lower, REHAB_KEYWORDS) and not _has_neg_pattern(msg_lower, NEG_REHAB_PATTERNS):
        matched_keywords = [k for k in REHAB_KEYWORDS if k.lower() in msg_lower]
        confidence = min(0.85 + (len(matched_keywords) * 0.01), 0.9)
        return RouteResult(
            intent="REHAB",
            confidence=confidence,
            via="keyword",
            reason=f"包含康复相关关键词：{', '.join(matched_keywords[:5])}"
        )

    # 7. 判断健康问答意图（无明确领域关键词，但有问答类词汇）
    if _has_any(msg_lower, HEALTH_QA_KEYWORDS):
        # 排除已匹配其他领域的情况（避免冲突）
        has_other_domain = (
                _has_any(msg_lower, FITNESS_KEYWORDS) or
                _has_any(msg_lower, NUTRITION_KEYWORDS) or
                _has_any(msg_lower, REHAB_KEYWORDS)
        )
        if not has_other_domain:
            matched_keywords = [k for k in HEALTH_QA_KEYWORDS if k.lower() in msg_lower]
            return RouteResult(
                intent="HEALTH_QA",
                confidence=0.75,
                via="keyword",
                reason=f"包含健康问答相关关键词：{', '.join(matched_keywords[:3])}"
            )

    # 8. 兜底：闲聊意图
    if _has_any(msg_lower, SMALL_TALK_KEYWORDS):
        return RouteResult(
            intent="SMALL_TALK",
            confidence=0.8,
            via="keyword",
            reason=f"包含闲聊关键词：{', '.join([k for k in SMALL_TALK_KEYWORDS if k.lower() in msg_lower][:3])}"
        )

    # 9. 最终兜底（无任何匹配关键词）
    return RouteResult(
        intent="SMALL_TALK",
        confidence=0.2,
        via="default",
        reason="未匹配到任何领域关键词，默认归类为闲聊"
    )


# # -------------------------- 测试代码（可选）--------------------------
# if __name__ == "__main__":
#     # 测试中文输入
#     print(route("如何区分肌肉酸痛和运动损伤"))
#     # 测试英文输入
#     print(route("How to distinguish between DOMS and sports injury"))
#     # 测试混合输入
#     print(route("我想做 bench press 训练，需要注意什么"))