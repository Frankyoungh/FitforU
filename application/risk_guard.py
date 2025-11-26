# -*- coding: utf-8 -*-
# Step 8: Risk Guard 一次闸 & 句级证据对齐（最小可用实现）
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
import math, re

from application.language_utils import detect_language
from application.retrieval_autoload import get_retriever_autoload

# —— 关键词规则（可按需扩充）——
_RED_FLAG_PATTERNS = [
    r"胸痛", r"呼吸困难|气促", r"昏厥|晕厥", r"大出血|出血不止|呕血|黑便|血便",
    r"剧烈头痛|突发神经症状", r"严重过敏|喉头水肿",
r"chest pain", r"difficulty breathing", r"shortness of breath",
    r"fainting", r"severe bleeding", r"sudden headache"
]
_CAUTION_PATTERNS = [
    r"发烧|发熱", r"感冒|喉咙痛|咳嗽|流涕", r"身体不适|乏力|肌肉酸痛|头晕",
    r"胃肠不适|腹泻", r"感染|炎症",
    r"fever", r"cold", r"sore throat", r"cough",
    r"muscle ache", r"fatigue", r"diarrhea"
]

# —— KB 文件名线索（命名建议：data/knowledge 下放这些文档）——
_RED_FLAG_FILE_HINTS = ["red_flag", "contraindication", "急症", "高风险","emergency", "high_risk", "danger" ]
_CAUTION_FILE_HINTS  = ["sick_day", "fever", "illness", "生病训练", "暂停训练", "RPE"]

# —— 句子切分（中英混排）——
_SENT_SPLIT = re.compile(r"(?<=[。！？!?\.])\s+|[\n\r]+")

def _match_any(text: str, patterns: List[str]) -> Optional[str]:
    for pat in patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            return pat
    return None

# def _looks_like(hits: List[Dict], name_hints: List[str]) -> bool:
#     for h in hits:
#         p = (h.get("path") or "").lower()
#         if any(k.lower() in p for k in name_hints):
#             return True
#     return False
def _looks_like(hits: List[Dict], name_hints: List[str]) -> bool:
    """判断命中结果是否匹配线索（支持部分匹配、大小写不敏感）"""
    for h in hits:
        path = (h.get("path") or "").lower()  # 路径转小写
        for hint in name_hints:
            hint_lower = hint.lower()
            # 允许线索是路径的子字符串（如 "rehab" 匹配 "rehab_guide.pdf"）
            if hint_lower in path:
                return True
    return False
@dataclass
class GateResult:
    level: str            # "BLOCK" | "CAUTION" | "OK"
    reason: str
    constraints: Dict[str, Any]
    evidence: List[Dict]  # [{path, score, snippet}]
    message: str

def _score_to_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0

#
# # 在 risk_guard.py 中补充意图-文件线索映射
# _INTENT_FILE_HINTS = {
#     "REHAB": ["康复", "损伤鉴别", "疼痛区分", "恢复训练", "韧带损伤", "肌肉撕裂"],
#     "FITNESS_GYM": ["力量训练", "动作标准", "增肌减脂", "HIIT", "有氧训练"],
#     "NUTRITION": ["饮食搭配", "热量计算", "蛋白质摄入", "减脂餐", "增肌餐"],
#     "HEALTH_QA": ["健康常识", "运动健康", "肌肉酸痛", "DOMS"]
#     # 其他意图补充对应线索
# }
#
# # 修改 kb_search 函数，支持按意图过滤文件
# def kb_search(query: str, k: int = 8, intent: Optional[str] = None) -> List[Dict]:
#     r = get_retriever_autoload()
#     all_hits = r.search(query, k=k * 2) or []  # 多取一倍结果用于过滤
#
#     # 若有意图，优先保留匹配该意图文件线索的结果
#     if intent and intent in _INTENT_FILE_HINTS:
#         hints = _INTENT_FILE_HINTS[intent]
#         # 先保留符合意图的结果，不足再用其他结果补充
#         intent_hits = [h for h in all_hits if _looks_like([h], hints)]
#         other_hits = [h for h in all_hits if h not in intent_hits]
#         all_hits = intent_hits + other_hits  # 意图相关结果排在前面
#
#     return all_hits[:k]  # 截断到指定数量
# def kb_search(query: str, k: int = 8) -> List[Dict]:
#     r = get_retriever_autoload()
#     return r.search(query, k=k) or []
# 在 _CAUTION_FILE_HINTS 下方新增
import streamlit as st
_REHAB_FILE_HINTS = ["rehab", "康复", "损伤鉴别", "肌肉酸痛", "运动损伤", "恢复训练"]
# def kb_search(query: str, k: int = 8, intent: Optional[str] = None) -> List[Dict]:
#     r = get_retriever_autoload()
#     all_hits = r.search(query, k=k*2) or []  # 多取结果用于过滤
#
#     # 根据意图过滤命中结果
#     if intent == "REHAB":
#         st.write('111')
#         # 优先保留康复相关文件的结果
#         rehab_hits = [h for h in all_hits if _looks_like([h], _REHAB_FILE_HINTS)]
#         other_hits = [h for h in all_hits if h not in rehab_hits]
#         all_hits = rehab_hits + other_hits  # 康复相关结果置顶
#     # 可扩展其他意图的过滤逻辑
#
#     return all_hits[:k]
# def kb_search(query: str, k: int = 8, intent: Optional[str] = None) -> List[Dict]:
#     r = get_retriever_autoload()
#     # 1. 增加预检索数量，确保有足够候选结果
#     all_hits = r.search(query, k=k * 3) or []  # 从 k*2 提升到 k*3
#
#     # 2. 扩展意图过滤逻辑，覆盖更多场景（而非仅 REHAB）
#     if intent == "REHAB":
#         # 康复相关文件过滤
#         rehab_hits = [h for h in all_hits if _looks_like([h], _REHAB_FILE_HINTS)]
#         other_hits = [h for h in all_hits if h not in rehab_hits]
#         all_hits = rehab_hits + other_hits
#     elif intent == "FITNESS_GYM":
#         # 新增健身相关文件过滤（需先定义 _FITNESS_FILE_HINTS）
#         fitness_hits = [h for h in all_hits if _looks_like([h], _FITNESS_FILE_HINTS)]
#         other_hits = [h for h in all_hits if h not in fitness_hits]
#         all_hits = fitness_hits + other_hits
#     # 可继续扩展其他意图（如 NUTRITION、HEALTH_QA 等）
#
#     # 3. 移除调试输出，避免干扰
#     return all_hits[:k]
# application/risk_guard.py
def kb_search(query: str, k: int = 8, intent: Optional[str] = None) -> List[Dict]:
    r = get_retriever_autoload()
    # 1. 检测查询语言，用于后续线索过滤
    query_lang = detect_language(query)  # "zh" 或 "en"

    # 2. 扩大预检索数量，确保有足够候选
    all_hits = r.search(query, k=k * 5) or []

    # 3. 结合意图和语言过滤线索
    if intent and intent in _INTENT_FILE_HINTS:
        all_clues = _INTENT_FILE_HINTS[intent]
        # 分离中英文线索（中文：含 Unicode 中文范围；英文：纯字母）
        zh_clues = [c for c in all_clues if re.search(r'[\u4e00-\u9fa5]', c)]
        en_clues = [c for c in all_clues if re.fullmatch(r'[A-Za-z\s]+', c, re.IGNORECASE)]

        # 根据查询语言优先匹配对应线索的结果
        if query_lang == "zh":
            priority_clues = zh_clues
            secondary_clues = en_clues
        else:
            priority_clues = en_clues
            secondary_clues = zh_clues

        # 优先保留匹配优先线索的结果，再补充次要线索结果
        priority_hits = [h for h in all_hits if _looks_like([h], priority_clues)]
        secondary_hits = [h for h in all_hits if h not in priority_hits and _looks_like([h], secondary_clues)]
        other_hits = [h for h in all_hits if h not in priority_hits and h not in secondary_hits]

        # 合并结果：优先线索 > 次要线索 > 其他（确保相关结果前置）
        all_hits = priority_hits + secondary_hits + other_hits

    return all_hits[:k]
# application/risk_guard.py
# application/risk_guard.py
_INTENT_FILE_HINTS = {
    "FITNESS_GYM": [
        # 中文线索
        "健身", "力量训练", "增肌", "减脂", "卧推", "深蹲",
        # 英文线索
        "fitness", "strength training", "muscle building", "fat loss",
        "bench press", "squat", "workout"
    ],
    "REHAB": [
        # 中文线索
        "康复", "损伤", "肌肉酸痛", "运动损伤", "疼痛区分", "恢复训练",
        # 英文线索
        "rehab", "recovery", "muscle soreness", "sports injury",
        "DOMS", "pain distinction", "injury recovery"
    ],
    "NUTRITION": [
        # 中文线索
        "饮食", "营养", "减脂餐", "增肌餐", "卡路里",
        # 英文线索
        "nutrition", "diet", "calorie", "protein", "meal plan", "bulk meal"
    ],
    "HEALTH_QA": [
        # 中文线索
        "健康常识", "运动健康", "睡眠", "作息",
        # 英文线索
        "health tips", "exercise health", "sleep", "daily routine"
    ]
}
_FITNESS_FILE_HINTS = ["力量训练", "动作标准", "增肌减脂", "HIIT", "有氧训练", "gym"]
# 新增消息字典
MESSAGES = {
    "zh": {
        "BLOCK": "⚠️ 检测到高风险关键词，建议立即就医！",
        "CAUTION": "🤒 检测到轻病相关线索，建议降低训练强度！",
        "OK": "✅ 未检测到风险信号"
    },
    "en": {
        "BLOCK": "⚠️ High risk keywords detected, please seek medical attention immediately!",
        "CAUTION": "🤒 Minor illness clues detected, it is recommended to reduce training intensity!",
        "OK": "✅ No risk signals detected"
    }
}
def one_gate(user_text: str, kb_threshold: float = 0.05, fever_rest_days: int = 2, intent: Optional[str] = None) -> GateResult:
    from application.language_utils import detect_language
    lang = detect_language(user_text)
    hits = kb_search(user_text, k=8, intent=intent)  # 测试时返回空列表 []
    has_red_flag = _match_any(user_text, _RED_FLAG_PATTERNS) is not None
    has_caution = _match_any(user_text, _CAUTION_PATTERNS) is not None

    # 1) 高风险判断：关键词匹配优先（不依赖知识库）
    if has_red_flag:
        return GateResult(
            level="BLOCK",
            reason="RED_FLAG_KEYWORD",
            constraints={},
            evidence=hits[:5],
            # message="⚠️ 检测到高风险关键词，建议立即就医！"
            message=MESSAGES[lang]["BLOCK"]
        )
    # 补充：知识库命中的高风险（仅当 hits 非空时）
    if hits and _looks_like(hits, _RED_FLAG_FILE_HINTS):
        top_score = _score_to_float(hits[0].get("score"))
        if top_score >= kb_threshold:
            return GateResult(
                level="BLOCK",
                reason="RED_FLAG_KB",
                constraints={},
                evidence=hits[:5],
                message="⚠️ 检测到高风险知识库匹配，建议立即就医！"
            )

    # 2) 轻病判断（同样处理 hits 为空的情况）
    if has_caution:
        return GateResult(
            level="CAUTION",
            reason="CAUTION_KEYWORD",
            constraints={"avoid_tags": ["hiit", "heavy"], "rpe_max": 4},
            evidence=hits[:5],
            # message="🤒 检测到轻病相关线索，建议降低训练强度！"
            message=MESSAGES[lang]["CAUTION"]
        )
    if hits and _looks_like(hits, _CAUTION_FILE_HINTS):
        top_score = _score_to_float(hits[0].get("score"))
        if top_score >= kb_threshold * 0.6:
            return GateResult(
                level="CAUTION",
                reason="CAUTION_KB",
                constraints={"avoid_tags": ["hiit", "heavy"], "rpe_max": 4},
                evidence=hits[:5],
                message="🤒 检测到轻病知识库匹配，建议降低训练强度！"
            )

    # 3) 正常通过
    return GateResult(
        level="OK",
        reason="NO_RISK",
        constraints={},
        evidence=hits[:5],
        # message="✅ 未检测到风险信号"
        message=MESSAGES[lang]["OK"]
    )
# def one_gate(user_text: str,
#              kb_threshold: float = 0.05,
#              fever_rest_days: int = 2) -> GateResult:
#     """
#     一次闸：结合关键词 + KB 命中，给出拦截/谨慎/通过，并提供“可注入 Composer 的约束”。
#     """
#     hits = kb_search(user_text, k=8)
#
#     # 1) 先看 KB 是否强命中 “红旗”
#     # if hits and ( _looks_like(hits, _RED_FLAG_FILE_HINTS) or _match_any(user_text, _RED_FLAG_PATTERNS) ):
#     if (hits and _looks_like(hits, _RED_FLAG_FILE_HINTS)) or _match_any(user_text, _RED_FLAG_PATTERNS):
#         top = _score_to_float(hits[0].get("score"))
#         if top >= kb_threshold or _match_any(user_text, _RED_FLAG_PATTERNS):
#             return GateResult(
#                 level="BLOCK",
#                 reason="RED_FLAG",
#                 constraints={},
#                 evidence=hits[:3],
#                 message=("⚠️ 检测到疑似高风险信号（非医疗建议）。请尽快就医评估；"
#                          "若出现胸痛、呼吸困难、昏厥或持续性大出血等紧急症状，请立即拨打当地急救电话。")
#             )
#
#     # 2) 其次看 “轻病/谨慎” 场景（发烧/感冒等）
#     if hits and ( _looks_like(hits, _CAUTION_FILE_HINTS) or _match_any(user_text, _CAUTION_PATTERNS) ):
#         top = _score_to_float(hits[0].get("score"))
#         if top >= (kb_threshold * 0.6) or _match_any(user_text, _CAUTION_PATTERNS):
#             # 注入到 Composer/排程的最小约束集合
#             constraints = {
#                 "avoid_tags": ["hiit", "heavy", "failure"],
#                 "rpe_max": 4,                  # 主观强度上限
#                 "max_daily_minutes": 20,       # 单日上限
#                 "postpone_days": fever_rest_days,  # 延后起始天数
#                 "notes": " illness_caution ",  # 供 UI 显示
#             }
#             return GateResult(
#                 level="CAUTION",
#                 reason="MINOR_ILLNESS",
#                 constraints=constraints,
#                 evidence=hits[:3],
#                 message=("🤒 检测到轻病相关线索。建议以休息/极轻强度为主，避免 HIIT/大重量/接近力竭；"
#                          f"起始可顺延 {fever_rest_days} 天或症状完全恢复后再恢复常规训练（非医疗建议）。")
#             )
#
#     # 3) 正常通过
#     return GateResult(
#         level="OK",
#         reason="CLEAR",
#         constraints={},
#         evidence=hits[:3] if hits else [],
#         message="✓ 未检测到需要特别拦截的风险。"
#     )

# —— 把约束后置应用到 actions（如果 Composer 不认识 constraints，就用这个兜底）——
def apply_constraints_to_actions(actions: List[Dict[str, Any]],
                                 constraints: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not actions or not constraints:
        return actions or []

    avoid = set([t.lower() for t in constraints.get("avoid_tags", [])])
    rpe_max = int(constraints.get("rpe_max", 0) or 0)
    cap_min = int(constraints.get("max_daily_minutes", 0) or 0)
    postpone = int(constraints.get("postpone_days", 0) or 0)

    out = []
    for a in actions:
        b = dict(a)

        # 延后开始
        if postpone > 0 and "date" in b:
            # 仅调整日期字符串（yyyy-mm-dd），真实 dtstart/dtend 在导出前会重算
            from datetime import datetime, timedelta
            try:
                dt = datetime.strptime(b["date"], "%Y-%m-%d")
                dt = dt + timedelta(days=postpone)
                b["date"] = dt.strftime("%Y-%m-%d")
            except Exception:
                pass

        # 降强度（写在描述里，便于 UI 呈现）
        if rpe_max > 0:
            desc = (b.get("desc") or b.get("description") or "").strip()
            b["desc"] = (desc + f" [强度≤RPE{rpe_max}]").strip()

        # 避免标签：如果命中“重训/HIIT”等，则把标签切到“recovery/轻活动”
        tags = [t.lower() for t in (b.get("tags") or [])]
        if avoid and any(t in avoid for t in tags):
            b["tags"] = ["recovery", "light"]

        # 限制单次时长
        if cap_min > 0:
            try:
                dur = int(b.get("duration_min", 0) or 0)
                if dur > cap_min:
                    b["duration_min"] = cap_min
            except Exception:
                pass

        out.append(b)
    return out

# # —— 句级证据对齐：把文本按句切开，与 KB 分块做简易 TF-IDF 相似度，返回对齐列表 ——
# def verify_text_against_kb(text: str, k_per_sent: int = 2,
#                            kb_threshold: float = 0.08) -> List[Dict[str, Any]]:
#     if not text or not text.strip():
#         return []
#     retriever = get_retriever_autoload()
#     sents = [s.strip() for s in _SENT_SPLIT.split(text) if s and s.strip()]
#     out: List[Dict[str, Any]] = []
#     for s in sents:
#         hits = retriever.search(s, k=k_per_sent) or []
#         hits = [h for h in hits if _score_to_float(h.get("score")) >= kb_threshold]
#         if hits:
#             out.append({"sentence": s, "evidence": hits})
#     return out
def verify_text_against_kb(text: str, k_per_sent: int = 3,  # 增加返回数量，避免漏检
                           kb_threshold: float = 0.06,intent: Optional[str] = None) -> List[Dict[str, Any]]:  # 降低阈值，提高命中率
    if not text or not text.strip():
        return []

    # 新增：针对“肌肉酸痛vs运动损伤”补充核心术语（关键！）
    related_keywords = {
        "肌肉酸痛": ["延迟性肌肉酸痛", "DOMS", "运动后酸痛", "酸胀", "钝痛"],
        "运动损伤": ["锐痛", "刺痛", "即时疼痛", "单点疼痛", "活动受限"],
        "区分": ["如何判断", "区别", "分辨", "差异"]
    }
    # 给用户输入补充同义词/核心术语，提升检索匹配度
    enhanced_text = text
    for user_word, synonyms in related_keywords.items():
        if user_word in text:
            enhanced_text += " " + " ".join(synonyms)

    retriever = get_retriever_autoload()
    # 用增强后的文本检索（原文本保留，避免丢失用户原意）
    sents = [s.strip() for s in _SENT_SPLIT.split(enhanced_text) if s and s.strip()]
    out: List[Dict[str, Any]] = []
    for s in sents:
        hits = retriever.search(s, k=k_per_sent) or []
        # 按意图过滤（仅保留康复相关文件）
        if intent == "REHAB":
            print('1')
            hits = [h for h in hits if _looks_like([h], _REHAB_FILE_HINTS)]
        # 应用阈值过滤
        hits = [h for h in hits if _score_to_float(h.get("score")) >= kb_threshold]
        if hits:
            out.append({"sentence": s, "evidence": hits})
    return out
    # for s in sents:
    #     hits = retriever.search(s, k=k_per_sent) or []
    #     # 过滤低相似度结果，同时保留高相关度的知识库片段
    #     hits = [h for h in hits if _score_to_float(h.get("score")) >= kb_threshold]
    #     # 新增：优先保留doms_vs_injury.md的结果（确保目标知识库被优先选中）
    #     hits.sort(key=lambda x: 1 if "doms_vs_injury.md" in x.get("source", "") else 0, reverse=True)
    #     if hits:
    #         out.append({"sentence": s, "evidence": hits})
    # return out
