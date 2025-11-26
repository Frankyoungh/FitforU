
import sys
from pathlib import Path
from datetime import datetime, time as _time, timedelta, date as _date
import uuid
import os
import importlib
import json
from typing import List, Dict, Any, Optional
from copy import deepcopy
import requests
import streamlit as st
import re
import html



# ---------------------------------------------------------
# Path & sys.path
# ---------------------------------------------------------
_THIS_FILE = Path(__file__).resolve()
_APP_DIR = _THIS_FILE.parent  # .../application
_PROJ_ROOT = _APP_DIR.parent  # project root

for p in (_PROJ_ROOT, _APP_DIR):
    ps = str(p)
    if ps not in sys.path:
        sys.path.insert(0, ps)

# ---------------------------------------------------------
# Imports from application
# ---------------------------------------------------------
from application.language_utils import detect_language
from application.verify import verify_actions, verify_draft
from application.retrieval_autoload import (
    get_retriever_autoload,
    knowledge_status,
    rescan_and_rebuild,
)
from application.risk_guard import (
    one_gate,
    apply_constraints_to_actions,
    verify_text_against_kb,
)

# ---------------------------------------------------------
# 可选加载 Profile / Composer
# ---------------------------------------------------------
HAS_COMPOSER = False
COMPOSER_IMPL_LABEL = "fallback (disabled)"
Profile = None
compose_plan = None
try:
    from application.profile import Profile as _Prof
    from application.composer import compose_plan as _compose

    Profile = _Prof
    compose_plan = _compose
    HAS_COMPOSER = True
    COMPOSER_IMPL_LABEL = "application.composer:compose_plan"
except Exception:
    HAS_COMPOSER = False

# ---------------------------------------------------------
# Intent Router
# ---------------------------------------------------------
ROUTER_IMPL_LABEL = "fallback (builtin)"


# def _load_router():
#     def _pick_callable(mod, names=("route_intent", "route")):
#         for n in names:
#             fn = getattr(mod, n, None)
#             if callable(fn):
#                 return fn, n
#         return None, None
#
#     global ROUTER_IMPL_LABEL
#     # 优先 application.intent_router
#     try:
#         mod = importlib.import_module("application.intent_router")
#         fn, name = _pick_callable(mod)
#         if fn:
#             ROUTER_IMPL_LABEL = f"application.intent_router:{name}"
#             return fn
#     except Exception:
#         pass
#
#     # 次选根目录 intent_router
#     try:
#         mod = importlib.import_module("intent_router")
#         fn, name = _pick_callable(mod)
#         if fn:
#             ROUTER_IMPL_LABEL = f"intent_router:{name}"
#             return fn
#     except Exception:
#         pass
def _load_router():
    def _pick_callable(mod, names=("route_intent", "route")):
        for n in names:
            fn = getattr(mod, n, None)
            if callable(fn):
                # 验证路由函数是否能正常返回 HEALTH_PLAN（新增校验）
                try:
                    test_input = "随便说点什么"  # 非高风险输入
                    test_res = fn(test_input)
                    normalized = normalize_route_result(test_res)
                    if normalized.get("intent") != "HEALTH_PLAN":
                        # 路由函数无法正确返回 HEALTH_PLAN，视为无效
                        return None, None
                except Exception:
                    return None, None
                return fn, n
        return None, None

    global ROUTER_IMPL_LABEL
    # 优先加载 application.intent_router，但增加有效性校验
    try:
        mod = importlib.import_module("application.intent_router")
        fn, name = _pick_callable(mod)
        if fn:
            ROUTER_IMPL_LABEL = f"application.intent_router:{name}"
            return fn
    except Exception:
        pass

    # 次选根目录 intent_router，同样增加校验
    try:
        mod = importlib.import_module("intent_router")
        fn, name = _pick_callable(mod)
        if fn:
            ROUTER_IMPL_LABEL = f"intent_router:{name}"
            return fn
    except Exception:
        pass

    # 强制使用兜底路由（确保非高风险场景返回 HEALTH_PLAN）
    return _fallback_route_intent
    # Fallback：简单关键词
    # def _fallback_route_intent(text: str) -> Dict[str, Any]:
    #     # 检测文本语言
    #     lang = get_text_language(text)
    #     # 获取对应语言的高风险关键词
    #     high_risk_keywords = LANG_CONFIG[lang]['high_risk_keywords']
    #
    #     hi = any(k in text.lower() for k in high_risk_keywords)
    #     return {
    #         "intent": "HIGH_RISK" if hi else "HEALTH_PLAN",
    #         "confidence": 0.75 if hi else 0.55,
    #         "reason": "fallback router"
    #     }
    # def _fallback_route_intent(text: str) -> Dict[str, Any]:
    #     # 检测语言，区分中英文高风险关键词
    #     lang = detect_language(text.lower())
    #     if lang == "en":
    #         high_risk_keywords = [
    #             "chest pain", "difficulty breathing", "shortness of breath",
    #             "fainting", "severe bleeding", "loss of consciousness",
    #             "severe headache", "vomiting", "high fever", "fracture", "dislocation"
    #         ]
    #     else:
    #         high_risk_keywords = [
    #             "毫升", "mg", "剂量", "胸痛", "出血", "昏厥",
    #             "呼吸困难", "儿童用药", "孕妇用药"
    #         ]
    #
    #     hi = any(k in text.lower() for k in high_risk_keywords)
    #     return {
    #         "intent": "HIGH_RISK" if hi else "HEALTH_PLAN",
    #         "confidence": 0.75 if hi else 0.55,
    #         "reason": "fallback router"
    #     }
    # return _fallback_route_intent
def _fallback_route_intent(text: str) -> Dict[str, Any]:
        text_clean = text.strip()
        if not text_clean:
            return {"intent": "HEALTH_PLAN", "confidence": 0.55, "reason": "empty text"}

        # 1. 调用基础检测函数
        lang = detect_language(text_clean)

        # 2. 兜底校验：若检测为英文，但文本包含中文字符，则强制修正为中文
        has_chinese = any("\u4e00" <= c <= "\u9fff" for c in text_clean)
        if lang == "en" and has_chinese:
            lang = "zh"
        # 反之，若检测为中文但无中文字符，修正为英文（可选）
        elif lang == "zh" and not has_chinese:
            lang = "en"

        # 3. 根据修正后的语言选择关键词
        if lang == "en":
            high_risk_keywords = [
                "chest pain", "difficulty breathing", "shortness of breath",
                "fainting", "severe bleeding", "loss of consciousness"
            ]
        else:
            high_risk_keywords = [
                "毫升", "mg", "剂量", "胸痛", "出血", "昏厥",
                "呼吸困难", "儿童用药", "孕妇用药"
            ]

        hi = any(k in text_clean.lower() for k in high_risk_keywords)
        return {
            "intent": "HIGH_RISK" if hi else "HEALTH_PLAN",
            "confidence": 0.75 if hi else 0.55,
            "reason": "fallback router with chinese check"
        }

route_intent = _load_router()


def _to_str_intent(x):
    if x is None:
        return "HEALTH_PLAN"
    name = getattr(x, "name", None)
    if isinstance(name, str):
        return name
    return str(x)


def normalize_route_result(res):
    if isinstance(res, dict):
        intent = _to_str_intent(res.get("intent"))
        conf = res.get("confidence", 0.0)
        rsn = res.get("reason", "")
        try:
            conf = float(conf)
        except Exception:
            conf = 0.0
        return {"intent": intent, "confidence": conf, "reason": rsn}

    # pydantic / dataclass / etc
    try:
        from pydantic import BaseModel as _BM
        if isinstance(res, _BM):
            data = res.model_dump() if hasattr(res, "model_dump") else res.dict()
            return normalize_route_result(data)
    except Exception:
        pass

    try:
        from dataclasses import is_dataclass, asdict as _asdict
        if is_dataclass(res):
            return normalize_route_result(_asdict(res))
    except Exception:
        pass

    for cand_int in ("intent", "label"):
        if hasattr(res, cand_int):
            intent = _to_str_intent(getattr(res, cand_int))
            conf = 0.0
            for c in ("confidence", "score", "prob"):
                if hasattr(res, c):
                    try:
                        conf = float(getattr(res, c))
                    except Exception:
                        conf = 0.0
                    break
            rsn = getattr(res, "reason", "") if hasattr(res, "reason") else ""
            return {"intent": intent, "confidence": conf, "reason": rsn}

    if isinstance(res, (list, tuple)) and len(res) >= 1:
        intent = _to_str_intent(res[0])
        conf = 0.0
        if len(res) >= 2:
            try:
                conf = float(res[1])
            except Exception:
                conf = 0.0
        rsn = res[2] if len(res) >= 3 else ""
        return {"intent": intent, "confidence": conf, "reason": rsn}

    try:
        from enum import Enum
        if isinstance(res, Enum):
            return {"intent": _to_str_intent(res), "confidence": 0.0, "reason": ""}
    except Exception:
        pass

    return {
        "intent": "HEALTH_PLAN",
        "confidence": 0.0,
        "reason": "unrecognized router return"
    }


# ---------------------------------------------------------
# Risk Guard 一次闸（Step 8 一闸）
# ---------------------------------------------------------
def _run_one_gate(text: str) -> Optional[Dict[str, Any]]:
    """
    统一封装 risk_guard.one_gate：
    返回格式：
    {
        "high": bool,           # 是否 BLOCK 红线
        "caution": bool,        # 是否轻病/谨慎场景
        "level": "BLOCK|CAUTION|OK",
        "constraints": {...},   # 可直接喂给 apply_constraints_to_actions
        "reason": str,
        "message": str,
    }
    """
    if not text or not text.strip():
        return None

    try:
        res = one_gate(text)
    except Exception:
        return None

    if res is None:
        return None

    # --- 1) GateResult / 类似 dataclass: 有 level/constraints ---
    if hasattr(res, "level"):
        level = str(getattr(res, "level", "") or "").upper()
        constraints = getattr(res, "constraints", {}) or {}
        reason = getattr(res, "reason", "") or ""
        msg = getattr(res, "message", "") or ""

        high = level in ("BLOCK", "HIGH_RISK", "RED_FLAG")
        caution = (level == "CAUTION")

        return {
            "high": high,
            "caution": caution,
            "level": level or ("BLOCK" if high else "OK"),
            "constraints": constraints,
            "reason": reason,
            "message": msg,
        }

    # --- 2) dict 返回 ---
    if isinstance(res, dict):
        level = str(res.get("level", "") or "").upper()
        constraints = res.get("constraints") or {}
        reason = res.get("reason", "") or ""
        msg = res.get("message", "") or ""

        # 尝试从字段推断 level
        if not level:
            if res.get("high") or res.get("high_risk") or res.get("is_high_risk"):
                level = "BLOCK"
            elif res.get("caution") or constraints:
                level = "CAUTION"
            else:
                level = "OK"

        high = (level == "BLOCK")
        caution = (level == "CAUTION")

        return {
            "high": high,
            "caution": caution,
            "level": level,
            "constraints": constraints,
            "reason": reason,
            "message": msg,
        }

    # --- 3) bool：True=高风险，False=安全 ---
    if isinstance(res, bool):
        return {
            "high": bool(res),
            "caution": False,
            "level": "BLOCK" if res else "OK",
            "constraints": {},
            "reason": "",
            "message": "",
        }

    # --- 4) 其他对象：尝试按属性名解析一次 ---
    level = str(getattr(res, "level", "") or "").upper()
    constraints = getattr(res, "constraints", {}) or {}
    reason = getattr(res, "reason", "") or ""
    msg = getattr(res, "message", "") or ""

    if level or constraints or reason or msg:
        high = (level == "BLOCK")
        caution = (level == "CAUTION")
        return {
            "high": high,
            "caution": caution,
            "level": level or ("BLOCK" if high else "OK"),
            "constraints": constraints,
            "reason": reason,
            "message": msg,
        }
    # text_lang = get_text_language(text)

    # # 处理消息本地化（如果原始消息为空，补充默认多语言消息）
    # if not msg:
    #     if high:
    #         msg = "检测到高风险内容，请避免提供相关建议。" if text_lang == 'zh-cn' else "High risk content detected, please avoid providing relevant suggestions."
    #     elif caution:
    #         msg = "请注意，内容涉及需要谨慎处理的场景。" if text_lang == 'zh-cn' else "Please note that the content involves scenarios requiring careful handling."
    #
    # return {
    #     "high": high,
    #     "caution": caution,
    #     "level": level or ("BLOCK" if high else "OK"),
    #     "constraints": constraints,
    #     "reason": reason,
    #     "message": msg,
    # }
    return None


def _run_verify_text_against_kb(answer: str, hits: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    对 verify_text_against_kb 做一层兼容封装，统一成:
      { "ok": bool, "reason": str, "raw": ... }

    兼容多种可能实现：
    - 返回 bool: True=安全, False=不安全/存疑
    - 返回 dict: 使用 ok/safe/passed 或 high_risk/violated 等字段
    - 返回 list/tuple: 视为句子级或证据级结果，聚合判断
    - 返回对象: 尝试读取 ok/passed/safe/high_risk/violated/reason
    - 函数签名兼容：
        verify_text_against_kb(answer, hits)
        verify_text_against_kb(answer=..., evidence=...)
        verify_text_against_kb(answer)
    任意异常视为 None（不上闸，以免实现问题影响主流程）。
    """
    if not answer:
        return None

    # --- 调用底层函数（兼容多种签名） ---
    try:
        try:
            res = verify_text_against_kb(answer, hits)
        except TypeError:
            try:
                res = verify_text_against_kb(answer=answer, evidence=hits)
            except TypeError:
                res = verify_text_against_kb(answer)
    except Exception:
        return None

    if res is None:
        return None

    # --- 情况 1：list / tuple（句子级或证据级结果）---
    if isinstance(res, (list, tuple)):
        if not res:
            # 空列表：没发现问题也没发现强证据，偏保守但放行
            return {"ok": True, "reason": "", "raw": res}

        any_conflict = False
        any_support_flag = False
        scores = []

        for item in res:
            if not isinstance(item, dict):
                continue

            # 显式冲突 / 风险信号优先级最高
            if any(bool(item.get(k)) for k in ("high_risk", "violated", "conflict", "mismatch", "unsafe")):
                any_conflict = True

            # 显式支持信号
            if any(bool(item.get(k)) for k in ("ok", "safe", "passed", "aligned", "support")):
                any_support_flag = True

            # 分数字段（如有）用于粗略评估证据强度
            s = item.get("score")
            if s is not None:
                try:
                    scores.append(float(s))
                except Exception:
                    pass

        # if any_conflict:
        #     return {
        #         "ok": False,
        #         "reason": "Knowledge base verification alert: There are contents in the answer that are inconsistent with the evidence or potentially pose high risks.",
        #         "raw": res,
        #     }
        answer_lang = get_text_language(answer)

        if any_conflict:
            return {
                "ok": False,
                "reason": LANG_CONFIG[answer_lang]['kb_verify_conflict'],
                "raw": res,
            }

        # 如果只有很弱的匹配（所有分数都极低），给出“支撑不足”的保守提示
        # if scores:
        #     max_s = max(scores)
        #     if max_s < 0.25:
        #         return {
        #             "ok": False,
        #             "reason": "There is insufficient reliable evidence from the knowledge base to support this answer. It is recommended not to make critical decisions based on this.",
        #             "raw": res,
        #         }
        if scores:
            max_s = max(scores)
            if max_s < 0.25:
                return {
                    "ok": False,
                    "reason": LANG_CONFIG[answer_lang]['kb_verify_insufficient'],
                    "raw": res,
                }
        # 无冲突信号 → 视为通过（不强制要求显式 support 字段）
        return {"ok": True, "reason": "", "raw": res}

    # --- 情况 2：bool ---
    if isinstance(res, bool):
        return {"ok": bool(res), "reason": "", "raw": res}

    # --- 情况 3：dict ---
    if isinstance(res, dict):
        ok = res.get("ok")

        if ok is None:
            # 常见别名 & 反向信号
            if "safe" in res:
                ok = bool(res.get("safe"))
            elif "passed" in res:
                ok = bool(res.get("passed"))
            elif res.get("high_risk") or res.get("violated"):
                ok = False

        if ok is None:
            ok = True  # 不确定时默认放行

        return {
            "ok": bool(ok),
            "reason": str(res.get("reason") or res.get("message") or ""),
            "raw": res,
        }

    # --- 情况 4：对象风格 ---
    ok = None
    reason = ""

    for name in ("ok", "passed", "safe"):
        if hasattr(res, name):
            try:
                ok = bool(getattr(res, name))
                break
            except Exception:
                pass

    for bad in ("high_risk", "violated"):
        if hasattr(res, bad) and getattr(res, bad):
            ok = False

    if hasattr(res, "reason"):
        try:
            reason = str(getattr(res, "reason"))
        except Exception:
            reason = ""

    if ok is None:
        ok = True  # 不确定不拦截

    return {
        "ok": bool(ok),
        "reason": reason,
        "raw": str(res),
    }


# ---------------------------------------------------------
# ACT (Step 4)
# ---------------------------------------------------------
ACT_IMPL_LABEL = "fallback (inline)"


def _load_act():
    """
    统一从 application.act 加载 build_actions / to_ics / to_checklist_md，
    并对 to_ics 做一层包装，确保：
    - VCALENDAR 中至少包含 X-WR-TIMEZONE（默认 Asia/Shanghai，可用 ICS_TZ 覆盖）
    - DTSTART/DTEND 若为本地时间且无 TZID，则自动补上 TZID
    - 不破坏已有实现（已有声明则不重复改）
    """
    ICS_DEFAULT_TZ = os.environ.get("ICS_TZ", "Asia/Shanghai")

    try:
        from application.act import (
            build_actions as _build_actions,
            to_ics as _raw_to_ics,
            to_checklist_md as _to_checklist_md,
        )

        def _safe_to_ics(actions, name: str = "FitForU Plan", tz: str = None) -> str:
            ics = _raw_to_ics(actions, name=name)
            if not isinstance(ics, str):
                return ""

            tzid = tz or ICS_DEFAULT_TZ

            # --- 1) 确保 VCALENDAR 层有 X-WR-TIMEZONE ---
            if "BEGIN:VCALENDAR" in ics and "X-WR-TIMEZONE" not in ics:
                if "VERSION:2.0" in ics:
                    ics = ics.replace(
                        "VERSION:2.0",
                        f"VERSION:2.0\r\nX-WR-TIMEZONE:{tzid}",
                        1,
                    )
                else:
                    ics = ics.replace(
                        "BEGIN:VCALENDAR",
                        f"BEGIN:VCALENDAR\r\nX-WR-TIMEZONE:{tzid}",
                        1,
                    )

            # --- 2) 为本地时间的 DTSTART/DTEND 自动补 TZID ---
            fixed_lines = []
            for line in ics.splitlines():
                # 跳过已经带 TZID 的、全日制 (VALUE=DATE) 的、以及 UTC 行(以 Z 结尾)
                if (
                        line.startswith("DTSTART:")
                        and "TZID=" not in line
                        and ";VALUE=DATE" not in line
                        and not line.endswith("Z")
                ):
                    line = line.replace("DTSTART:", f"DTSTART;TZID={tzid}:", 1)

                elif (
                        line.startswith("DTEND:")
                        and "TZID=" not in line
                        and ";VALUE=DATE" not in line
                        and not line.endswith("Z")
                ):
                    line = line.replace("DTEND:", f"DTEND;TZID={tzid}:", 1)

                fixed_lines.append(line)

            # 使用 \r\n 组装，兼容大部分日历解析器
            ics = "\r\n".join(fixed_lines)

            return ics

        globals()["ACT_IMPL_LABEL"] = "application.act"
        return _build_actions, _safe_to_ics, _to_checklist_md

    except Exception:
        # fallback：至少包含基本合法头，保证能被导入
        def _fallback_build_actions(draft, start_date):
            return []

        def _fallback_to_ics(actions, name: str = "FitForU Plan", tz: str = None) -> str:
            tzid = tz or ICS_DEFAULT_TZ
            return (
                "BEGIN:VCALENDAR\r\n"
                "VERSION:2.0\r\n"
                f"X-WR-TIMEZONE:{tzid}\r\n"
                "END:VCALENDAR"
            )

        def _fallback_to_checklist_md(actions):
            return ""

        globals()["ACT_IMPL_LABEL"] = "fallback"
        return _fallback_build_actions, _fallback_to_ics, _fallback_to_checklist_md


# 注意：此处得到的是“已经带时区保护”的 to_ics
build_actions, to_ics, to_checklist_md = _load_act()


def _extract_json_object(raw: str) -> Optional[Dict[str, Any]]:
    """从 LLM 输出中尽力抽出单个 JSON 对象，不做危险的内容改写。"""
    if not raw:
        return None

    s = str(raw).strip()

    # 去掉 ```json ... ``` 包裹
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_]*\s*", "", s)
        s = re.sub(r"```$", "", s).strip()

    # 只取第一个 { 到 最后一个 } 的内容
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    candidate = s[start:end + 1]

    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError as e:
        print(f"[extract_json_object] JSON decode error: {e}: {candidate[:200]}")
        return None

    if isinstance(obj, dict):
        return obj
    return None


# 新增语言检测相关依赖及配置
try:
    from langdetect import detect, LangDetectException
except ImportError:
    # 提供降级方案
    def detect(text: str) -> str:
        if any('\u4e00' <= c <= '\u9fff' for c in text):
            return 'zh-cn'
        return 'en'


    class LangDetectException(Exception):
        pass

# 多语言配置字典（统一管理提示词）
LANG_CONFIG = {
    'zh-cn': {
        'system_prompt_refine': (
            "你是一名LLM规划助手，负责协同设计3-30天的训练/生活计划。\n"
            "你会收到一个已验证的结构化周计划JSON。\n"
            "你的唯一任务：优化面向人类的文本字段。\n"
            "\n"
            "目标：\n"
            "- 使每个模块的标题具体且具有激励性。\n"
            "- 利用模块的天数、标签和时长来区分不同日期。\n"
            "- 避免重复：如果两天内容相似，用不同方式表述或突出不同重点。\n"
            "- 保持描述简洁（1-3句话）：包含做什么以及为什么有帮助。\n"
            "\n"
            "严格规则：\n"
            "- 不要修改任何数值（天数、日期、时长、组数等）。\n"
            "- 不要增加或删除模块。\n"
            "- 不要引入药物或补充剂剂量。\n"
            "- 不要在标题/描述中提到自己是AI。\n"
            "- 只修改：`title` 和 `description`（对应`desc`）。\n"
            "\n"
            "输出格式严格为JSON：\n"
            "{\n"
            '  "modules": [\n'
            '    {"index": int, "title": "...", "description": "..."}]\n'
            "}\n"
        ),
        'kb_verify_conflict': "知识库验证警告：回答中存在与证据不一致或潜在高风险的内容。",
        'kb_verify_insufficient': "知识库中没有足够的可靠证据支持此回答，建议不要基于此做出重要决策。",
        'high_risk_keywords': ["毫升", "mg", "剂量", "胸痛", "出血", "昏厥", "呼吸困难", "儿童用药", "孕妇用药"]
    },
    'en': {
        'system_prompt_refine': (
            "You are an LLM planning agent co-designing a 3-30 day training / lifestyle plan.\n"
            "You receive a validated structured weekly plan JSON.\n"
            "Your ONLY job: upgrade the human-facing text fields.\n"
            "\n"
            "Goals:\n"
            "- Make each module's title concrete and motivating.\n"
            "- Use the module's day, tags, and minutes to differentiate days.\n"
            "- Avoid repetition: if two days look similar, phrase them differently or highlight different focus.\n"
            "- Keep descriptions short (1-3 sentences): what to do + why it helps.\n"
            "\n"
            "HARD RULES:\n"
            "- DO NOT change any numeric values (day, date, duration, sets, etc.).\n"
            "- DO NOT add or remove modules.\n"
            "- DO NOT introduce medications or supplement dosages.\n"
            "- DO NOT mention being an AI in the titles/descriptions.\n"
            "- Only touch: `title` and `description` (mapped to `desc`).\n"
            "\n"
            "Output STRICTLY as JSON:\n"
            "{\n"
            '  "modules": [\n'
            "    {\"index\": int, \"title\": \"...\", \"description\": \"...\"}\n"
            "  ]\n"
            "}\n"
        ),
        'kb_verify_conflict': "Knowledge base verification alert: There are contents in the answer that are inconsistent with the evidence or potentially pose high risks.",
        'kb_verify_insufficient': "There is insufficient reliable evidence from the knowledge base to support this answer. It is recommended not to make critical decisions based on this.",
        'high_risk_keywords': ["ml", "mg", "dosage", "chest pain", "bleeding", "fainting", "dyspnea", "pediatric use",
                               "pregnancy use"]
    }
}


def get_text_language(text: str) -> str:
    """统一语言检测：优先字符特征，兜底langdetect，确保结果仅为zh或en"""
    if not text or not text.strip():
        return 'zh'  # 空文本默认中文

    text_clean = text.strip()
    # 强特征判断：包含中文字符 → 中文
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', text_clean))
    # 强特征判断：仅含英文（字母/空格/标点）→ 英文
    has_only_english = bool(re.fullmatch(r'[a-zA-Z0-9\s\.,\?!;:()\-"\']+', text_clean))

    if has_chinese:
        return 'zh'
    elif has_only_english:
        return 'en'
    # 兜底：使用langdetect，结果归一化
    try:
        lang = detect(text_clean)
        return 'zh' if lang.startswith('zh') else 'en'
    except LangDetectException:
        return 'zh'  # 异常情况默认中文

def refine_plan_texts_with_llm(
        draft: Dict[str, Any],
        user_text: str,
        model_name: str,
        gen_params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    对计划草案的文案层进行轻量 LLM 润色：
    - 仅允许修改模块的 title / desc
    - 严禁改动 day/date/start/end/duration/tags 等结构字段
    - 任意异常 / 高风险输出，直接回退原始 draft
    """
    modified = False
    if not isinstance(draft, dict):
        return draft

    modules = draft.get("modules") or []
    if not isinstance(modules, list) or not modules:
        return draft

    # 构造精简版模块信息给 LLM 参考（防止看到太多内部字段）
    simple_modules: List[Dict[str, Any]] = []
    for idx, m in enumerate(modules):
        m = dict(m or {})
        title = str(m.get("title") or m.get("name") or f"Module {idx + 1}")
        desc = str(m.get("desc") or m.get("description") or "")
        tags = [str(t) for t in (m.get("tags") or [])]
        try:
            minutes = int(m.get("duration_min") or m.get("minutes") or 0)
        except Exception:
            minutes = 0
        day = m.get("day") or (idx + 1)

        simple_modules.append({
            "index": idx,
            "day": int(day) if str(day).isdigit() else day,
            "title": title,
            "description": desc,
            "tags": tags,
            "minutes": minutes,
        })

    system_prompt = (
        "You are an LLM planning agent co-designing a 3-30 day training / lifestyle plan.\n"
        "You receive a validated structured weekly plan JSON.\n"
        "Your ONLY job: upgrade the human-facing text fields.\n"
        "\n"
        "Goals:\n"
        "- Make each module's title concrete and motivating.\n"
        "- Use the module's day, tags, and minutes to differentiate days.\n"
        "- Avoid repetition: if two days look similar, phrase them differently or highlight different focus.\n"
        "- Keep descriptions short (1-3 sentences): what to do + why it helps.\n"
        "\n"
        "HARD RULES:\n"
        "- DO NOT change any numeric values (day, date, duration, sets, etc.).\n"
        "- DO NOT add or remove modules.\n"
        "- DO NOT introduce medications or supplement dosages.\n"
        "- DO NOT mention being an AI in the titles/descriptions.\n"
        "- Only touch: `title` and `description` (mapped to `desc`).\n"
        "\n"
        "Output STRICTLY as JSON:\n"
        "{\n"
        '  \"modules\": [\n'
        "    {\"index\": int, \"title\": \"...\", \"description\": \"...\"}\n"
        "  ]\n"
        "}\n"
    )

    profile = st.session_state.get("profile") if HAS_COMPOSER else None
    user_payload = {
        "user_request": user_text,
        "modules": simple_modules,
        "user_profile": profile or {}
    }

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                    "Here is the current plan JSON. "
                    "Return ONLY the JSON patch in the required format.\n"
                    + json.dumps(user_payload, ensure_ascii=False)
            ),
        },
    ]

    # 保守一点的生成参数，避免风格飞太远
    from copy import deepcopy
    safe_params = deepcopy(gen_params or {})
    # 允许一定多样性；deterministic=True 的情况会在 ollama_chat 里被强制成 0
    try:
        orig_temp = float(safe_params.get("temperature", 0.7))
    except Exception:
        orig_temp = 0.7
    safe_params["temperature"] = min(max(orig_temp, 0.4), 0.9)

    try:
        safe_params["max_tokens"] = min(int(safe_params.get("max_tokens", 512)), 2056)
    except Exception:
        safe_params["max_tokens"] = 512

    try:
        raw = ollama_chat(model_name, messages, safe_params, json_mode=True)
    except Exception as e:
        print("[refine_plan_texts_with_llm] ollama_chat error:", e)
        return draft

    # Ollama 连不上时，你当前实现会返回一串以 ⚠️ 开头的文本，这里直接识别掉
    if raw.startswith("⚠️ 无法连接 Ollama"):
        print("[refine_plan_texts_with_llm] skip refine due to Ollama error:", raw)
        return draft

    # 处理 LLM 返回的 JSON 数据
    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        print("[refine_plan_texts_with_llm] invalid JSON from LLM, raw:", raw[:300])
        return draft

    mods_patch = data.get("modules")
    if not isinstance(mods_patch, list):
        return draft

    # 收集每个模块的文案更新
    updates: Dict[int, Dict[str, str]] = {}
    for item in mods_patch:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(modules)):
            continue

        title = str(item.get("title") or "").strip()
        desc = str(item.get("description") or "").strip()

        # 简单长度控制
        if len(title) > 60:
            title = title[:60].rstrip()
        if len(desc) > 220:
            desc = desc[:220].rstrip()

        if title or desc:
            updates[idx] = {"title": title, "description": desc}

    if not updates:
        return draft
    modified = True

    # 用已有 Risk Guard 做一次整体兜底（如果项目里有 _run_one_gate）
    try:
        all_text = " ".join(
            (u.get("title") or "") + " " + (u.get("description") or "")
            for u in updates.values()
        ).strip()
        if all_text and "_run_one_gate" in globals():
            gate = globals()["_run_one_gate"](all_text)
            if gate and gate.get("high"):
                # 如果 LLM 润色里出现高风险内容，直接丢弃润色
                return draft
    except Exception as e:
        print("[refine_plan_texts_with_llm] risk gate error:", e)
        # 工具异常时，不因为实现 bug 丢掉润色
        pass

    # 应用补丁：只改 title / desc
    new_modules: List[Dict[str, Any]] = []
    for idx, m in enumerate(modules):
        m = dict(m or {})
        upd = updates.get(idx)
        if upd:

            if upd["title"]:
                m["title"] = upd["title"]  # 调试期直接加前缀
            if upd["description"]:
                m["desc"] = upd["description"]
            # m["desc"] = "[LLM] " + m["desc"]  # 调试用，确认生效后可以删

        new_modules.append(m)

    new_draft = dict(draft)
    new_draft["modules"] = new_modules
    if modified:
        new_draft["_llm_refined"] = True
    return new_draft


# ---------------------------------------------------------
# Planner import + normalization (Step 3)
# ---------------------------------------------------------
PLANNER_IMPL_LABEL = "fallback (stub)"


def _default_normalize_draft(obj):
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    try:
        from pydantic import BaseModel as _BM
        if isinstance(obj, _BM):
            return obj.model_dump() if hasattr(obj, "model_dump") else obj.dict()
    except Exception:
        pass
    try:
        from dataclasses import is_dataclass, asdict
        if is_dataclass(obj):
            return asdict(obj)
    except Exception:
        pass
    try:
        return dict(obj)
    except Exception:
        try:
            return dict(obj.__dict__)
        except Exception:
            return {"_repr": repr(obj)}


def _load_planner():
    global PLANNER_IMPL_LABEL
    # 优先 application.planner
    try:
        pm = importlib.import_module("application.planner")
        draft_fn = getattr(pm, "draft_plan", None)
        norm_fn = getattr(pm, "normalize_draft", None)
        if callable(draft_fn):
            PLANNER_IMPL_LABEL = "application.planner:draft_plan"
            return draft_fn, (norm_fn or _default_normalize_draft)
    except Exception:
        pass

    # 其次根目录 planner.py
    try:
        pm = importlib.import_module("planner")
        draft_fn = getattr(pm, "draft_plan", None)
        norm_fn = getattr(pm, "normalize_draft", None)
        if callable(draft_fn):
            PLANNER_IMPL_LABEL = "planner:draft_plan"
            return draft_fn, (norm_fn or _default_normalize_draft)
    except Exception:
        pass

    # Fallback stub
    def _stub_draft_plan(user_input: str, agent_config: Dict[str, Any], memory=None):
        return {
            "plan_types": agent_config.get("plan_types", ["lifestyle"]),
            "horizon_days": int(agent_config.get("horizon_days", 7)),
            "time_windows": [{"label": "evening", "start": "20:00", "end": "22:00"}],
            "constraints": {},
            "modules": [
                {"day": 1, "title": "Evening walk 20′", "tags": ["lifestyle"], "duration_min": 20},
                {"day": 2, "title": "Light stretch 15′", "tags": ["recovery"], "duration_min": 15},
            ],
            "keywords": [],
            "_stub": True,
        }

    PLANNER_IMPL_LABEL = "fallback:stub"
    return _stub_draft_plan, _default_normalize_draft


draft_plan, normalize_draft = _load_planner()

# ---------------------------------------------------------
# Draft enrichment：给模块补 tags / duration 等
# ---------------------------------------------------------
_PRESET = [
    (("补水", "饮水", "水分"), {"tags": ["habit", "hydration"], "duration_min": 10}),
    (("睡眠", "蓝光"), {"tags": ["habit", "sleep"], "duration_min": 30}),
    (("上肢推", "胸", "三头", "push"), {"tags": ["gym", "upper", "push"], "duration_min": 60}),
    (("上肢拉", "背", "二头", "pull"), {"tags": ["gym", "upper", "pull"], "duration_min": 60}),
    (("下肢", "腿", "squat", "deadlift"), {"tags": ["gym", "lower", "legs"], "duration_min": 60}),
    (("备餐", "餐"), {"tags": ["nutrition", "prep"], "duration_min": 60}),
]


def _match_preset(title: str):
    t = title or ""
    for keys, val in _PRESET:
        if any(k in t for k in keys):
            return val
    return {"tags": ["general"], "duration_min": 45}


def _enrich_draft(d: Dict[str, Any]) -> Dict[str, Any]:
    d = dict(d or {})
    d.setdefault("horizon_days", 7)
    d.setdefault("time_windows", [{"label": "evening", "start": "19:00", "end": "22:00"}])
    mods = []
    for i, m in enumerate(d.get("modules") or [], 1):
        m = dict(m or {})
        title = m.get("title") or m.get("name") or f"Module {i}"
        m["title"] = title
        try:
            m["day"] = int(m.get("day") or i)
        except Exception:
            m["day"] = i
        preset = _match_preset(title)
        if not m.get("tags"):
            m["tags"] = preset["tags"][:]
        if not m.get("duration_min") and not m.get("duration"):
            m["duration_min"] = int(preset.get("duration_min", 45))
        mods.append(m)
    d["modules"] = mods
    return d


# ---------------------------------------------------------
# Actions & export helpers
# ---------------------------------------------------------
def _add_minutes(hhmm: str, mins: int) -> str:
    h, m = map(int, hhmm.split(":"))
    total = (h * 60 + m + int(mins)) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _normalize_actions_from_raw(
        raw_actions: List[Dict[str, Any]],
        draft: Dict[str, Any],
        start_date: _date,
) -> List[Dict[str, Any]]:
    """统一把各种来源的 actions 规范成内部 schema，并强制应用 horizon_days 约束。"""
    draft = draft or {}
    horizon = int(draft.get("horizon_days") or 7)

    # 默认时间窗
    tw = (draft.get("time_windows") or [{"start": "19:00", "end": "22:00"}])[0]
    default_start = (tw.get("start") or "19:00")[:5]

    modules = draft.get("modules") or []
    out: List[Dict[str, Any]] = []

    for i, item in enumerate(raw_actions or [], 1):
        item = dict(item or {})
        m = modules[i - 1] if i - 1 < len(modules) else {}

        # ---- day 优先级：action.day > module.day > index ----
        day = item.get("day") or m.get("day")
        date_str = item.get("date")

        # 如无 day 有 date，用 date 反推 day
        if day is None and date_str:
            try:
                d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                day = (d - start_date).days + 1
            except Exception:
                day = None

        if day is None:
            day = i

        try:
            day = int(day)
        except Exception:
            day = i

        # ---- 应用 horizon_days 约束：超出范围直接丢弃 ----
        if day < 1 or day > horizon:
            continue

        # ---- date / duration / time ----
        if not date_str:
            dt = start_date + timedelta(days=day - 1)
            date_str = dt.strftime("%Y-%m-%d")

        dur = item.get("duration_min") or m.get("duration_min") or m.get("duration") or 45
        try:
            dur = int(dur)
        except Exception:
            dur = 45

        start_hhmm = (item.get("start") or default_start)[:5]
        end_hhmm = (item.get("end") or _add_minutes(start_hhmm, dur))[:5]

        # ---- 标题 & 描述 ----
        title = (
                item.get("title")
                or m.get("title")
                or m.get("name")
                or f"Module {i}"
        )
        desc = (
                item.get("desc")
                or item.get("description")
                or m.get("desc")
                or ""
        )

        out.append({
            "title": title,
            "desc": desc,
            "day": day,
            "date": date_str,
            "duration_min": dur,
            "start": start_hhmm,
            "end": end_hhmm,
        })

    # 排序一下，预览更顺眼
    out.sort(key=lambda a: (a["date"], a["start"], a["title"]))
    return out


def _ensure_action_schema(draft: Dict[str, Any], start_date: _date) -> List[Dict[str, Any]]:
    """
    无 Composer 时：
    1. 优先调用 build_actions(draft, start_date)；
    2. 如果返回为空 / 异常，则按 draft.modules 逐条生成 actions，
       确保「草案 = 排程」至少结构上同步。
    """
    draft = draft or {}

    # 1) 先试 build_actions
    try:
        raw = build_actions(draft, start_date) or []
    except Exception:
        raw = []

    if raw:
        return _normalize_actions_from_raw(raw, draft, start_date)

    # 2) fallback：用 modules 直接生成
    horizon = int(draft.get("horizon_days") or 7)
    modules = draft.get("modules") or []
    if not modules:
        return []

    # 默认时间窗
    tw = (draft.get("time_windows") or [{"start": "19:00", "end": "22:00"}])[0]
    default_start = (tw.get("start") or "19:00")[:5]

    actions: List[Dict[str, Any]] = []

    for i, m in enumerate(modules, 1):
        m = dict(m or {})

        # day
        day = m.get("day") or i
        try:
            day = int(day)
        except Exception:
            day = i

        if day < 1 or day > horizon:
            continue

        # date
        dt = start_date + timedelta(days=day - 1)
        date_str = dt.strftime("%Y-%m-%d")

        # duration
        dur = m.get("duration_min") or m.get("duration") or 45
        try:
            dur = int(dur)
        except Exception:
            dur = 45

        # time
        start_hhmm = (m.get("start") or default_start)[:5]
        end_hhmm = (m.get("end") or _add_minutes(start_hhmm, dur))[:5]

        title = m.get("title") or m.get("name") or f"Module {i}"
        desc = m.get("desc") or m.get("description") or ""

        actions.append({
            "title": title,
            "desc": desc,
            "day": day,
            "date": date_str,
            "duration_min": dur,
            "start": start_hhmm,
            "end": end_hhmm,
            "tags": m.get("tags") or [],
        })

    actions.sort(key=lambda a: (a["date"], a["start"], a["title"]))
    return actions


def _should_skip_by_avoid(action: Dict[str, Any], avoid_tags: List[str]) -> bool:
    if not avoid_tags:
        return False

    ats = {str(t).lower() for t in avoid_tags}
    title = (action.get("title") or "").lower()
    tags = [str(t).lower() for t in (action.get("tags") or [])]

    # 1) 标签直接命中
    if any(t in ats for t in tags):
        return True

    # 2) 文本包含（例如用户写 avoid_tags=["hiit"]）
    if any(w in title for w in ats):
        return True

    # 3) 专门兜底“不练腿”：看到这些就当腿
    if any(x in ats for x in ("leg", "legs", "下肢")):
        leg_keywords = [
            "腿", "下肢", "leg day",
            "squat", "deadlift", "弓步", "箭步蹲", "臀腿", "hip thrust"
        ]
        if any(k in title for k in leg_keywords):
            return True
        if any(k in tags for k in ("legs", "leg", "lower")):
            return True

    return False


def _compose_actions(draft: Dict[str, Any], start_date: _date) -> List[Dict[str, Any]]:
    """
    Step 3: Act
    1. 先把 Step 2 的 plan draft 转成 actions（用 composer 或 fallback）。
    2. 然后合并 Draft + Profile（st.session_state.profile）里的约束。
    3. 用 apply_constraints_to_actions 产出最终可排期 actions。
    """
    # 1) 生成基础 actions
    if HAS_COMPOSER and compose_plan is not None:
        prof_obj = _get_profile_obj()
        try:
            actions = compose_plan(draft, prof_obj, start_date)
        except Exception:
            actions = _ensure_action_schema(draft, start_date)
    else:
        actions = _ensure_action_schema(draft, start_date)

    if not isinstance(actions, list):
        actions = []

    # 2) 聚合约束：先用可见 profile dict，再叠加 Composer Profile（如有）
    base_profile = st.session_state.get("profile") or {}
    profile_dict = dict(base_profile)

    if HAS_COMPOSER:
        try:
            prof_obj = _get_profile_obj()
            prof_from_obj = _profile_to_dict(prof_obj)
            if isinstance(prof_from_obj, dict):
                for k, v in prof_from_obj.items():
                    if v is not None:
                        profile_dict[k] = v
        except Exception:
            pass

    constraints = _build_constraints_for_actions(draft, profile_dict)

    # 3) 应用约束（避免项 / 单日上限 / 等等）
    if constraints:
        try:
            actions = apply_constraints_to_actions(actions, constraints)
        except Exception:
            pass

        # ✅ 本地再兜一层，防止外部实现没处理 avoid_tags
        avoid = [str(t) for t in (constraints.get("avoid_tags") or [])]
        if avoid:
            actions = [
                a for a in actions
                if not _should_skip_by_avoid(a, avoid)
            ]
    return actions


def _attach_calendar_fields(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for a in actions:
        b = dict(a)
        b.setdefault("summary", b.get("title", "计划项"))
        b.setdefault("uid", uuid.uuid4().hex)
        if "dtstart" not in b:
            b["dtstart"] = datetime.strptime(f"{b['date']} {b['start']}", "%Y-%m-%d %H:%M")
        if "dtend" not in b:
            b["dtend"] = datetime.strptime(f"{b['date']} {b['end']}", "%Y-%m-%d %H:%M")
        out.append(b)
    return out


def _ensure_plans_dir() -> Path:
    try:
        PLANS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return PLANS_DIR


def _save_plan_version(actions: List[Dict[str, Any]], preview_id: str = "") -> str:
    """
    保存当前计划为版本化文件：
    logs/plans/week_plan_v{n}.json + week_plan_latest.json
    """
    plan_dir = _ensure_plans_dir()

    # 序列化 datetime，避免 json 报错
    serial_actions = []
    for a in actions:
        b = dict(a)
        dt = b.get("dtstart")
        if isinstance(dt, datetime):
            b["dtstart"] = dt.isoformat()
        dt = b.get("dtend")
        if isinstance(dt, datetime):
            b["dtend"] = dt.isoformat()
        serial_actions.append(b)

    # 计算下一个版本号
    max_v = 0
    for p in plan_dir.glob("week_plan_v*.json"):
        name = p.stem  # week_plan_vX
        try:
            v = int(name.rsplit("v", 1)[1])
            max_v = max(max_v, v)
        except Exception:
            continue
    ver = max_v + 1

    meta = {
        "version": ver,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "preview_id": preview_id,
    }
    payload = {"meta": meta, "actions": serial_actions}

    path = plan_dir / f"week_plan_v{ver}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    latest = plan_dir / "week_plan_latest.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return str(path)


def _load_latest_plan() -> (List[Dict[str, Any]], Dict[str, Any]):
    """
    读取最近一次导出的周计划（latest 或最大版本号）。
    返回 (actions, meta)
    """
    plan_dir = _ensure_plans_dir()
    latest = plan_dir / "week_plan_latest.json"
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
        return data.get("actions") or [], data.get("meta") or {}
    except Exception:
        pass

    best = None
    max_v = 0
    for p in plan_dir.glob("week_plan_v*.json"):
        name = p.stem
        try:
            v = int(name.rsplit("v", 1)[1])
        except Exception:
            continue
        if v > max_v:
            max_v, best = v, p

    if best:
        try:
            data = json.loads(best.read_text(encoding="utf-8"))
            return data.get("actions") or [], data.get("meta") or {}
        except Exception:
            return [], {}

    return [], {}


def _normalize_loaded_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    把 json 里的 actions 补齐 uid/date/start/end/duration_min 等字段，
    并移除字符串形式的 dtstart/dtend，留给后续统一重建。
    """
    fixed = []
    for idx, a in enumerate(actions):
        if not isinstance(a, dict):
            continue
        b = dict(a)

        uid = b.get("uid") or b.get("id") or f"act-{idx}"
        b["uid"] = str(uid)

        # 如果有 dtstart/dtend，先尽量反推 date/start/end
        if not b.get("date") and b.get("dtstart"):
            try:
                dt = datetime.fromisoformat(str(b["dtstart"]))
                b["date"] = dt.date().isoformat()
                b["start"] = dt.strftime("%H:%M")
            except Exception:
                pass

        if not b.get("end") and b.get("dtend"):
            try:
                dt = datetime.fromisoformat(str(b["dtend"]))
                b["end"] = dt.strftime("%H:%M")
            except Exception:
                pass

        # 反推 duration
        if not b.get("duration_min") and b.get("start") and b.get("end"):
            try:
                sh, sm = [int(x) for x in b["start"].split(":")]
                eh, em = [int(x) for x in b["end"].split(":")]
                dur = (eh * 60 + em) - (sh * 60 + sm)
                if dur > 0:
                    b["duration_min"] = dur
            except Exception:
                pass

        # 🔧 关键修复点：
        # 如果 dtstart/dtend 是字符串（来自 json），删掉，避免后面直接 .strftime 爆炸，
        # 后续会由 _attach_calendar_fields 根据 date/start/end 统一重建为 datetime。
        if isinstance(b.get("dtstart"), str):
            b.pop("dtstart", None)
        if isinstance(b.get("dtend"), str):
            b.pop("dtend", None)

        fixed.append(b)

    return fixed


def _format_action_label(a: Dict[str, Any]) -> str:
    date = a.get("date") or "????-??-??"
    start = a.get("start") or "--:--"
    end = a.get("end") or "--:--"
    title = a.get("title") or a.get("summary") or "(无标题)"
    return f"{date} {start}-{end} · {title}"


def _parse_replan_constraints(text: str) -> Dict[str, Any]:
    """
    从自然语言里抽 Rolling Replan 能直接用的约束。
    支持：
    - 不练腿
    - 发烧/感冒：限制或禁止训练（安全优先）
    - 不做 HIIT / 只做轻松
    - 最晚结束时间
    """
    c: Dict[str, Any] = {}
    if not text:
        return c

    raw = text.strip()
    t = raw.lower()
    avoid_tags = []

    # 1) 不练腿
    if "不练腿" in raw or "本周不练腿" in raw or "no leg" in t or "no legs" in t:
        avoid_tags.extend(["legs", "leg", "下肢", "腿"])

    # 2) 发烧 / 感冒 情况 —— 非常关键：倾向禁止高强度
    if "发烧" in raw or "烧到" in raw or "感冒" in raw:
        m = re.search(r"(\d+(?:\.\d+)?)\s*度", raw)
        temp = float(m.group(1)) if m else 38.0

        if temp >= 38.0:
            # 对 38° 以上：建议完全不排高强度，强烈倾向休息
            c["max_daily_minutes"] = 0  # 交给 apply_constraints_to_actions 清空未来训练
            c["rpe_max"] = 3
            avoid_tags += ["hiit", "sprint", "all_out", "heavy", "max", "pr"]
        else:
            # 低热/不适：最多极轻活动
            c["max_daily_minutes"] = 10
            c["rpe_max"] = 4
            avoid_tags += ["hiit", "sprint", "all_out"]

    # 3) 显式提到“不做 HIIT” / “只做轻松”
    if "不做hiit" in t or "不做 hiit" in t:
        avoid_tags.append("hiit")

    if "只做轻松" in raw or "轻松一点" in raw or "低强度" in raw:
        # 控制主观强度
        c.setdefault("rpe_max", 6)

    # 4) 最晚结束时间（原有逻辑）
    m = re.search(r"(\d{1,2}):(\d{2})", raw)
    if m and ("前" in raw or "之前" in raw or "before" in t):
        hh = int(m.group(1))
        mm = int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            c["latest_end"] = f"{hh:02d}:{mm:02d}"

    if avoid_tags:
        c["avoid_tags"] = list(dict.fromkeys(avoid_tags))

    return c


def _replan_actions(
        original_actions: List[Dict[str, Any]],
        done_ids: List[str],
        cannot_ids: List[str],
        new_constraints: Dict[str, Any],
        today: Optional[_date] = None,
) -> List[Dict[str, Any]]:
    """
    Rolling Replan（修正版）：
    - 已完成 / 已经过的日期：保留不动；
    - cannot_ids：直接移除；
    - 其余未来任务：根据 new_constraints 做轻量调整；
    - 最后套一遍 apply_constraints_to_actions。
    """
    if today is None:
        today = _date.today()

    acts = _normalize_loaded_actions(original_actions)
    done_set = set(done_ids or [])
    cannot_set = set(cannot_ids or [])

    frozen: List[Dict[str, Any]] = []  # 不再动的任务（历史 + 已完成）
    replannable: List[Dict[str, Any]] = []  # 可以调整的未来任务

    for idx, a in enumerate(acts):
        b = dict(a)
        uid = str(b.get("uid") or f"act-{idx}")
        b["uid"] = uid

        try:
            d = datetime.strptime(str(b.get("date")), "%Y-%m-%d").date()
        except Exception:
            d = today

        if uid in cannot_set:
            # 明确取消，直接丢弃
            continue

        if uid in done_set or d < today:
            frozen.append(b)
        else:
            replannable.append(b)

    # ---- 解析新约束 ----
    avoid_tags = set(t.lower() for t in (new_constraints.get("avoid_tags") or []) if t)
    latest_end = str(new_constraints.get("latest_end") or "").strip()  # "HH:MM" or ""

    # 预计算 latest_end 分钟数
    latest_end_min = None
    if latest_end:
        try:
            hh, mm = map(int, latest_end[:5].split(":"))
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                latest_end_min = hh * 60 + mm
        except Exception:
            latest_end_min = None

    adjusted: List[Dict[str, Any]] = []

    for idx, a in enumerate(replannable):
        b = dict(a)
        title = str(b.get("title", "")) or ""
        lt = title.lower()
        tags = [str(t).lower() for t in (b.get("tags") or [])]

        # 1) 处理 avoid_tags（不练腿 / 不做 HIIT 等）
        if avoid_tags:
            hit = False

            # tag 精确命中
            if any(t in avoid_tags for t in tags):
                hit = True

            # 标题中包含任意 avoid 关键词
            if not hit:
                for at in avoid_tags:
                    if at and at in lt:
                        hit = True
                        break

            # 不练腿：标题触发腿关键词
            if ("腿" in title or "下肢" in title or "leg" in lt or "legs" in lt) and \
                    any(x in avoid_tags for x in ("腿", "下肢", "leg", "legs")):
                hit = True

            if hit:
                # 命中禁止项：这条任务直接取消
                continue

        # 2) 处理最晚结束时间（超过 latest_end 的任务丢弃）
        if latest_end_min is not None and b.get("end"):
            try:
                eh, em = map(int, str(b["end"])[:5].split(":"))
                end_min = eh * 60 + em
                if end_min > latest_end_min:
                    # 超过用户要求的最晚结束时间，去掉
                    continue
            except Exception:
                pass

        # ✅ 关键：保留下来的任务要加入 adjusted
        adjusted.append(b)

    # ---- 合并 + 排序 ----
    frozen.sort(key=lambda x: (x.get("date", ""), x.get("start", ""), x.get("title", "")))
    adjusted.sort(key=lambda x: (x.get("date", ""), x.get("start", ""), x.get("title", "")))
    merged = frozen + adjusted
    merged.sort(key=lambda x: (x.get("date", ""), x.get("start", ""), x.get("title", "")))

    # ---- 再套一次通用约束（例如 max_daily_minutes / rpe_max 等）----
    try:
        if new_constraints:
            merged = apply_constraints_to_actions(merged, new_constraints)
    except Exception:
        # 出错不阻塞使用，直接返回未二次约束的版本
        pass

    return merged


def _summarize_replan_changes(
        done_ids: List[str],
        cannot_ids: List[str],
        original_n: int,
        new_n: int,
) -> str:
    return (
        f"本次调整：标记已完成 {len(done_ids)} 项，取消 {len(cannot_ids)} 项，"
        f"原计划 {original_n} 项 → 调整后剩余 {new_n} 项。"
    )


def _get_profile_obj() -> Optional[object]:
    if not HAS_COMPOSER:
        return None
    p = st.session_state.get("profile") or {}
    try:
        if hasattr(Profile, "from_dict"):
            return Profile.from_dict(p)
        return Profile(**p)
    except Exception:
        try:
            return Profile()
        except Exception:
            return None


def _profile_to_dict(p: object) -> Dict[str, Any]:
    """把 Profile 对象安全地摊平成 dict."""
    if p is None:
        return {}
    # 优先 as_dict / dict / model_dump
    for attr in ("as_dict", "dict", "model_dump"):
        fn = getattr(p, attr, None)
        if callable(fn):
            try:
                d = fn()
                if isinstance(d, dict):
                    return d
            except Exception:
                pass
    # fallback: __dict__
    try:
        return dict(p.__dict__)
    except Exception:
        return {}


def _build_constraints_for_actions(
        draft: Dict[str, Any],
        profile_dict: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    c = dict(draft.get("constraints") or {})

    if profile_dict:
        # 1) max_daily_minutes: Draft 优先，其次 Profile（取更小）
        if not c.get("max_daily_minutes"):
            md = profile_dict.get("max_daily_minutes")
            if md:
                try:
                    c["max_daily_minutes"] = int(md)
                except Exception:
                    pass

        # 2) avoid_tags 合并：
        #    draft.constraints.avoid_tags
        #    + profile.avoid_tags
        #    + profile.avoid.muscle_groups （当成 tag 用）
        avoid: list[str] = []
        avoid.extend(c.get("avoid_tags") or [])
        avoid.extend(profile_dict.get("avoid_tags") or [])

        avoid_cfg = profile_dict.get("avoid") or {}
        if isinstance(avoid_cfg, dict):
            mg = avoid_cfg.get("muscle_groups") or []
            avoid.extend(str(x).strip() for x in mg if str(x).strip())

        if avoid:
            merged, seen = [], set()
            for t in avoid:
                s = str(t).strip()
                if not s:
                    continue
                k = s.lower()
                if k not in seen:
                    seen.add(k)
                    merged.append(s)
            if merged:
                c["avoid_tags"] = merged

        # 3) 其他字段：例如最小肌群间隔等，直接带进去
        if "min_muscle_gap_h" not in c and profile_dict.get("min_muscle_gap_h"):
            c["min_muscle_gap_h"] = profile_dict["min_muscle_gap_h"]

    return c


LONG_TERM_TRIGGERS_CN = ("以后", "从现在起", "之后都", "长期", "一直", "每次都", "默认", "记住")
LONG_TERM_TRIGGERS_EN = ("from now on", "by default", "always", "in general", "usually", "every time")


def _looks_like_long_term_pref(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if not t:
        return False
    tl = t.lower()
    if any(k in t for k in LONG_TERM_TRIGGERS_CN):
        return True
    if any(k in tl for k in LONG_TERM_TRIGGERS_EN):
        return True
    return False


def extract_profile_updates_from_text(text: str) -> Dict[str, Any]:
    """
    从用户输入语句中提炼「适合作为长期偏好/约束」的信息。
    只处理非常明确的情况，且优先需要含“以后/从现在起/by default”等长期信号。
    返回可直接 merge 到 profile 的 dict：
      - max_daily_minutes: int
      - avoid_tags: List[str]
      - time_windows: [ {label, start, end, days} ]
    """
    updates: Dict[str, Any] = {}
    if not text:
        return updates

    t = text.strip()
    if not t:
        return updates
    tl = t.lower()
    long_term = _looks_like_long_term_pref(t)

    # ---------- 1) 每日时长上限 ----------
    # 示例：
    #   "以后每天最多 40 分钟"
    #   "从现在起训练控制在 60 分钟以内"
    if long_term:
        m = re.search(r"(?:每天|每次|日常)[^0-9]{0,6}(\d{2,3})\s*(?:分钟|min)", t)
        if not m:
            m = re.search(r"(?:不超过|最多|上限|limit(?: to)?|within)\s*(\d{2,3})\s*(?:分钟|min)", t)
        if m:
            try:
                val = int(m.group(1))
                if 10 <= val <= 300:
                    updates["max_daily_minutes"] = val
            except Exception:
                pass

    # ---------- 2) 避免类目（腿 / HIIT / 跳跃等） ----------
    avoid_tags = set()

    # 不练腿 / no legs
    if long_term and (
            "不练腿" in t or "本周不练腿" in t or "不要安排腿" in t or
            "no leg" in tl or "no legs" in tl
    ):
        avoid_tags.update(["legs", "leg", "下肢"])

    # 不做 HIIT
    if ("不做hiit" in tl or "不要 hiit" in tl or "讨厌hiit" in tl) and long_term:
        avoid_tags.add("hiit")

    # 不跳 / 低冲击（这里不记录诊断，只抽象成运动特性）
    if long_term and ("不要跳" in t or "不做跳跃" in t or "避免高冲击" in t):
        avoid_tags.update(["jump", "plyometric", "hi_impact"])

    # 膝盖不适 + 长期语气：转成“避免高冲击”类标签
    if long_term and ("膝盖" in t and ("不太行" in t or "有伤" in t or "老伤" in t or "不舒服" in t)):
        avoid_tags.update(["jump", "plyometric", "hi_impact"])

    if avoid_tags:
        updates["avoid_tags"] = sorted(avoid_tags)

    # ---------- 3) 偏好时间窗 ----------
    # 例：
    #   "以后基本只在 21:00-22:30 有空"
    #   "从现在起我晚上9点以后练就行"
    win = None

    if long_term:
        # 形式 21:00-22:30
        times = re.findall(r"(\d{1,2}):(\d{2})", t)
        if len(times) >= 2:
            try:
                (h1, m1), (h2, m2) = times[0], times[1]
                h1, m1, h2, m2 = int(h1), int(m1), int(h2), int(m2)
                if 0 <= h1 <= 23 and 0 <= h2 <= 23:
                    win = {
                        "label": "preferred",
                        "start": f"{h1:02d}:{m1:02d}",
                        "end": f"{h2:02d}:{m2:02d}",
                        "days": [1, 2, 3, 4, 5, 6, 7],
                    }
            except Exception:
                win = None

        # 文本："晚上9点以后"
        if win is None:
            m = re.search(r"晚上\s*(\d{1,2})\s*点以后", t)
            if m:
                try:
                    h = int(m.group(1))
                    if 0 <= h <= 23:
                        win = {
                            "label": "evening",
                            "start": f"{h:02d}:00",
                            "end": "23:30",
                            "days": [1, 2, 3, 4, 5, 6, 7],
                        }
                except Exception:
                    pass

    if win:
        updates["time_windows"] = [win]

    return updates


def merge_profile(old_profile: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    """
    把抽取到的长期偏好合并进 profile。
    规则：
    - max_daily_minutes 取更小（更保守）
    - avoid_tags 合并去重
    - time_windows：用新偏好更新第一个时间窗（没有则新增）
    """
    p = dict(old_profile or {})
    if not updates:
        return p

    # max_daily_minutes: 取更小
    if "max_daily_minutes" in updates:
        try:
            new_val = int(updates["max_daily_minutes"])
            if new_val > 0:
                old_val = int(p.get("max_daily_minutes") or 0)
                p["max_daily_minutes"] = new_val if not old_val else min(old_val, new_val)
        except Exception:
            pass

    # avoid_tags: 合并去重
    if "avoid_tags" in updates:
        base = [str(t) for t in (p.get("avoid_tags") or [])]
        extra = [str(t) for t in (updates["avoid_tags"] or [])]
        merged, seen = [], set()
        for t in base + extra:
            s = t.strip()
            if not s:
                continue
            k = s.lower()
            if k not in seen:
                seen.add(k)
                merged.append(s)
        if merged:
            p["avoid_tags"] = merged

    # time_windows: 优先更新第一个
    if "time_windows" in updates:
        new_tw = updates["time_windows"]
        if isinstance(new_tw, list) and new_tw:
            base_tw = p.get("time_windows") or []
            tw_new0 = dict(new_tw[0])
            if base_tw:
                tw0 = dict(base_tw[0])
                for key in ("label", "start", "end", "days"):
                    if key in tw_new0 and tw_new0[key]:
                        tw0[key] = tw_new0[key]
                base_tw[0] = tw0
                p["time_windows"] = base_tw
            else:
                p["time_windows"] = [tw_new0]

    return p


def _format_profile_updates_for_toast(updates: Dict[str, Any]) -> str:
    """
    把本次更新的关键点变成一句简短提示，用于 st.toast。
    """
    if not updates:
        return ""
    parts = []
    if "max_daily_minutes" in updates:
        parts.append(f"单日不超过 {updates['max_daily_minutes']} 分钟")
    if "avoid_tags" in updates:
        parts.append("避免：" + "、".join(updates["avoid_tags"]))
    if "time_windows" in updates and updates["time_windows"]:
        tw = updates["time_windows"][0]
        label = tw.get("label", "训练时段")
        start = tw.get("start", "")
        end = tw.get("end", "")
        parts.append(f"{label} {start}-{end}")
    return "，".join(parts)


# ---------------------------------------------------------
# Basic config
# ---------------------------------------------------------
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODELS = ["wellnessone:latest", "llama3.1:8b-instruct-q4_K_M"]
ALLOWED_PLAN_INTENTS = {"HEALTH_PLAN", "FITNESS_GYM", "NUTRITION", "REHAB"}

LOG_DIR = _PROJ_ROOT / "logs"
PLANS_DIR = LOG_DIR / "plans"

PLAN_REQUEST_KEYWORDS = (
    "训练计划", "健身计划", "饮食计划", "减脂计划", "增肌计划",
    "恢复计划", "作息计划", "计划表", "日程表", "排期", "排程", "课程表",
)
PLAN_REQUEST_VERBS = (
    "帮我制定", "帮我出", "帮我做", "帮我安排",
    "给我做", "给我出", "给我一个",
    "出一个", "做一个", "设计一个", "定一个", "安排一下",
)


def is_explicit_plan_request(
        text: str,
        intent: str,
        history_messages: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """
    只有在：
      - 勾选了计划模式（外层判断）
      - 且本函数返回 True
    的时候，才允许真正生成计划。
    intent 只作参考，不单独触发。
    """
    if not text:
        return False

    t = text.strip()
    tl = t.lower()

    # 当前这句话有明显“出计划”信号
    if any(kw in t for kw in PLAN_REQUEST_KEYWORDS):
        return True
    if any(kw in t for kw in PLAN_REQUEST_VERBS):
        return True
    if any(kw in tl for kw in (
            "make a plan",
            "training plan",
            "workout plan",
            "diet plan",
            "schedule a plan",
            "program for me",
            "design a plan",
    )):
        return True

    # 看最近几条用户话，有没有已经明确说“帮我做个计划”
    if history_messages:
        recent_user_texts = [
            str(m.get("content", ""))
            for m in history_messages[-6:]
            if m.get("role") == "user"
        ]
        recent_user_texts.reverse()  # 从最近往前看
        for ut in recent_user_texts:
            if any(kw in ut for kw in PLAN_REQUEST_KEYWORDS) \
                    or any(kw in ut for kw in PLAN_REQUEST_VERBS):
                return True
            # 如果遇到明显是问句（倾向问答而不是规划），就停止往前推
            if ut.endswith("?") or "？" in ut or "吗" in ut:
                break

    return False


# ---------------------------------------------------------
# Step 7: 本地知识库检索 + LLM 结合回答
# ---------------------------------------------------------
def retrieve_knowledge(
        query: str,
        k: int = 10,
        min_score: float = 0.1,
        max_items: int = 3,
        intent: Optional[str] = None,
        lang: str = "zh"
) -> List[Dict[str, Any]]:
    try:
        retriever = get_retriever_autoload()
        print(f"=== 检索器信息 ===")
        print(f"检索器类型：{type(retriever).__name__}")
        print(f"查询语言：{lang}，查询文本：{query}")

        # 1. 调用检索器获取原始结果
        raw_hits = retriever.search(query, k=k)
        print(f"检索器原生返回结果数：{len(raw_hits)}")

        # 2. 语言过滤：优先保留与查询语言匹配的文件
        lang_filtered_hits = []
        other_hits = []
        for hit in raw_hits:
            path = hit.get("path", "")
            snippet = hit.get("snippet", "").lower()
            score = hit.get("score", 0.0)

            # 跳过分数过低的结果
            if score < min_score:
                continue

            # 语言判断：根据文件内容/路径中的语言特征分类
            has_chinese = bool(re.search(r'[\u4e00-\u9fff]', snippet))  # 包含中文字符
            has_english = bool(re.search(r'[a-zA-Z]{2,}', snippet))  # 包含英文单词

            # 按查询语言优先过滤
            if lang == "zh" and has_chinese:
                lang_filtered_hits.append(hit)
            elif lang == "en" and has_english and not has_chinese:
                lang_filtered_hits.append(hit)
            else:
                other_hits.append(hit)

        # 3. 合并结果：语言匹配的结果在前，其他在后
        filtered_hits = lang_filtered_hits + other_hits
        print(f"语言过滤后结果数：{len(filtered_hits)}（语言匹配：{len(lang_filtered_hits)}，其他：{len(other_hits)}）")

        # 4. 二次排序：确保分数高的结果在前（重新排序，避免语言过滤打乱相关性）
        filtered_hits.sort(key=lambda x: x.get("score", 0.0), reverse=True)

        # 5. 标准化结果格式
        final_hits = []
        for i, hit in enumerate(filtered_hits[:max_items]):
            snippet = hit.get("snippet", "").strip()
            path = hit.get("path", "").strip()
            score = round(hit.get("score", 0.0), 4)

            final_hits.append({
                "snippet": snippet[:200] + "..." if len(snippet) > 200 else snippet,
                "path": path,
                "score": score,
                "raw": hit
            })
            print(f"最终结果{i + 1}：路径={path}，分数={score}，内容={snippet[:50]}...")

    except Exception as e:
        print(f"检索函数报错：{str(e)}")
        return []

    return final_hits
# def retrieve_knowledge(
#         query: str,
#         k: int = 16,
#         min_score: float = 0.1,  # 提高最低分数阈值（原0.0）
#         rel_keep: float = 0.6,  # 提高相关性保留比例（原0.4）
#         max_items: int = 3,  # 减少返回数量，只保留最相关的3条
#         intent: Optional[str] = None,
#         lang: str = "zh"
# ) -> List[Dict[str, Any]]:
#     try:
#         retriever = get_retriever_autoload()
#         hits = retriever.search(query, k=k) or []
#     except Exception:
#         return []
#
#     if not hits:
#         return []
#     # 新增：按意图过滤（优先保留意图相关文档）
#     if intent:
#         intent_hints = {
#             "FITNESS_GYM": ["健身", "力量训练", "gym", "workout"],
#             "REHAB": ["康复", "损伤", "rehab", "injury"],
#             "NUTRITION": ["营养", "饮食", "nutrition", "diet"],
#             "HEALTH_QA": ["健康", "区分", "health", "distinguish"]
#         }.get(intent.upper(), [])
#         # 保留包含意图线索的结果
#         hits = [h for h in hits if any(hint in str(h.get("snippet", "")) for hint in intent_hints)]
#
#     # 新增：按语言过滤（保留对应语言的文档）
#     lang_hints = {"en": ["en", "english", "workout", "injury"], "zh": ["zh", "中文", "健身", "康复"]}
#     hits = [h for h in hits if
#             any(hint in str(h.get("path", "")) or hint in str(h.get("snippet", "")) for hint in lang_hints[lang])]
#
#
#
#     # for h in hits:
#     #     try:
#     #         h["score"] = float(h.get("score", 0.0))
#     #     except Exception:
#     #         h["score"] = 0.0
#     # hits.sort(key=lambda x: x["score"], reverse=True)
#     #
#     # top = hits[0]["score"]
#     # if top <= 0:
#     #     return []
#     #
#     # cutoff = top * rel_keep  # 放宽一点
#     #
#     # good = [h for h in hits if h["score"] >= cutoff]
#     #
#     # if not good:
#     #     good = [hits[0]]
#     #
#     # return good[:max_items]
#     for h in hits:
#         try:
#             h["score"] = float(h.get("score", 0.0))
#         except Exception:
#             h["score"] = 0.0
#     hits.sort(key=lambda x: x["score"], reverse=True)
#     top_score = hits[0]["score"] if hits else 0
#     if top_score <= 0:
#         return []
#     # 只保留分数≥最低阈值 且 分数≥top_score*rel_keep 的结果
#     cutoff = max(min_score, top_score * rel_keep)
#     good_hits = [h for h in hits if h["score"] >= cutoff]
#     if not good_hits:
#         good_hits = [hits[0]] if hits else []  # 兜底保留第一条
#     return good_hits[:max_items]


def build_kb_context(hits: List[Dict[str, Any]], max_items: int = 3) -> str:
    """
    把检索结果整理成给 LLM 看的上下文（不直接给用户看）。
    """
    if not hits:
        return ""
    chunks = []
    for i, h in enumerate(hits[:max_items], 1):
        fname = Path(h.get("path", "")).name
        snippet = str(h.get("snippet", "")).strip()
        score = h.get("score", 0.0)
        chunks.append(
            f"[{i}] 来源文件: {fname} (score={score})\n{snippet}"
        )
    return "\n\n".join(chunks)

def llm_answer_with_kb(
        user_text: str,
        intent: str,
        history: Optional[List[Dict[str, str]]] = None,
):
    lang = get_text_language(user_text)  # 替换为统一的检测函数
    # 新增日志：打印接收的 intent
    print(f"\n=== llm_answer_with_kb 接收参数 ===")
    print(f"用户文本：{user_text[:30]}...")
    print(f"接收的 intent：{intent}（类型：{type(intent).__name__}）")  # 关键日志
    # 1. 检索证据（保留基础逻辑，新增检索结果打印，明确是否命中）
    hits = retrieve_knowledge(query=user_text, intent=intent, lang=lang)
    has_kb = bool(hits)
    # 调试打印：强制显示检索结果（方便排查是检索还是生成问题）
    print(f"\n=== 问答证据检索结果 ===")
    print(f"查询文本：{user_text}，语言：{lang}，意图：{intent}")
    print(f"命中证据数量：{len(hits)}")
    for i, hit in enumerate(hits):
        print(f"证据{i+1}：路径={hit.get('path')}，相关性分数={hit.get('score', 0)}，内容片段={hit.get('snippet', '')[:80]}...")

    msgs: List[Dict[str, str]] = []

    if lang == "en":
        system_prompt = """
    You are a knowledge-based assistant. FOLLOW THESE RULES STRICTLY:
    1. BASE YOUR ANSWER ON THE EVIDENCE BLOCKS BELOW. Summarize and generalize the core points (DO NOT simply list or copy the original evidence text).
    2. For the question "How to distinguish between DOMS and sports injury", structure your answer as CLEAR comparison points (e.g., onset time, pain characteristics, recovery period).
    3. Mark each comparison point with a reference [1] or [2] to indicate which evidence it comes from.
    4. Keep the answer concise (3-5 key comparison points), easy to understand, and focused on "distinguishing differences".
    5. Do NOT add content unrelated to the evidence; do NOT repeat the original evidence content.
            """.strip()
        if has_kb:
            kb_context = "=== EVIDENCE BLOCKS ===\n"
            for i, hit in enumerate(hits, 1):
                snippet = hit.get("snippet", "").strip()
                source = hit.get("path", "Unknown Source")
                kb_context += f"\n[Evidence {i}] Source: {source}\nContent: {snippet}\n"
        no_kb_prompt = "Relevant evidence in the knowledge base is limited. For critical decisions, consult a professional."
        user_prompt = f"Answer the question clearly: {user_text}\nRequired format: 3-5 comparison points (summarized, not copied) + [1]/[2] references."

    else:
        system_prompt = """
    你是基于知识库的助手，必须遵守以下规则：
    1. 基于下方证据块回答，提炼核心要点进行总结概括（禁止简单罗列或复制原文）；
    2. 针对“如何区分肌肉酸痛和运动损伤”，回答需按「明确对比维度」展开（如：发作时间、疼痛特征、恢复周期）；
    3. 每个对比要点需标注 [1] 或 [2] 引用，对应支撑证据的编号；
    4. 回答简洁（3-5个核心对比点）、易懂，聚焦“区分差异”；
    5. 不得添加无关内容，不得重复证据原文。
            """.strip()
        if has_kb:
            kb_context = "=== 证据块 ===\n"
            for i, hit in enumerate(hits, 1):
                snippet = hit.get("snippet", "").strip()
                source = hit.get("path", "未知来源")
                kb_context += f"\n[证据 {i}] 来源：{source}\n内容：{snippet}\n"
        no_kb_prompt = "知识库中相关证据有限，重要决策建议咨询专业人士。"
        user_prompt = f"清晰回答问题：{user_text}\n要求格式：3-5个对比要点（总结提炼，非原文复制）+ [1]/[2] 引用标记。"

    # 3. 组装消息：系统指令 → 证据块 → 用户问题（固定顺序，LLM无法跳过）
    if has_kb:
        msgs.append({"role": "system", "content": system_prompt})
        msgs.append({"role": "system", "content": kb_context})
    else:
        msgs.append({"role": "system", "content": no_kb_prompt})

    # 4. 清除冗余历史：只保留用户当前问题，避免干扰
    if history:
        msgs.extend([{"role": "user", "content": user_text}])
    else:
        msgs.append({"role": "user", "content": user_prompt if has_kb else user_text})

    gen_params = st.session_state.gen_params.copy()
    gen_params["temperature"] = 0.3  # 允许轻微扩展，避免机械复制
    gen_params["top_p"] = 0.9
    gen_params["max_tokens"] = 768  # 放宽长度限制，支持合理阐述

    answer = ollama_chat(st.session_state.model_name, msgs, gen_params)

    # 6. 终极校验：强制拦截未引用证据的回答（硬规则，不是参数）
    # if has_kb:
    #     # 检查回答是否包含证据引用标记（如[1]、[2]）
    #     if not re.search(r"\[\d+\]", answer):
    #         # 未引用证据，直接替换为固定提示
    #         answer = (
    #             "No relevant evidence found in the knowledge base. Please consult a professional."
    #             if lang == "en"
    #             else "知识库中无相关证据，请咨询专业人士。"
    #         )
    #     # 清除LLM偷偷添加的无关内容
    #     answer = re.sub(r"(?i)note:|tip:|建议:|提示:|additional:.*$", "", answer)

    return answer, hits
# def llm_answer_with_kb(
#         user_text: str,
#         intent: str,
#         history: Optional[List[Dict[str, str]]] = None,
# ):
#     # 关键新增：检测用户输入语言（第一次输入也会执行）
#     lang = detect_language(user_text)  # 从 language_utils 导入
#     # hits = retrieve_knowledge(user_text)
#     hits = retrieve_knowledge(
#         query=user_text,
#         intent=intent,  # 让检索器优先匹配意图相关知识库
#         lang=lang  # 匹配对应语言的知识库（中英文分离）
#     )
#     has_kb = bool(hits)
#     msgs: List[Dict[str, str]] = []
#
#     # 根据语言选择系统提示词（中英文分离）
#     if lang == "en":
#         system_prompt = (
#             "You are FitForU's health and training assistant.\n"
#             "Relevant internal knowledge base evidence will be provided below.\n"
#             "Answer strictly based on the evidence with clear structure:\n"
#             "1) Summarize key points in your own words;\n"
#             "2) Do not paste the original text in large chunks or output markdown headings;\n"
#             "3) Do not use procedural phrases like 'I will record the situation';\n"
#             "4) Do not provide prescription drug names or specific dosages;\n"
#             "5) For parts not covered by evidence, only give general advice and explain limitations."
#         )
#         no_kb_prompt = (
#             "You are FitForU's health and training assistant.\n"
#             "No relevant internal knowledge base content was retrieved.\n"
#             "You can provide general advice based on common sense, but must clearly state:\n"
#             "These do not constitute personalized medical opinions and cannot include prescription drugs or specific dosages."
#         )
#         user_prompt = (
#             f"Please answer my question based on the above evidence: {user_text}\n"
#             "Summarize in 3–6 key points with concise explanations, do not directly copy the original evidence or output large headings."
#         )
#     else:
#         # 原有中文提示词
#         system_prompt = (
#             "你是 FitForU 的健康与训练助手。\n"
#             "上面会提供与用户问题相关的内部知识库证据。\n"
#             "请严格以证据为主要依据回答，要求："
#             "1) 用自己的话总结要点，结构清晰；"
#             "2) 不大段粘贴原文，不输出 markdown 标题；"
#             "3) 不说“我会记录情况/尽快告知”等流程性话术；"
#             "4) 不给处方药名和具体剂量；"
#             "5) 证据没有覆盖的部分，只给非常一般性的建议并说明局限。"
#         )
#         no_kb_prompt = (
#             "你是 FitForU 的健康与训练助手。"
#             "当前没有检索到相关内部知识库内容。"
#             "你可以基于常识给一般性建议，但必须明确说明："
#             "这些不构成个体化医疗意见，且不能包含处方药或具体剂量。"
#         )
#         user_prompt = (
#             f"请基于上方证据回答我的问题：{user_text}\n"
#             "用 3–6 条要点 + 简洁解释总结，不要直接复制证据原文或输出大字号标题。"
#         )
#
#     # 后续逻辑不变，只是替换了提示词为语言对应的版本
#     if has_kb:
#         kb_context = build_kb_context(hits)
#         system_prompt = (
#             "You are FitForU's health and training assistant. "
#             "You MUST answer STRICTLY based on the provided evidence fragments below. "
#             "If the evidence does not cover the question, state 'No sufficient evidence to support this, please consult a professional.' "
#             "Do NOT add any external information or personal opinions. "
#             "Structure your answer in 3-6 concise points, summarizing the evidence in your own words. "
#             "Do not paste the original evidence text directly."
#         ) if lang == "en" else (
#             "你是FitForU的健康与训练助手。"
#             "必须严格基于下方提供的证据片段回答。"
#             "若证据未覆盖问题，请说明‘无足够证据支持，建议咨询专业人士。’"
#             "不得添加任何外部信息或个人观点。"
#             "用3-6条简洁要点总结证据，用自己的话表述，不要直接粘贴原文。"
#         )
#         msgs.append({"role": "system", "content": system_prompt})
#         msgs.append({"role": "system", "content": f"【Evidence Fragments】\n{kb_context}"})
#     else:
#         msgs.append({"role": "system", "content": no_kb_prompt})
#
#     if history:
#         recent = [
#             {"role": m["role"], "content": m["content"]}
#             for m in history[-6:]
#             if m.get("role") in ("user", "assistant")
#         ]
#         msgs.extend(recent)
#
#     if has_kb:
#         msgs.append({"role": "user", "content": user_prompt})
#     else:
#         msgs.append({"role": "user", "content": user_text})
#
#     # 生成回答（后续逻辑不变）
#     answer = ollama_chat(
#         st.session_state.model_name,
#         msgs,
#         st.session_state.gen_params,
#     )
#
#     # 知识库二次校验（语言适配提示）
#     if has_kb:
#         try:
#             kb_verify = _run_verify_text_against_kb(answer, hits)
#         except Exception:
#             kb_verify = None
#         if kb_verify and not kb_verify.get("ok", True):
#             reason = kb_verify.get("reason") or (
#                 "This answer is inconsistent with current knowledge evidence or has potential risks."
#                 if lang == "en"
#                 else "该回答与当前知识证据不完全一致，或存在潜在风险。"
#             )
#             safe_reply = (
#                 f"{reason}\n\n"
#                 "For safety reasons, I will not provide more specific or personalized diagnosis, treatment, or medication advice here."
#                 "You can use the above points as background information and prioritize consulting a qualified doctor or nutritionist."
#                 "Especially if you experience persistent discomfort, worsening symptoms, or have underlying diseases, you should seek offline medical attention as soon as possible."
#                 if lang == "en"
#                 else f"{reason}\n\n"
#                 "出于安全考虑，我不会在这里给出更具体或个体化的诊断、治疗或用药建议。"
#                 "你可以把上面的要点当作背景信息，同时优先咨询具备资质的医生或营养师，"
#                 "尤其在出现持续不适、症状加重或存在基础疾病的情况下，应尽快线下就诊。"
#             )
#             answer = safe_reply
#
#     return answer, (hits if has_kb else [])
# def llm_answer_with_kb(
#         user_text: str,
#         intent: str,
#         history: Optional[List[Dict[str, str]]] = None,
# ):
#     """
#     返回 (answer_text, hits)。
#
#     - 命中知识库：要求模型基于证据总结回答，禁止机械复读和“稍后回复”之类的流程话。
#     - 未命中：给通用建议，并说明局限。
#     """
#     hits = retrieve_knowledge(user_text)
#     has_kb = bool(hits)
#
#     msgs: List[Dict[str, str]] = []
#
#     if has_kb:
#         kb_context = build_kb_context(hits)
#         msgs.append({
#             "role": "system",
#             "content": (
#                 "你是 FitForU 的健康与训练助手。\n"
#                 "上面会提供与用户问题相关的内部知识库证据。\n"
#                 "请严格以证据为主要依据回答，要求："
#                 "1) 用自己的话总结要点，结构清晰；"
#                 "2) 不大段粘贴原文，不输出 markdown 标题；"
#                 "3) 不说“我会记录情况/尽快告知”等流程性话术；"
#                 "4) 不给处方药名和具体剂量；"
#                 "5) 证据没有覆盖的部分，只给非常一般性的建议并说明局限。"
#             ),
#         })
#         msgs.append({
#             "role": "system",
#             "content": f"【证据片段】\n{kb_context}",
#         })
#     else:
#         msgs.append({
#             "role": "system",
#             "content": (
#                 "你是 FitForU 的健康与训练助手。"
#                 "当前没有检索到相关内部知识库内容。"
#                 "你可以基于常识给一般性建议，但必须明确说明："
#                 "这些不构成个体化医疗意见，且不能包含处方药或具体剂量。"
#             ),
#         })
#
#     # 最近少量上下文，避免把 meta / 证据展示一类噪音带进去
#     if history:
#         recent = [
#             {"role": m["role"], "content": m["content"]}
#             for m in history[-6:]
#             if m.get("role") in ("user", "assistant")
#         ]
#         msgs.extend(recent)
#
#     if has_kb:
#         user_prompt = (
#             f"请基于上方证据回答我的问题：{user_text}\n"
#             "用 3–6 条要点 + 简洁解释总结，不要直接复制证据原文或输出大字号标题。"
#         )
#     else:
#         user_prompt = user_text
#
#     msgs.append({"role": "user", "content": user_prompt})
#
#     answer = ollama_chat(
#         st.session_state.model_name,
#         msgs,
#         st.session_state.gen_params,
#     )
#
#     # 🔒 基于知识库的二次校验闸：
#     # - 仅当有 KB 命中时启用；
#     # - verify_text_against_kb 判定不安全/不一致时，用保守提示覆盖原回答；
#     # - 任意异常不影响主流程（直接忽略）。
#     if has_kb:
#         try:
#             kb_verify = _run_verify_text_against_kb(answer, hits)
#         except Exception:
#             kb_verify = None
#
#         if kb_verify and not kb_verify.get("ok", True):
#             reason = kb_verify.get("reason") or "该回答与当前知识证据不完全一致，或存在潜在风险。"
#             safe_reply = (
#                 f"{reason}\n\n"
#                 "出于安全考虑，我不会在这里给出更具体或个体化的诊断、治疗或用药建议。"
#                 "你可以把上面的要点当作背景信息，同时优先咨询具备资质的医生或营养师，"
#                 "尤其在出现持续不适、症状加重或存在基础疾病的情况下，应尽快线下就诊。"
#             )
#             answer = safe_reply
#
#     return answer, (hits if has_kb else [])


# ---------------------------------------------------------
# Step 9: Deliver（摘要 / 免责声明 / 日志）
# ---------------------------------------------------------
# def build_plan_summary(draft: Dict[str, Any], profile: Optional[Dict[str, Any]]) -> str:
#     modules = draft.get("modules") or []
#     try:
#         horizon = int(draft.get("horizon_days", 7) or 7)
#     except Exception:
#         horizon = 7
#     plan_types = ", ".join([str(x) for x in (draft.get("plan_types") or [])]) or "未指定"
#
#     # 粗估模块时长
#     total_minutes = 0
#     for m in modules:
#         try:
#             total_minutes += int(m.get("duration_min") or m.get("duration") or 0)
#         except Exception:
#             pass
#     avg_minutes = total_minutes // len(modules) if modules and total_minutes > 0 else 0
#
#     summary = f"已为你生成 {horizon} 天的 {plan_types} 计划，共 {len(modules)} 个模块。"
#     if avg_minutes:
#         summary += f" 平均每个模块约 {avg_minutes} 分钟。"
#
#     # Profile 条件
#     if profile:
#         tw = (profile.get("time_windows") or [{}])[0]
#         label = tw.get("label", "训练时段")
#         start = str(tw.get("start", ""))[:5]
#         end = str(tw.get("end", ""))[:5]
#         days = tw.get("days") or []
#         day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
#         days_str = ",".join([day_names[d - 1] for d in days if 1 <= d <= 7]) or "全周可选"
#         daily_cap = profile.get("max_daily_minutes", 0)
#         if start and end:
#             summary += f" 将优先安排在 {label} {start}–{end}"
#         if days_str:
#             summary += f"（{days_str}）"
#         if daily_cap:
#             summary += f"，每日不超过 {daily_cap} 分钟。"
#
#     disclaimer = (
#         "⚠️ 本计划为自动生成的健康与训练建议，仅供参考，不构成医疗诊断或个性化处方。"
#         "如有基础疾病、近期手术或受伤、持续发烧、胸痛、明显气促等情况，请在执行前先咨询专业医生。"
#     )
#
#     return summary + "\n\n" + disclaimer
def build_plan_summary(
        draft: Dict[str, Any],
        profile: Optional[Dict[str, Any]],
        lang: str = "zh"  # 新增语言参数，默认中文
) -> str:
    # 多语言模板定义
    templates = {
        "zh": {
            "plan_intro": "已为你生成 {horizon} 天的 {plan_types} 计划，共 {module_count} 个模块。",
            "avg_duration": " 平均每个模块约 {avg_minutes} 分钟。",
            "time_window_label": "将优先安排在 {label} {start}–{end}",
            "days_suffix": "（{days_str}）",
            "daily_cap": "，每日不超过 {daily_cap} 分钟。",
            "disclaimer": (
                "⚠️ 本计划为自动生成的健康与训练建议，仅供参考，不构成医疗诊断或个性化处方。"
                "如有基础疾病、近期手术或受伤、持续发烧、胸痛、明显气促等情况，请在执行前先咨询专业医生。"
            ),
            "day_names": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        },
        "en": {
            "plan_intro": "A {horizon}-day {plan_types} plan has been generated, with a total of {module_count} modules.",
            "avg_duration": " Each module averages about {avg_minutes} minutes.",
            "time_window_label": " It will be prioritized in {label} {start}–{end}",
            "days_suffix": " ({days_str})",
            "daily_cap": ", with a maximum of {daily_cap} minutes per day.",
            "disclaimer": (
                "⚠️ This plan is automatically generated health and training advice for reference only, "
                "and does not constitute a medical diagnosis or personalized prescription. "
                "If you have underlying diseases, recent surgery or injury, persistent fever, "
                "chest pain, obvious shortness of breath, etc., please consult a professional doctor before implementation."
            ),
            "day_names": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        }
    }

    # 确保语言参数合法
    lang = lang.lower()
    if lang not in templates:
        lang = "zh"  # 默认为中文
    t = templates[lang]

    modules = draft.get("modules") or []
    try:
        horizon = int(draft.get("horizon_days", 7) or 7)
    except Exception:
        horizon = 7
    plan_types = ", ".join([str(x) for x in (draft.get("plan_types") or [])]) or (
        "未指定" if lang == "zh" else "unspecified")

    # 计算模块时长
    total_minutes = 0
    for m in modules:
        try:
            total_minutes += int(m.get("duration_min") or m.get("duration") or 0)
        except Exception:
            pass
    avg_minutes = total_minutes // len(modules) if modules and total_minutes > 0 else 0

    # 构建基础摘要
    summary = t["plan_intro"].format(
        horizon=horizon,
        plan_types=plan_types,
        module_count=len(modules)
    )
    if avg_minutes:
        summary += t["avg_duration"].format(avg_minutes=avg_minutes)

    # 处理时间窗口和约束（来自profile）
    if profile:
        tw = (profile.get("time_windows") or [{}])[0]
        label = tw.get("label", "训练时段" if lang == "zh" else "training time")
        start = str(tw.get("start", ""))[:5]
        end = str(tw.get("end", ""))[:5]
        days = tw.get("days") or []
        # 转换星期显示（1-7对应周一到周日）
        day_names = t["day_names"]
        days_str = ",".join([
            day_names[d - 1] for d in days
            if 1 <= d <= 7  # 确保索引合法
        ]) or ("全周可选" if lang == "zh" else "all week available")
        daily_cap = profile.get("max_daily_minutes", 0)

        if start and end:
            summary += t["time_window_label"].format(
                label=label,
                start=start,
                end=end
            )
        if days_str:
            summary += t["days_suffix"].format(days_str=days_str)
        if daily_cap:
            summary += t["daily_cap"].format(daily_cap=daily_cap)

    # 添加免责声明
    summary += "\n\n" + t["disclaimer"]

    return summary

def _log_plan_preview(
        user_query: str,
        intent: str,
        conf: float,
        draft: Dict[str, Any],
        preview_id: str,
) -> None:
    """
    记录本次 Plan Preview，方便事后审计 / 复盘。

    除了原始 draft 外，还会附带：
    - 当前模型名 & 生成参数
    - agent_config（计划模式配置）
    - 草案级校验结果概要（ERROR/WARNING/INFO 计数）
    """
    from application.verify import verify_draft  # 避免循环引用，函数内部引入

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)

        # 草案级静态检查概要（不影响主流程）
        try:
            v = verify_draft(draft)
            verify_summary = {
                "ok": bool(v.ok),
                "counts": dict(v.counts),
            }
        except Exception:
            verify_summary = None

        payload = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "preview_id": preview_id,
            "user_query": user_query,
            "intent": intent,
            "confidence": conf,
            "plan_draft": draft,
            # 新增：生成相关信息，方便排查
            "model_name": st.session_state.get("model_name"),
            "gen_params": st.session_state.get("gen_params", {}),
            "agent_config": st.session_state.get("agent_config", {}),
            # 新增：草案校验概要（可选）
            "verify_draft": verify_summary,
            "llm_refined": bool(draft.get("_llm_refined", False)),
        }

        fname = f"plan_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{preview_id}.json"
        (LOG_DIR / fname).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception:
        # 日志失败不影响主流程
        pass


# ---------------------------------------------------------
# CSS
# ---------------------------------------------------------
CSS = """
<style>
:root{
  --bg:#fffdf8;
  --panel:#fff7ed;
  --text:#111827;
  --muted:#6b7280;
  --border:#f5e7dd;
  --accent:#f97316;
  --ok:#22c55e;
  --chip:#fef3c7;
}

/* 基础背景 & 文本色 */
html, body, [class^="stApp"]{
  background:var(--bg) !important;
  color:var(--text) !important;
}

/* 清理多余分隔线/空块 */
hr,
div[role="separator"],
.stDivider{
  display:none !important;
}
.input-shell:empty{
  display:none !important;
  border:none !important;
  padding:0 !important;
  height:0 !important;
}
.main .block-container > div:empty{
  display:none !important;
}
.main .block-container > div:has(hr){
  display:none !important;
}
.stMarkdown p:empty{
  display:none !important;
}

/* ===== 聊天气泡 ===== */
.chat-bubble{
  padding:.9rem 1rem;
  border:1px solid var(--border);
  border-radius:12px;
  background:#fff;
  font-size:14px;
  line-height:1.7;
}
.chat-bubble.user{
  background:#f1f6ff;
  border-color:#dfe7ff;
}
div.stChatMessage:has(div.chat-bubble.user) {
    padding: 16px 0px 16px 16px !important;
    background: transparent !important;
}

/* ===== 固定底部输入区 ===== */
.fixed-footer{
  position:fixed;
  left:0;
  right:0;
  bottom:0;
  z-index:998;
  background:linear-gradient(to top, rgba(255,247,237,0.98), rgba(255,253,248,0.96));
  backdrop-filter:blur(12px);
  padding:14px 0 22px;
}

.footer-inner{
  max-width:960px;
  margin:0 auto;
  display:flex;
  align-items:flex-end;
  gap:14px;
}

/* 输入框外壳 */
.input-shell{
  min-height: 72px !important; /* <-- 2. 设置最小高度（保持外观）*/
  height: auto !important;     /* <-- 3. 允许高度随内容自动增长 */
  border:1px solid var(--border) !important;
  border-radius:22px !important;
  background:#f9fafb !important;
  display:flex !important;
  align-items:flex-start !important;
  padding:10px 16px !important;
  box-sizing:border-box !important;
  box-shadow:0 10px 26px rgba(15,23,42,0.10);
}

/* 状态 pill */
.status-pill{
  height:40px !important;
  min-width:160px;
  padding:0 18px !important;
  border-radius:22px !important;
  display:flex !important;
  align-items:center !important;
  justify-content:center !important;
  font-size:13px !important;
  font-weight:500;
  box-shadow:0 8px 22px rgba(15,23,42,0.08);
}
.status-on{
  background:#dcfce7 !important;
  border:1px solid #bbf7d0 !important;
  color:#166534 !important;
}
.status-off{
  background:#f9fafb !important;
  border:1px solid var(--border) !important;
  color:#6b7280 !important;
}

/* TextInput 去边框，适配自定义外壳 */
div.stTextInput > div > div{
  border:none !important;
  box-shadow:none !important;
  background:transparent !important;
}
div.stTextInput > div > input{
  height:52px !important;
  border:none !important;
  box-shadow:none !important;
  background:transparent !important;
  border-radius:16px !important;
  padding-left:4px !important;
  font-size:15px !important;
  color:var(--text) !important;
}

/* TextArea 去边框，适配自定义外壳 */
[data-testid="stTextArea"] > div > div {
  border:none !important;
  box-shadow:none !important;
  background:transparent !important;
}

/* TextArea 内部样式 (使用 data-testid) */
[data-testid="stTextArea"] textarea {

  /* === 自动增长的核心配置 === */



  /* 2. 设置最小高度 (匹配原外观) */
  min-height: 52px !important;

  /* 3. 设置最大高度 (例如 200px，约 5 行，防止无限增高) */
  max-height: 400px !important;

  /* 4. 关键：让输入框根据内容自动调整大小 */
  field-sizing: content !important;

  /* 5. 保持禁止用户手动拖拽 */
  resize: none !important; 

  /* === (原有的样式，保持不变) === */
  border:none !important;
  box-shadow:none !important;
  background:transparent !important;
  border-radius:16px !important;
  padding-left:4px !important;
  font-size:15px !important;
  color:var(--text) !important;
  white-space: pre-wrap !important; 
  overflow-wrap: break-word !important;
}
.input-shell > [data-testid="stForm"] {
    width: 100% !important;
    /* * 关键：
     * 1. 让表单本身也成为 flex 容器。
     * 2. 它的高度将由它的子元素 (textarea) 决定。
     */
    display: flex !important;
    flex-direction: column !important;
    flex-grow: 1 !important;
}

/* 左侧 + 按钮 */
div[data-testid="stPopover"] {
  height: 40px !important;
  width: 100% !important;
  margin: 0 !important; 
  padding: 0 !important;
}

/* Trigger button *inside* the st.popover */
div[data-testid="stPopover"] > button {
  width:100% !important;
  height:100% !important;
  margin:0 !important;
  border-radius:22px !important;
  border:none !important;
  background:#fef3c7 !important;
  display:flex !important;
  align-items:center !important;
  justify-content:center !important;
  font-size:26px !important;
  font-weight:700 !important;
  color:#92400e !important;
  box-shadow:0 6px 16px rgba(251,191,36,0.45) !important;
}

/* Keep the fix for the status pill's wrapper */
div[data-testid="stMarkdown"]:has(> div.status-pill){
  margin:0 !important;
  padding:0 !important;
}

/* 意图 Chip */
.intent-chip{
  display:inline-flex;
  gap:8px;
  align-items:center;
  background:#eef2ff;
  color:#334155;
  border:1px solid #dbe2ff;
  padding:6px 10px;
  border-radius:999px;
  font-size:12px;
  font-weight:600;
  margin:6px 0 2px 0;
}

/* 计划卡片 & badge */
.plan-card{
  border:1px solid var(--border);
  border-radius:14px;
  background:#fff;
  padding:14px;
  margin:8px 0 14px 0;
}
.plan-meta{
  display:flex;
  gap:8px;
  flex-wrap:wrap;
  margin-bottom:8px;
}
.badge{
  padding:4px 8px;
  border-radius:999px;
  background:#f1f5f9;
  font-size:12px;
  border:1px solid #e2e8f0;
}

div[data-testid="stFormSubmitButton"]{
  display:none;
}

/* 底部 spacer，避免内容被 footer 挡住 */
.spacer-below{
  height:120px;
}
.spacer-below-empty{
  height: 50px;
}

/* ===== Sidebar 基础 ===== */
[data-testid="stSidebar"]{
  background:transparent !important;
}
[data-testid="stSidebar"] .block-container{
  padding:18px 14px 24px !important;
}
[data-testid="stSidebar"] hr {
    display: block !important;
    margin: 2rem 0; /* (可选) 添加一些上下间距 */
}

/* 侧栏标题 label */
.side-label{
  display:flex !important;
  align-items:center !important;
  gap:8px !important;
  width:100% !important;
  box-sizing:border-box !important;
  padding:10px 14px !important;
  margin:10px 0 6px !important;
  font-size:15px;
  font-weight:600;
  color:#111827;
  background:#fff;
  border-radius:14px;
  border:1px solid #f3e7da;
  box-shadow:0 4px 10px rgba(148,81,35,0.06);
}
.side-label .icon{
  width:20px;
  height:20px;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:16px;
}

/* 连接状态 pill */
.side-pill{
  display:flex;
  align-items:center;
  gap:6px;
  padding:8px 12px;
  margin:4px 0 10px;
  width:100% !important;
  box-sizing:border-box;
  border-radius:999px;
  font-size:11px;
  background:#e0fbe5;
  color:#166534;
  box-shadow:0 3px 8px rgba(22,101,52,0.16);
}

/* 侧栏按钮 */
[data-testid="stSidebar"] button[kind="secondary"],
[data-testid="stSidebar"] button[kind="primary"]{
  border-radius:999px !important;
  font-size:12px !important;
  padding:6px 10px !important;
  box-shadow:none !important;
}
/* 定义侧边栏中“已激活”历史记录按钮（即 primary 按钮）的颜色 */
[data-testid="stSidebar"] button[kind="primary"] {
  background-color: #d0d2d6 !important; 
  color: #31333f33 !important;            
  border: 1px solid #31333f33 !important; 
}

/* 侧栏文字微调 */
[data-testid="stSidebar"] .stCaption,
[data-testid="stSidebar"] p{
  font-size:13px;
  color:var(--muted);
}

/* ===== Sidebar Sliders（修正版：真实生效） ===== */

/* 滑块标题文字颜色 */
[data-testid="stSidebar"] [data-testid="stSlider"] label,
[data-testid="stSidebar"] [data-testid="stSlider"] span{
  color:#374151 !important;
}


/* 整个 slider 块的上下间距 */
[data-testid="stSidebar"] [data-testid="stSlider"]{
  padding:0 !important;
  margin:6px 0 2px !important;
}

/* 轨道底色：更粗、更圆角 */
[data-testid="stSidebar"] [data-testid="stSlider"] div[data-baseweb="slider"] > div > div{
  height:10px !important;
  border-radius:999px !important;
  background:#eef2f7 !important;
}

/* 已选区间（进度条）：浅橙色，同样加粗 */
[data-testid="stSidebar"] [data-testid="stSlider"] div[data-baseweb="slider"] > div > div > div{
  height:10px !important;
  border-radius:999px !important;
  background:#fed7aa !important;
}

/* 拖动圆点 */
[data-testid="stSidebar"] [data-testid="stSlider"] div[data-baseweb="slider"] [role="slider"]{
  width:18px !important;
  height:18px !important;
  border-radius:999px !important;
  border:none !important;
  background:#fdba74 !important;
  box-shadow:0 3px 8px rgba(253,186,116,.6) !important;
}


/* 刻度条背景透明 */
[data-testid="stSidebar"] [data-testid="stTickBarMin"],
[data-testid="stSidebar"] [data-testid="stTickBarMax"]{
  background:transparent !important;
}

/* ===== Hero 区 ===== */
.hero-wrap{
  max-width:960px;
  margin:32px auto 32px;
  padding:26px 32px 22px;
  border-radius:28px;
  background:linear-gradient(135deg,#fff7ed,#fee2e2);
  box-shadow:0 18px 50px rgba(148,81,35,0.18);
  color:#7c2d12;
}
.hero-main{
  display:flex;
  flex-direction:column;
  align-items:center;
  text-align:center;
  gap:12px;
}
.hero-icon{
  width:56px;
  height:56px;
  border-radius:18px;
  background:rgba(255,255,255,0.96);
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:26px;
  box-shadow:0 4px 14px rgba(0,0,0,0.08);
}
.hero-title{
  font-size:28px;
  font-weight:700;
  color:#111827;
  letter-spacing:0.02em;
}
.hero-sub{
  font-size:14px;
  color:#374151;
  line-height:1.8;
  max-width:640px;
}
.hero-tip{
  margin-top:14px;
  font-size:12px;
  color:#6b7280;
  text-align:center;
}
.hero-tip code{
  display:inline-block; 
  padding:6px 12px;
  border-radius:999px;
  background:#111827;
  color:#f9fafb;
  font-size:11px;
}
.hero-tip-container-flex {
  display: inline-flex; /* 允许这个组被 text-align:center 居中 */
  align-items: flex-start; /* 顶部对齐 */
  gap: 12px; /* <-- 这是您要的 "Try:" 和 <code> 之间的间距 */
}

/* "Try:" 标签的样式 */
.hero-tip-label {
  padding-top: 6px; /* 视觉微调，让 "Try:" 文本和 <code> 框顶部对齐 */
}

/* 两个 <code> 框的垂直堆叠容器 */
.hero-tip-stack-flex {
  display: flex;
  flex-direction: column; /* 垂直堆叠 */
  gap: 8px; /* 两个 <code> 框之间的垂直间距 */
}

/* 覆盖堆叠内的 <code> 样式 */
.hero-tip-stack-flex code {
  display: block; /* 确保它们是块级（宽度自适应）*/
  margin-left: 0; /* 保证左对齐 */
}

/* ===== 配置区（Popover） ===== */
.config-title{
  font-size:18px !important;
  font-weight:700 !important;
  color:#111827;
  margin:6px 0 8px !important;
  display:flex;
  align-items:center;
  gap:6px;
}
.config-desc{
  font-size:11px;
  color:var(--muted);
  margin-bottom:8px;
}
.config-card{
  border-radius:14px;
  border:1px solid var(--border);
  padding:10px 10px 8px;
  margin-bottom:10px;
  background:#ffffff;
  box-shadow:0 4px 14px rgba(15,23,42,0.04);
}
.config-inline{
  display:flex;
  gap:8px;
  align-items:center;
  flex-wrap:wrap;
}
.config-tag{
  font-size:10px;
  padding:3px 7px;
  border-radius:999px;
  background:var(--chip);
  color:#9a3412;
}

/* ===== Tabs 风格统一 ===== */
div[data-testid="stTabs"] > div > div{
  gap:6px;
}
div[data-testid="stTabs"] button[role="tab"]{
  padding:4px 10px !important;
  border-radius:999px !important;
  font-size:10px !important;
  color:#6b7280 !important;
  border:none !important;
}
div[data-testid="stTabs"] button[aria-selected="true"]{
  background:#111827 !important;
  color:#f9fafb !important;
}

/* ===== 证据卡片 ===== */
.evidence-card{
  border:1px solid(var(--border));
  border-radius:14px;
  padding:10px 12px;
  margin-top:6px;
  background:#ffffff;
  box-shadow:0 6px 18px rgba(15,23,42,0.06);
  font-size:14px;
  line-height:1.7;
}
.evidence-title{
  font-size:14px;
  font-weight:600;
  color:#111827;
  margin-bottom:2px;
}
.evidence-meta{
  font-size:12px;
  color:var(--muted);
  margin-bottom:4px;
}
.evidence-snippet{
  font-size:14px;
  color:#4b5563;
}
.evidence-sentence{
  font-size:14px;
  font-weight:500;
  margin:8px 0 4px;
  color:#111827;
}

</style>
"""


# ---------------------------------------------------------
# State
# ---------------------------------------------------------
def init_state():
    if "messages" not in st.session_state:
        st.session_state.messages: List[Dict[str, Any]] = []

    # --- 用于存储历史对话 ---
    if "chat_history" not in st.session_state:
        # 结构: { "session_id_str": {"title": str, "messages": List[Dict], "last_updated": str} }
        st.session_state.chat_history: Dict[str, Dict[str, Any]] = {}
    if "active_session_id" not in st.session_state:
        # 追踪当前 st.session_state.messages 对应的是哪条历史记录
        st.session_state.active_session_id: Optional[str] = None

    if "model_name" not in st.session_state:
        st.session_state.model_name = DEFAULT_MODELS[0]
    if "gen_params" not in st.session_state:
        st.session_state.gen_params = {
            "temperature": 0.7,
            "top_p": 0.9,
            "top_k": 40,
            "max_tokens": 2048,
        }
    if "agent_enabled" not in st.session_state:
        st.session_state.agent_enabled = False
    if "agent_config" not in st.session_state:
        st.session_state.agent_config = {
            "horizon_days": 7,
            "plan_types": ["lifestyle"],
            "deterministic": False,
            "seed": 42,
            "llm_coplan": True,  # ✅ 新增：默认开启 LLM 协同
        }

    if "profile" not in st.session_state:
        if HAS_COMPOSER:
            try:
                st.session_state.profile = Profile().as_dict()
            except Exception:
                st.session_state.profile = {
                    "max_daily_minutes": 100,
                    "time_windows": [{
                        "label": "evening",
                        "start": "19:00",
                        "end": "22:00",
                        "days": [1, 2, 3, 4, 5],
                    }],
                }
        else:
            # 即便没有 Composer，也用 dict 承载偏好，方便智能记忆复用
            st.session_state.profile = {
                "max_daily_minutes": 100,
                "time_windows": [{
                    "label": "evening",
                    "start": "19:00",
                    "end": "22:00",
                    "days": [1, 2, 3, 4, 5],
                }],
            }


def _save_current_session(update_timestamp: bool = False):  # 添加参数，默认为 False
    """
    将当前活动会话 (st.session_state.messages) 保存或更新到 chat_history 中。
    """
    messages = st.session_state.get("messages", [])
    if not messages:  # 不保存空对话
        return

    session_id = st.session_state.get("active_session_id")

    # 深度拷贝 messages，确保所有嵌套对象（如 draft）都是独立的
    messages_copy = deepcopy(messages)

    if session_id and session_id in st.session_state.chat_history:
        # 如果是已存在的会话，则更新消息列表
        st.session_state.chat_history[session_id]["messages"] = messages_copy

        # --- 只有在明确要求时才更新时间戳 ---
        if update_timestamp:
            st.session_state.chat_history[session_id]["last_updated"] = datetime.now().isoformat()

    else:
        # 如果是新会话 (active_session_id is None)，则总是创建新条目并设置时间戳
        first_user_message = next((m['content'] for m in messages if m['role'] == 'user'), "New Chat")
        title = first_user_message.split('\n')[0][:40]  # 取第一行，最多40字符

        if any(m.get("type") == "plan_preview" for m in messages):
            title = f"Plan: {title}"

        new_session_id = uuid.uuid4().hex[:10]
        now_iso = datetime.now().isoformat()  # 新会话总是需要时间戳

        st.session_state.chat_history[new_session_id] = {
            "title": title,
            "messages": messages_copy,
            "created_at": now_iso,
            "last_updated": now_iso  # 新会话总是设置 last_updated
        }
        # 将这个新 ID 设为当前活动 ID
        st.session_state.active_session_id = new_session_id


# ---------------------------------------------------------
# Ollama helpers
# ---------------------------------------------------------
def get_ollama_models():
    try:
        r = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=1.2)
        r.raise_for_status()
        data = r.json()
        names = [m.get("name") for m in data.get("models", []) if m.get("name")]
        return names or DEFAULT_MODELS
    except Exception:
        return DEFAULT_MODELS


def ollama_chat(model: str, messages: List[Dict[str, str]], params: Dict[str, Any], json_mode: bool = False) -> str:
    # 防御式复制，避免外面传进来的 dict 被我们改坏
    params = dict(params or {})

    # --- 1) 读取 deterministic / seed ---
    # 优先从 params 里读（用于精确控制某次调用）
    deterministic = bool(params.get("deterministic", False))
    seed = None
    if deterministic:
        try:
            seed = int(params.get("seed", 42))
        except Exception:
            seed = 42

    # --- 2) 基础采样参数 ---
    try:
        temperature = float(params.get("temperature", 0.7))
    except Exception:
        temperature = 0.7
    try:
        top_p = float(params.get("top_p", 0.9))
    except Exception:
        top_p = 0.9
    try:
        top_k = int(params.get("top_k", 40))
    except Exception:
        top_k = 40
    try:
        max_tokens = int(params.get("max_tokens", 1024))
    except Exception:
        max_tokens = 1024

    # --- 3) 确定性模式下强制收紧采样 ---
    # 满足你 checklist 里的要求：temperature=0, top_p=1，并加 seed
    if deterministic:
        temperature = 0.0
        top_p = 1.0

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "num_predict": max_tokens,
        }
    }

    # 如果启用 deterministic，就把 seed 塞进 options（Ollama 支持）
    if deterministic and seed is not None:
        payload["options"]["seed"] = seed

    # 只有明确要求 JSON 的场景才加 format，避免影响普通聊天
    if json_mode:
        payload["format"] = "json"

    try:
        r = requests.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        content = data.get("message", {}).get("content", "")
        return (content or "").strip() or "(空响应)"
    except Exception as e:
        return f"⚠️ 无法连接 Ollama：{e}"


# ---------------------------------------------------------
# Sidebar / Header / Controls
# ---------------------------------------------------------
def render_sidebar():
    st.sidebar.markdown(
        """
        <div style="
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 35px;   
        ">
            <div style="
                font-size: 30px;
                font-weight: 800;
                /* 2. 移除了 background-gradient 和 -webkit-clip 属性 */
                /* 3. 将颜色直接设置为黑色 (使用您CSS变量中的 --text 颜色) */
                color: #111827;
                letter-spacing: -0.5px;
            ">
                FitForU
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    # --- 将“清空”改为“新建对话” ---
    if st.sidebar.button("➕ New Chat", use_container_width=True):
        # 保存当前对话（如果有的话），但不更新时间戳
        _save_current_session(update_timestamp=False)

        # 重置主聊天区
        st.session_state.messages = []
        st.session_state.active_session_id = None
        st.rerun()

    st.sidebar.markdown("##### Chat History")

    if not st.session_state.chat_history:
        st.sidebar.caption("No saved chats yet.")
    else:
        # 按最后更新时间倒序排列
        sorted_history = sorted(
            st.session_state.chat_history.items(),
            key=lambda item: item[1].get("last_updated", item[1].get("created_at", "1970-01-01")),
            reverse=True
        )

        # 为每个历史会话创建一个按钮
        for session_id, session_data in sorted_history:
            title = session_data.get("title", f"Chat {session_id}")

            # 检查这个是否是当前活动的会话
            is_active = (session_id == st.session_state.active_session_id)
            button_type = "primary" if is_active else "secondary"

            if st.sidebar.button(title, key=f"history_{session_id}", use_container_width=True, type=button_type):
                if not is_active:
                    # 1. 保存切换前的当前对话，但不更新时间戳
                    _save_current_session(update_timestamp=False)

                    # 2. 加载被点击的历史对话
                    st.session_state.messages = deepcopy(st.session_state.chat_history[session_id]["messages"])  # 加载副本

                    # 3. 设为活动ID
                    st.session_state.active_session_id = session_id

                    # 4. 刷新页面
                    st.rerun()

    st.sidebar.markdown("---")
    # 在侧边栏底部添加设置按钮
    st.sidebar.markdown('<div style="margin-top: auto; "></div>', unsafe_allow_html=True)

    # 设置按钮（与输入框上方的按钮类似）
    with st.sidebar.expander("⚙️ Settings", expanded=False):
        # ===== 模型 =====
        st.markdown(
            '<div class="side-label"><span class="icon">🧩</span><span>Models</span></div>',
            unsafe_allow_html=True,
        )
        st.session_state.model_name = st.selectbox(
            "Choose model",
            options=get_ollama_models(),
            index=0,
            label_visibility="collapsed",
        )

        try:
            _ = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=1.0)
            conn_html = '<div class="side-pill">🟢 Ollama connected</div>'
        except Exception:
            conn_html = '<div class="side-pill">🟠 Ollama not connected</div>'
        st.markdown(conn_html, unsafe_allow_html=True)
        st.markdown("---")
        # ===== 生成参数 =====
        st.markdown(
            '<div class="side-label" style="margin-top:10px;"><span class="icon">🎛️</span><span>Generation parameter</span></div>',
            unsafe_allow_html=True,
        )
        gp = st.session_state.gen_params
        gp["temperature"] = st.slider(
            "Temperature (Creativity)", 0.0, 2.0, gp["temperature"], 0.05
        )
        gp["top_p"] = st.slider(
            "Top P (Diversity)", 0.0, 1.0, gp["top_p"], 0.05
        )
        gp["top_k"] = st.slider(
            "Top K (Vocabulary)", 1, 100, int(gp["top_k"]), 1
        )
        gp["max_tokens"] = st.slider(
            "Max Tokens (Response length)", 32, 4096, int(gp["max_tokens"]), 32
        )

        # ===== 工具信息（折叠）=====
        with st.expander("🔍 Internal implementation (optional viewing)", expanded=False):
            st.caption(f"Intent router: {ROUTER_IMPL_LABEL}")
            st.caption(f"Planner: {PLANNER_IMPL_LABEL}")
            st.caption(f"Composer: {COMPOSER_IMPL_LABEL}")
            st.caption("Deliver: plan summary + disclaimer + logs/plan_*.json")
        st.markdown("---")

        # ===== 知识库 =====
        st.markdown(
            '<div class="side-label" style="margin-top:10px;"><span class="icon">📚</span><span>Local repository</span></div>',
            unsafe_allow_html=True,
        )

        if "ks_snapshot" not in st.session_state:
            st.session_state["ks_snapshot"] = knowledge_status()
        ks = st.session_state["ks_snapshot"]

        st.caption("Directory: data/knowledge/")
        st.caption(f"Number of files{ks.n_files}")
        if ks.last_scan_ts:
            st.caption(
                f"Recent scan:{datetime.fromtimestamp(ks.last_scan_ts).strftime('%Y-%m-%d %H:%M:%S')}"
            )

        auto_val = st.toggle(
            "Automatically reconstruct when monitoring changes",
            value=st.session_state.get("kb_auto", True),
        )
        st.session_state["kb_auto"] = auto_val

        if st.button("🔄 Rebuild the index immediately", use_container_width=True):
            ks2 = rescan_and_rebuild()
            st.session_state["ks_snapshot"] = ks2
            st.success(f"{ks2.n_files} file(s) rebuilded", icon="✅")
            st.rerun()


def top_header():
    if len(st.session_state.messages) == 0:
        st.markdown(
            """
            <div class="hero-wrap">
              <div class="hero-main">
                <div class="hero-icon">💬</div>
                <div class="hero-title">FitForU Smart Plan & Health Assistant</div>
                <div class="hero-sub">
                  Please describe your goal. I will answer your questions, generate training/diet/recovery plans, and use the local knowledge base to review them for you.
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="hero-tip">
             <div class="hero-tip-container-flex">
              <span class="hero-tip-label">Try:</span>
              <div class="hero-tip-stack-flex">
                <code>Create a 7-day full-body training plan.</code>
                <code>How to distinguish doms with sports injury?</code>
              </div>
             </div>
            </div>
            """,
            unsafe_allow_html=True
        )


def _parse_time_hhmm(s: str, fallback: str = "19:00") -> _time:
    try:
        dt = datetime.strptime((s or fallback)[:5], "%H:%M")
        return _time(dt.hour, dt.minute)
    except Exception:
        dt = datetime.strptime(fallback, "%H:%M")
        return _time(dt.hour, dt.minute)


def render_profile_editor():
    st.markdown(
        '<div class="config-title">👤 Profile (Long-term preference)</div>'
        '<div class="config-desc">I will by default abide by these habits and restrictions when formulating the plan.</div>',
        unsafe_allow_html=True,
    )

    p = dict(st.session_state.get("profile") or {})

    max_daily = int(p.get("max_daily_minutes") or 100)
    max_daily = st.number_input(
        "Daily training duration limit (minutes)",
        min_value=30,
        max_value=300,
        value=max_daily,
        step=5,
    )

    default_avoid = [str(t) for t in (p.get("avoid_tags") or [])]
    avoid_options = sorted(
        set(default_avoid + ["Chest", "Back", "Legs", "Arms", "Shoulders", "Glutes", "Abdominals", "HIIT", "Aerobics"])
    )
    avoid = st.multiselect(
        "The types of training that need to be avoided",
        options=avoid_options,
        default=default_avoid,
    )

    tws = p.get("time_windows") or [
        {"label": "evening", "start": "19:00", "end": "22:00", "days": [1, 2, 3, 4, 5]}
    ]
    tw0 = dict(tws[0])

    label = st.text_input("Preferred time period", value=tw0.get("label", "evening"))

    start_t = _parse_time_hhmm(tw0.get("start", "19:00"))
    end_t = _parse_time_hhmm(tw0.get("end", "22:00"))
    c1, c2 = st.columns(2)
    with c1:
        st_time_start = st.time_input("start time", value=start_t)
    with c2:
        st_time_end = st.time_input("finish time", value=end_t)

    day_options = [(1, "Mon"), (2, "Tue"), (3, "Wed"), (4, "Thu"), (5, "Fri"), (6, "Sat"), (7, "Sun")]
    days_default = tw0.get("days") or [1, 2, 3, 4, 5]
    days_selected_labels = st.multiselect(
        "Trainable Day",
        options=[lab for _, lab in day_options],
        default=[lab for num, lab in day_options if num in days_default],
    )
    inv = {lab: num for num, lab in day_options}
    days_selected = [inv[lab] for lab in days_selected_labels] or [1, 2, 3, 4, 5, 6, 7]

    col_save, col_reset = st.columns(2)
    with col_save:
        if st.button("💾 Save Preferences", use_container_width=True):
            tw0_new = {
                "label": label.strip() or "evening",
                "start": f"{st_time_start.hour:02d}:{st_time_start.minute:02d}",
                "end": f"{st_time_end.hour:02d}:{st_time_end.minute:02d}",
                "days": sorted(days_selected),
            }
            st.session_state.profile = {
                "max_daily_minutes": int(max_daily),
                "avoid_tags": avoid,
                "time_windows": [tw0_new],
            }
            st.toast("Preferences saved.", icon="✅")
    with col_reset:
        if st.button("🧹 Reset", use_container_width=True):
            st.session_state.profile = {
                "max_daily_minutes": 100,
                "avoid_tags": [],
                "time_windows": [
                    {
                        "label": "evening",
                        "start": "19:00",
                        "end": "22:00",
                        "days": [1, 2, 3, 4, 5],
                    }
                ],
            }
            st.toast("Preferences reset.", icon="🧹")

    st.markdown('</div>', unsafe_allow_html=True)

    with st.expander("Current effective configuration (read-only)", expanded=False):
        st.json(st.session_state.get("profile") or {})


def render_agent_controls():
    aconf = st.session_state.agent_config

    st.markdown(
        '<div class="config-title">⚙️ Configurations of Plan Generation</div>'
        '<div class="config-desc">These settings will only affect the subsequent conversations and will not be executed immediately.</div>',
        unsafe_allow_html=True,
    )

    st.checkbox(
        "Activate Plan Generation mode",
        value=st.session_state.agent_enabled,
        key="__tmp_agent_enabled",
    )
    llm_coplan = st.checkbox(
        "Use LLM to collaboratively refine the plan description",
        value=aconf.get("llm_coplan", True),
    )

    c1, c2 = st.columns(2)
    with c1:
        horizon = st.radio(
            "Planning period (days)",
            [3, 7, 14, 30],
            index=[3, 7, 14, 30].index(aconf.get("horizon_days", 7)),
            horizontal=True,
        )
    with c2:
        deterministic = st.checkbox(
            "Fix the random seed (for more stable results)",
            value=aconf.get("deterministic", False),
        )

    plan_types = st.multiselect(
        "Plan type",
        options=["lifestyle", "fitness", "nutrition", "rehab"],
        default=aconf.get("plan_types", ["lifestyle"]),
    )

    seed_val = st.number_input(
        "Random seed",
        min_value=0,
        max_value=2 ** 31 - 1,
        value=int(aconf.get("seed", 42)),
        step=1,
        disabled=not deterministic,
    )

    if st.button("💾 Save configurations", use_container_width=True):
        st.session_state.agent_enabled = bool(st.session_state.__tmp_agent_enabled)
        st.session_state.agent_config.update(
            {
                "horizon_days": int(horizon),
                "plan_types": plan_types,
                "deterministic": bool(deterministic),
                "seed": int(seed_val),
                "llm_coplan": bool(llm_coplan),
            }
        )
        st.toast("Configurations saved.", icon="✅")


# ---------------------------------------------------------
# Chat-first plan preview components (含 Deliver Summary)
# ---------------------------------------------------------
def _fmt_time_windows(tws):
    out = []
    for tw in (tws or []):
        label = str(tw.get("label", "")).strip()
        start = str(tw.get("start", "")).strip()[:5]
        end = str(tw.get("end", "")).strip()[:5]
        piece = f"{label} {start}–{end}".strip()
        out.append(piece if piece else "—")
    return out or ["—"]


def _fmt_tags(tags):
    if isinstance(tags, dict):
        tag_id = tags.get("id") or ""
        why = tags.get("why") or ""
        return ", ".join([t for t in [tag_id] if t]), why
    if isinstance(tags, (list, tuple)):
        ids, whys = [], []
        for t in tags:
            if isinstance(t, dict):
                if t.get("id"):
                    ids.append(str(t["id"]))
                if t.get("why"):
                    whys.append(str(t["why"]))
            else:
                ids.append(str(t))
        return ", ".join(ids), "; ".join(whys)
    if tags:
        return str(tags), ""
    return "", ""


def _esc(s: Any) -> str:
    """用于插入 unsafe_allow_html 的内容前的 HTML 转义。"""
    try:
        return html.escape(str(s), quote=True)
    except Exception:
        return ""


def _esc_br(s: Any) -> str:
    """转义并把换行变成 <br>，用于气泡内多行文本。"""
    return _esc(s).replace("\n", "<br>")


def _clean_kb_snippet(snippet: str, max_len: int = 260) -> str:
    """
    展示给用户看的证据片段：
    - 去掉多余空白
    - 截断长度
    - 先做 HTML 转义，再转义 markdown 特殊符号，避免注入/大标题
    """
    if not snippet:
        return ""
    s = " ".join(str(snippet).strip().split())
    if len(s) > max_len:
        s = s[:max_len] + "..."
    # 先 HTML 转义，防止被当成标签执行
    s = html.escape(s, quote=True)
    # 再做 markdown 特殊符号转义（主要用于非 unsafe_allow_html 场景）
    for ch in ("#", "*", "_", "`"):
        s = s.replace(ch, f"\\{ch}")
    return s


def _profile_badges_html(p: Dict[str, Any]) -> str:
    if not p:
        return ""
    try:
        md = []
        mdm = int(p.get("max_daily_minutes", 0) or 0)
        if mdm:
            md.append(f"<span class='badge'>Daily≤{mdm}min</span>")
        tw = (p.get("time_windows") or [{}])[0]
        if tw:
            label = _esc(tw.get("label", "?"))
            start = _esc(str(tw.get("start", ""))[:5])
            end = _esc(str(tw.get("end", ""))[:5])
            md.append(f"<span class='badge'>Window: {label} {start}–{end}</span>")
            days = tw.get("days") or []
            lab = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            show = ",".join([lab[d - 1] for d in days if 1 <= d <= 7]) or "—"
            md.append(f"<span class='badge'>Days: {show}</span>")
        return " ".join(md)
    except Exception:
        return ""


def _draft_summary_line(draft: Dict[str, Any], profile: Optional[Dict[str, Any]]) -> str:
    # Step 9: 用统一的 Deliver Summary（含免责声明）
    lang = draft.get("language", "zh")  # 从 draft 拿语言，默认中文
    return build_plan_summary(draft, profile,lang)


def _pick_safe_actions_for_export(actions, profile, verify_result=None):
    """
    根据 verify_actions 结果决定是否可导出。
    - verify_result: 可选，外部已经算过就传进来，避免重复计算。
    返回 (safe_actions_or_None, final_verify_result, note)
    """
    from application.verify import verify_actions

    v_orig = verify_result or verify_actions(actions, profile=profile)

    # 原始动作无 ERROR：直接放行
    if getattr(v_orig, "counts", {}).get("ERROR", 0) == 0:
        return actions, v_orig, "✅ The original schedule has been checked and can be directly exported."

    # 尝试使用自动修复版
    fixed = getattr(v_orig, "fixed_actions", None)
    if fixed:
        v_fix = verify_actions(fixed, profile=profile)
        if getattr(v_fix, "counts", {}).get("ERROR", 0) == 0:
            return fixed, v_fix, "✅ There were issues with the original plan, so we have used the automatically repaired version for export."

    # 原始+修复都还有 ERROR：不给导出
    return None, v_orig, "⚠️ The current plan still has ERROR. Exporting has been temporarily disabled. Please make the necessary modifications according to the above prompts."


def _split_sentences(text: str) -> List[str]:
    """
    粗粒度把中文/英文句子切开，用于证据对齐展示。
    """
    if not text:
        return []
    # 按常见句号/问号/感叹号分割，中英文都照顾到
    parts = re.split(r"[。！？!?\.]\s*", text)
    return [p.strip() for p in parts if p.strip()]


def _render_plan_evidence_alignment(draft: Dict[str, Any]) -> None:
    """
    计划摘要 vs 知识库 的对齐视图，前端统一 Tab0/1 风格：
    - Tab 0：整体摘要校验 + 核心证据
    - Tab 1：按句溯源映射到证据片段
    """
    profile_dict = st.session_state.get("profile")
    full_summary = build_plan_summary(draft, profile_dict)

    core = full_summary.split("⚠️", 1)[0].strip()
    if not core:
        return

    sentences = _split_sentences(core)
    if not sentences:
        return

    summary_hits = retrieve_knowledge(core)
    kb_check = _run_verify_text_against_kb(core, summary_hits) if summary_hits else None

    with st.expander("📚 Evidence Alignment", expanded=False):
        tabs = st.tabs(["Abstract verification", "Trace the source sentence"])

        # Tab 0：整体摘要的安全性 & 核心证据
        with tabs[0]:
            if kb_check and not kb_check.get("ok", True):
                reason = kb_check.get(
                    "reason") or "The current plan summary is inconsistent with the local knowledge base or may pose potential risks. Please use it with caution."
                st.warning(reason)
            elif not summary_hits:
                st.caption(
                    "No document fragments directly supporting this summary were found in the local repository. Therefore, this plan is mainly based on general rules for generation.")
            else:
                st.caption("The following are some knowledge base segments that form the basis of this plan summary:")
                for i, h in enumerate(summary_hits[:4], 1):
                    snippet = _clean_kb_snippet(h.get("snippet", ""))
                    fname = _esc(Path(h.get("path", "")).name)
                    score = float(h.get("score", 0.0))
                    st.markdown(
                        f"""
                        <div class="evidence-card">
                            <div class="evidence-title">📚 Abstract evidence {i} · {fname}</div>
                            <div class="evidence-meta">score {score:.3f}</div>
                            <div class="evidence-snippet">{snippet}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        # Tab 1：逐句对齐
        with tabs[1]:
            if not summary_hits:
                st.caption(
                    "Since the overall search did not hit the knowledge base, there are no detailed traceability results available.")
            else:
                any_hit = False
                for idx, sent in enumerate(sentences, 1):
                    hits = retrieve_knowledge(
                        sent,
                        k=3,
                        min_score=0.01,
                        # rel_keep=0.6,
                        max_items=3
                    )
                    if not hits:
                        continue

                    any_hit = True
                    st.markdown(
                        f"<div class='evidence-sentence'>🔹 Sentence {idx}：{_esc(sent)}</div>",
                        unsafe_allow_html=True,
                    )
                    for j, h in enumerate(hits, 1):
                        snippet = _clean_kb_snippet(h.get("snippet", ""))
                        fname = _esc(Path(h.get("path", "")).name)
                        score = float(h.get("score", 0.0))
                        st.markdown(
                            f"""
                            <div class="evidence-card">
                                <div class="evidence-title">📌 Matching segment {j} · {fname}</div>
                                <div class="evidence-meta">score {score:.3f}</div>
                                <div class="evidence-snippet">{snippet}</div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                if not any_hit:
                    st.caption(
                        "There is evidence at the overall level, but no highly relevant segments that can be presented sentence by sentence have been found. These can be manually confirmed based on the evidence provided in the above summary.")


def _render_plan_rationale(draft: Dict[str, Any]) -> None:
    """在预览里展示一段规则化的推荐依据说明（不依赖 LLM）。"""
    plan_types = draft.get("plan_types") or []
    constraints = draft.get("constraints") or {}
    horizon = draft.get("horizon_days") or 7
    max_daily = constraints.get("max_daily_minutes")

    bullets = []

    if "fitness" in plan_types:
        bullets.append(
            "Strength training is carried out in a upper body push / lower body / upper body pull / recovery cycle, reducing the risk of excessive load on the same area over consecutive days.")
    if "nutrition" in plan_types:
        bullets.append(
            "The nutrition module should first record and set the total amount over a period of 1-2 days. Then, the 'dining plate check' should be used to reinforce the structure, rather than presenting a complex menu all at once.")
    if "rehab" in plan_types:
        bullets.append(
            "The rehabilitation module automatically recommends 10-15 minutes of low-impact exercises per day, allowing for movement within an acceptable pain range, and avoiding excessive pulling or straining.")
    if "lifestyle" in plan_types or not plan_types:
        bullets.append(
            "The lifestyle module includes daily activities such as hydrating and light exercise, controlling prolonged sitting, and suggesting simple bedtime relaxation. It prioritizes the adoption of the easiest and most sustainable changes.")
    if max_daily:
        bullets.append(
            f"The total duration for a single day should be kept within approximately {max_daily} minutes to avoid placing an excessive burden on the current system.")

    if not bullets:
        bullets.append(
            "Based on the period and type you have selected, the default arrangement is to prioritize low-risk and easily executable basic habits and training, and gradually increase the intensity.")

    with st.expander("Explanation of the recommendation basis", expanded=False):
        for b in bullets:
            st.markdown(f"- {b}")
        st.caption(
            "The above information is derived from built-in rules and experience-based guidance, and does not constitute individualized medical diagnosis or medication prescriptions.")


def _log_plan_export(
        preview_id: str,
        actions: List[Dict[str, Any]],
        verify_counts: Dict[str, int],
) -> None:
    """
    记录实际导出的安全版 actions。
    注意：只在用户点击下载按钮时调用。
    """
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "preview_id": preview_id,
            "n_actions": len(actions),
            "verify_counts": dict(verify_counts or {}),
        }
        fname = f"plan_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{preview_id}.json"
        (LOG_DIR / fname).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception:
        # 日志失败不影响主流程
        pass


def render_preview_widget(draft: Dict[str, Any], key_prefix: str):
    # 顶部卡片：计划元信息
    override_key = f"edited_draft_{key_prefix}"
    if override_key in st.session_state:
        draft = st.session_state[override_key]

    time_windows = draft.get("time_windows", [])
    constraints = draft.get("constraints", {})
    keywords = draft.get("keywords", [])
    plan_types = draft.get("plan_types", [])
    tw_badges = "".join([
        f"<span class='badge'>{_esc(tw)}</span>"
        for tw in _fmt_time_windows(time_windows)
    ])

    plan_types_html = ", ".join(_esc(str(x)) for x in plan_types) or "—"
    keywords_html = ", ".join(_esc(str(x)) for x in (keywords or [])) or "—"
    constraints_html = _esc(json.dumps(constraints, ensure_ascii=False)) if constraints else "—"

    st.markdown(
        f"""
        <div class="plan-card">
          <div class="plan-meta">
            <span class="badge">LLM Agent Collaborative Planning</span>
            <span class="badge">Model: {_esc(st.session_state.get("model_name", ""))}</span>
            <span class="badge">Plan types: {plan_types_html}</span>
            <span class="badge">Keywords: {keywords_html}</span>
          </div>
          <div><b>Time windows (draft hint):</b> {tw_badges or "—"}</div>
          <div style="margin-top:6px;"><b>Constraints:</b> <code>{constraints_html}</code></div>
        </div>
        """,
        unsafe_allow_html=True
    )

    if draft.get("_llm_refined"):
        st.markdown(
            "<div class='plan-meta'><span class='badge'>✨ The copywriting has been optimized by LLM</span></div>",
            unsafe_allow_html=True
        )

        st.markdown(
            f"<div class='plan-meta' style='margin-top:-4px;'>{_profile_badges_html(st.session_state.get('profile', {}))}</div>",
            unsafe_allow_html=True
        )

    # 计划依据（透明度说明）
    _render_plan_rationale(draft)

    # Tabs: 排程 / 草案 / 验证+导出
    tabs = st.tabs([
        "Schedule",
        "Draft",
        "Verification and Export",
        "Adjustment",
    ])

    # 辅助函数：根据活动内容返回图标和颜色
    def _get_activity_icon_and_color(action: Dict[str, Any]) -> tuple[str, str]:
        title = action.get('title', '').lower()
        tags = [tag.lower() for tag in action.get('tags', [])]

        # 健身相关
        if any(word in title for word in
               ['fitness', 'train', 'weightlifting', 'strength', 'bench press', 'squat', 'haul']) or \
                any(tag in tags for tag in ['fitness', 'gym', 'workout']):
            return "💪", "#ef4444"  # 红色

        # 有氧运动
        if any(word in title for word in ['running', 'aerobics', 'riding', 'swimming', 'skipping']) or \
                any(tag in tags for tag in ['cardio', 'running']):
            return "🏃", "#dc2626"  # 深红色

        # 拉伸恢复
        if any(word in title for word in ['stretch', 'yoga', 'relax', 'recovery']) or \
                any(tag in tags for tag in ['recovery', 'stretch', 'yoga']):
            return "🧘", "#8b5cf6"  # 紫色

        # 营养饮食
        if any(word in title for word in ['diet', 'nutrition', 'meal preparation', 'protein']) or \
                any(tag in tags for tag in ['nutrition', 'diet', 'meal']):
            return "🍎", "#10b981"  # 绿色

        # 生活习惯
        if any(word in title for word in ['moisturizing', 'sleep', 'lifestyle', 'habit']) or \
                any(tag in tags for tag in ['lifestyle', 'habit', 'hydration', 'sleep']):
            return "🌿", "#06b6d4"  # 青色

        # 康复训练
        if any(word in title for word in ['recovery', 'therapy', 'treatment']) or \
                any(tag in tags for tag in ['rehab', 'therapy']):
            return "❤️", "#ec4899"  # 粉色

        # 默认
        return "📝", "#6b7280"  # 灰色

    with tabs[0]:
        start_date = st.date_input("Start date", key=f"{key_prefix}__start_date",
                                   help="The date when the schedule begins")
        actions = _compose_actions(draft, start_date)
        st.markdown("##### 🗓️ Your schedule")

        if not actions:
            st.info("📝 The current draft does not contain any scheduled items.")
        else:
            # 按日期分组
            actions_by_date = {}
            for a in actions:
                date_key = a.get('date', 'Unknown date')
                if date_key not in actions_by_date:
                    actions_by_date[date_key] = []
                actions_by_date[date_key].append(a)

            # 为每个日期创建卡片
            for date_key in sorted(actions_by_date.keys()):
                date_actions = actions_by_date[date_key]

                # 格式化日期显示（如：周一 12月10日）
                try:
                    date_obj = datetime.strptime(date_key, "%Y-%m-%d")
                    weekday = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][
                        date_obj.weekday()]
                    formatted_date = f"{weekday} {date_obj.month}.{date_obj.day}"
                except:
                    formatted_date = date_key

                # 日期标题卡片
                st.markdown(f"""
                    <div style="
                        background: linear-gradient(135deg, #fdb35e 0%, #ffefdc 100%);
                        color: white;
                        padding: 12px 16px;
                        border-radius: 10px;
                        margin: 16px 0 8px 0;
                        font-weight: 600;
                        font-size: 14px;
                    ">
                        📅 {formatted_date}
                    </div>
                    """, unsafe_allow_html=True)

                # 创建两列布局
                cols = st.columns(2)

                for idx, a in enumerate(date_actions):
                    col_idx = idx % 2

                    with cols[col_idx]:
                        # 获取活动类型图标
                        icon, color = _get_activity_icon_and_color(a)

                        title_safe = _esc(a.get('title', 'Untitled activity'))
                        desc_safe = _esc(a.get('desc', "")) if a.get("desc") else ""
                        start_safe = _esc(a.get('start', '--:--'))
                        end_safe = _esc(a.get('end', '--:--'))
                        dur_safe = _esc(a.get('duration_min', 0))

                        card_html = f"""
                            <div style="
                                border: 1px solid {color}20;
                                border-left: 4px solid {color};
                                border-radius: 8px;
                                padding: 14px;
                                margin: 8px 0;
                                background: white;
                                box-shadow: 0 2px 8px rgba(0,0,0,0.06);
                                transition: all 0.2s ease;
                            ">
                                <div style="
                                    display: flex;
                                    align-items: flex-start;
                                    gap: 10px;
                                    margin-bottom: 8px;
                                ">
                                    <div style="
                                        background: {color}15;
                                        color: {color};
                                        width: 32px;
                                        height: 32px;
                                        border-radius: 8px;
                                        display: flex;
                                        align-items: center;
                                        justify-content: center;
                                        font-size: 16px;
                                        flex-shrink: 0;
                                    ">{icon}</div>
                                    <div style="flex: 1;">
                                        <div style="
                                            font-size: 14px;
                                            font-weight: 600;
                                            color: #1a1a1a;
                                            line-height: 1.4;
                                            margin-bottom: 4px;
                                        ">{title_safe}</div>
                                        <div style="
                                            display: flex;
                                            align-items: center;
                                            gap: 8px;
                                            font-size: 12px;
                                            color: #666;
                                        ">
                                            <span>⏰ {start_safe}-{end_safe}</span>
                                            <span>•</span>
                                            <span>🕐 {dur_safe} minutes</span>
                                        </div>
                                    </div>
                                </div>
                                {f'<div style="font-size: 12px; color: #888; line-height: 1.4; margin-top: 8px; padding-left: 42px;">{desc_safe}</div>' if desc_safe else ""}
                            </div>
                        """

                        st.markdown(card_html, unsafe_allow_html=True)

            # 添加计划统计信息
            total_days = len(actions_by_date)
            total_activities = len(actions)
            total_minutes = sum(a.get('duration_min', 0) for a in actions)

            st.markdown("---")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("📆 Planned days", f"{total_days}")
            with col2:
                st.metric("📋 Total events", f"{total_activities}")
            with col3:
                st.metric("⏱️ Total time (min)", f"{total_minutes}")

    with tabs[1]:  # 草案（模块）Tab
        st.markdown("##### 📋 Plan module editing")
        modules = draft.get("modules") or []

        if not modules:
            st.info("🎯 The current plan does not have any editable modules.")
        else:
            edited_modules = []
            for i, m in enumerate(modules, 1):
                # 模块卡片标题
                st.markdown(f"""
                <div style="
                    background: linear-gradient(135deg, #fdb35e 0%, #ffefdc 100%);
                    color: white;
                    padding: 10px 16px;
                    border-radius: 8px;
                    margin: 12px 0 8px 0;
                    font-weight: 600;
                    font-size: 13px;
                ">
                    📝 Module {i}
                </div>
                """, unsafe_allow_html=True)

                col1, col2 = st.columns([0.7, 0.3])

                default_title = m.get("title") or m.get("name") or f"Module {i}"
                default_day = int(m.get("day") or i)
                default_dur = int(m.get("duration_min") or m.get("duration") or 30)

                with col1:
                    # 标题输入框
                    title = st.text_input(
                        "Event",
                        value=default_title,
                        key=f"{key_prefix}_mod_title_{i}",
                        placeholder="Please enter the event name..."
                    )
                    # 描述输入框
                    desc = st.text_area(
                        "Description",
                        value=m.get("desc") or m.get("description") or "",
                        key=f"{key_prefix}_mod_desc_{i}",
                        height=80,
                        placeholder="Please enter the activity description ...(optional)"
                    )

                with col2:
                    # 天数输入
                    day = st.number_input(
                        "Scheduled date",
                        min_value=1,
                        max_value=draft.get("horizon_days", 7),
                        value=default_day,
                        key=f"{key_prefix}_mod_day_{i}",
                    )
                    # 时长输入
                    dur = st.number_input(
                        "Estimated duration (min)",
                        min_value=5,
                        max_value=240,
                        value=default_dur,
                        key=f"{key_prefix}_mod_dur_{i}",
                    )
                    # 保留开关
                    keep = st.toggle(
                        "Keep the module",
                        value=True,
                        key=f"{key_prefix}_mod_keep_{i}",
                    )

                if keep:
                    new_m = dict(m)
                    new_m.update({
                        "title": title.strip() or default_title,
                        "day": int(day),
                        "duration_min": int(dur),
                        "desc": desc.strip(),
                    })
                    edited_modules.append(new_m)

                # 模块分隔线
                if i < len(modules):
                    st.markdown("---")

            # 保存按钮
            if st.button("💾 Save all modifications", key=f"{key_prefix}_save_mods", type="primary"):
                new_draft = dict(draft)
                new_draft["modules"] = edited_modules
                st.session_state[override_key] = new_draft
                st.success("✅ All modifications saved!")
                st.rerun()

    with tabs[2]:  # 验证与导出 Tab
        st.markdown("##### 🔍 Plan verification")

        # 验证状态卡片
        col1, col2, col3 = st.columns(3)

        with col1:
            # 草案级检查
            st.markdown("###### 📄 Draft review")
            v1 = verify_draft(draft)
            if v1.counts['ERROR'] == 0:
                st.success("Pass", icon="✅")
            else:
                st.error(f"{v1.counts['ERROR']} ERROR", icon="❌")

        with col2:
            # 执行级检查
            st.markdown("###### ⚡ 执行检查")
            prof_obj = _get_profile_obj()
            start_date = st.session_state.get(f"{key_prefix}__start_date", _date.today())
            if not isinstance(start_date, _date):
                start_date = _date.today()
            actions = _compose_actions(draft, start_date)
            v2 = verify_actions(actions, profile=prof_obj)
            if v2.counts['ERROR'] == 0:
                st.success("Pass", icon="✅")
            else:
                st.error(f"{v2.counts['ERROR']} ERROR", icon="❌")

        with col3:
            # 导出状态
            st.markdown("###### 📤 Export status")
            safe_actions, v_final, note = _pick_safe_actions_for_export(actions, prof_obj, verify_result=v2)
            if safe_actions is not None:
                # 缓存当前预览对应的基础计划，给 Rolling Replan 用
                st.session_state[f"{key_prefix}_baseline_actions"] = safe_actions
                st.success("Safely exported", icon="✅")
            else:
                st.error("Export not possible", icon="❌")

        # 问题详情（可展开）
        with st.expander("📋 View details", expanded=False):
            if v1.issues:
                st.markdown("**Draft-level issues:**")
                for it in v1.issues:
                    emoji = "❌" if it.level == "ERROR" else "⚠️" if it.level == "WARNING" else "ℹ️"
                    st.markdown(f"{emoji} **{it.level}**: {it.message}")

            if v2.issues:
                st.markdown("**Execution-level issues:**")
                for it in v2.issues:
                    emoji = "❌" if it.level == "ERROR" else "⚠️" if it.level == "WARNING" else "ℹ️"
                    st.markdown(f"{emoji} **{it.level}**: {it.message}")

        # ✅ 在这里插入证据对齐视图
        _render_plan_evidence_alignment(draft)

        # 导出区域
        st.markdown("##### 📤 Plan export")
        if safe_actions is not None:
            cal_ready = _attach_calendar_fields(safe_actions)
            ics_text = to_ics(cal_ready, name="FitForU Plan")
            md_text = to_checklist_md(cal_ready)

            # 导出按钮卡片
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("""
                <div style="
                    border: 2px dashed #e2e8f0;
                    border-radius: 12px;
                    padding: 20px;
                    text-align: center;
                    background: #f8fafc;
                ">
                    <div style="font-size: 48px;">📅</div>
                    <div style="font-weight: 600; margin: 8px 0;">Calendar file</div>
                    <div style="color: #64748b; font-size: 14px;">Import to the mobile calendar application</div>
                </div>
                """, unsafe_allow_html=True)

                clicked_ics = st.download_button(
                    "⬇️ Download .ics file",
                    data=ics_text.encode("utf-8"),
                    file_name=f"fitforu_plan_{key_prefix}.ics",
                    mime="text/calendar",
                    use_container_width=True,
                    key=f"{key_prefix}_dl_ics_safe"
                )

            with col2:
                st.markdown("""
                <div style="
                    border: 2px dashed #e2e8f0;
                    border-radius: 12px;
                    padding: 20px;
                    text-align: center;
                    background: #f8fafc;
                ">
                    <div style="font-size: 48px;">📝</div>
                    <div style="font-weight: 600; margin: 8px 0;">Checklist</div>
                    <div style="color: #64748b; font-size: 14px;">Markdown format - Task list</div>
                </div>
                """, unsafe_allow_html=True)

                clicked_md = st.download_button(
                    "⬇️ Download .md file",
                    data=md_text.encode("utf-8"),
                    file_name=f"plan_checklist_{key_prefix}.md",
                    mime="text/markdown",
                    use_container_width=True,
                    key=f"{key_prefix}_dl_md_safe"
                )

            if clicked_ics or clicked_md:
                _log_plan_export(preview_id=key_prefix, actions=cal_ready, verify_counts=getattr(v_final, "counts", {}))
                _save_plan_version(cal_ready, preview_id=key_prefix)
                st.toast("🎉 Plan exported successfully!", icon="✅")

        else:
            st.warning("⚠️ Please solve the above issues first before attempting to export.")
    with tabs[3]:
        # 4) Rolling Replan（中途调整）——独立 Tab
        st.markdown("#### 🌀 Plan Adjustment")

        # 用于保存本次 Rolling Replan 结果的状态
        state_key = f"{key_prefix}_replan_state"
        if state_key not in st.session_state:
            st.session_state[state_key] = {}

        # 读取最近一次导出的安全版计划
        latest_actions, latest_meta = _load_latest_plan()

        # ① 优先使用当前预览刚生成的计划
        preview_base = st.session_state.get(f"{key_prefix}_baseline_actions")

        if preview_base:
            latest_actions = _normalize_loaded_actions(preview_base)
            latest_meta = {"source": "current_preview"}
        else:
            # ② 回退到最后一次导出的全局计划（兼容老逻辑）
            latest_actions, latest_meta = _load_latest_plan()
            latest_actions = _normalize_loaded_actions(latest_actions)

        if not latest_actions:
            st.info("There are no adjustable plans available at the moment. Please first generate and verify a plan.")
        else:
            # 用 label 展示，内部用 uid 标识
            labels: List[str] = []
            id_map: Dict[str, str] = {}
            for idx, a in enumerate(latest_actions):
                uid = a.get("uid") or f"act-{idx}"
                label = _format_action_label(a)
                labels.append(label)
                id_map[label] = uid

            # 交互区域：标记完成 / 取消 + 新约束
            done_labels = st.multiselect(
                "✅ Completed (unchanged)",
                options=labels,
                key=f"{key_prefix}_re_done",
            )
            cannot_labels = st.multiselect(
                "🚫 Can't do / Want to cancel",
                options=labels,
                key=f"{key_prefix}_re_cannot",
            )
            free_text = st.text_input(
                "New constraints (optional)",
                key=f"{key_prefix}_re_constraints",
            )

            # 点击后仅计算 + 写入 session_state，不在 if 分支里直接渲染下载按钮
            if st.button("Generate the adjusted plan", key=f"{key_prefix}_re_submit"):
                done_ids = [id_map[l] for l in done_labels]
                cannot_ids = [id_map[l] for l in cannot_labels]
                new_constraints = _parse_replan_constraints(free_text)
                # 利用 Risk Guard 解析自然语言约束（例如发烧、受伤等）
                if free_text.strip():
                    gate = _run_one_gate(free_text)
                    if gate:
                        # 高风险：直接拒绝继续排计划，提示就医
                        if gate.get("high"):
                            st.session_state[state_key] = {
                                "error": (
                                    "A possible high-risk situation has been detected (such as fever, chest pain, severe discomfort, etc.)"
                                    "The current training plan cannot be continued or strengthened. Please consult a professional doctor first."
                                )
                            }
                            st.rerun()

                        # CAUTION：把 Gate 给出的约束并进 Rolling Replan 的约束里
                        if gate.get("caution") and gate.get("constraints"):
                            new_constraints = _merge_constraints(
                                new_constraints,
                                gate["constraints"]
                            )

                # 用 profile + 新约束 共同约束（新约束优先）
                merged_constraints = dict(new_constraints)

                prof_obj = _get_profile_obj()
                if prof_obj:
                    prof_dict = _profile_to_dict(prof_obj)
                    base_c = {}
                    if prof_dict.get("max_daily_minutes"):
                        base_c["max_daily_minutes"] = prof_dict["max_daily_minutes"]
                    # profile 的基础约束作为缺省，新约束已在 merged_constraints 中优先生效
                    for k, v in base_c.items():
                        merged_constraints.setdefault(k, v)

                # 按约束重排
                new_actions = _replan_actions(
                    original_actions=latest_actions,
                    done_ids=done_ids,
                    cannot_ids=cannot_ids,
                    new_constraints=merged_constraints,
                )

                if not new_actions:
                    st.session_state[state_key] = {
                        "error": "After adjustment, there are no remaining tasks. Please check your selections or constraints.",
                    }
                else:
                    note = _summarize_replan_changes(
                        done_ids,
                        cannot_ids,
                        original_n=len(latest_actions),
                        new_n=len(new_actions),
                    )

                    # 再跑一遍安全闸
                    safe2, v2, note2 = _pick_safe_actions_for_export(
                        new_actions,
                        prof_obj,
                    )

                    if safe2 is None:
                        st.session_state[state_key] = {
                            "error": "The adjusted plan contains ERROR that cannot be automatically fixed. Please make manual adjustments according to the prompts and try again.",
                            "note": note,
                            "note2": note2,
                        }
                    else:
                        # 生成用于导出的结构与文本
                        cal2 = _attach_calendar_fields(safe2)
                        ics2 = to_ics(cal2, name="FitForU Plan (replan)")
                        md2 = to_checklist_md(cal2)

                        st.session_state[state_key] = {
                            "note": note,
                            "note2": note2,
                            "actions": safe2,
                            "calendar": cal2,
                            "ics": ics2,
                            "md": md2,
                            "verify_counts": getattr(v2, "counts", {}),
                        }

                # 写完状态后重跑一次，让下方预览区立即刷新
                st.rerun()

        # —— 下半部分：基于 session_state 的常驻预览和下载区 ——
        re_state = st.session_state.get(state_key, {})

        if re_state:
            # 有错误信息时展示提示
            if re_state.get("error"):
                if re_state.get("note"):
                    st.markdown(re_state["note"])
                if re_state.get("note2"):
                    st.markdown(re_state["note2"])
                st.warning(re_state["error"])
            # 有合法结果时展示预览 + 下载
            elif re_state.get("actions") and re_state.get("ics") is not None:
                st.markdown(re_state.get("note", ""))
                st.markdown(re_state.get("note2", ""))

                st.markdown("**Adjusted plan preview: **")
                for a in re_state["actions"]:
                    st.markdown(
                        f"- {a.get('date', '—')} "
                        f"{a.get('start', '--:--')}-{a.get('end', '--:--')} · "
                        f"**{a.get('title', '(untitled)')}**"
                    )

                c1, c2 = st.columns(2)
                with c1:
                    dl_ics2 = st.download_button(
                        "⬇️ Download the adjusted calendar (.ics)",
                        data=re_state["ics"].encode("utf-8"),
                        file_name=f"fitforu_plan_replan_{key_prefix}.ics",
                        mime="text/calendar",
                        use_container_width=True,
                        key=f"{key_prefix}_dl_ics_replan",
                    )
                with c2:
                    dl_md2 = st.download_button(
                        "⬇️ Download the adjusted checklist (Markdown)",
                        data=re_state["md"].encode("utf-8"),
                        file_name=f"plan_checklist_replan_{key_prefix}.md",
                        mime="text/markdown",
                        use_container_width=True,
                        key=f"{key_prefix}_dl_md_replan",
                    )

                # 只有当用户真正点击下载时再记录版本与日志
                if dl_ics2 or dl_md2:
                    _save_plan_version(
                        re_state.get("calendar") or _attach_calendar_fields(re_state["actions"]),
                        preview_id=f"{key_prefix}_replan",
                    )
                    _log_plan_export(
                        preview_id=f"{key_prefix}_replan",
                        actions=re_state.get("calendar") or re_state["actions"],
                        verify_counts=re_state.get("verify_counts", {}),
                    )
                    st.success("Rolling Replan version saved.")


# ---------------------------------------------------------
# Chat area
# ---------------------------------------------------------
def render_chat_area():
    for msg in st.session_state.messages:
        role = msg.get("role", "assistant")

        # Intent chip
        if role == "meta":
            raw = msg.get("content", "")
            intent, conf = (raw.split("::") + ["-"])[:2]
            try:
                conf_txt = f"{round(float(conf) * 100)}%"
            except Exception:
                conf_txt = "-"
            st.markdown(
                f'<div class="intent-chip">Stream: {intent} · {conf_txt}</div>',
                unsafe_allow_html=True
            )
            continue

        # plan preview message (含 Step9 summary)
        if msg.get("type") == "plan_preview":
            draft = msg.get("draft") or {}
            draft = _enrich_draft(draft)
            with st.chat_message("assistant"):
                summary = _draft_summary_line(
                    draft,
                    st.session_state.get("profile")
                )
                st.markdown(
                    f'<div class="chat-bubble">{_esc_br(summary)}</div>',
                    unsafe_allow_html=True
                )

                with st.expander("View plan details (schedule / draft / verification and export / adjustment)",
                                 expanded=False):
                    render_preview_widget(draft, key_prefix=msg.get("preview_id", "p0"))
            continue

        if msg.get("type") == "kb_answer":
            ev = msg.get("evidence") or []
            content = msg.get("content", "")

            with st.chat_message("assistant"):
                if ev:
                    labels = ["Summary of Responses"] + [
                        f"Evidence{i + 1}" for i in range(len(ev))
                    ]
                    tabs = st.tabs(labels)

                    # Tab 0：主回答
                    with tabs[0]:
                        safe_answer = _esc_br(content)
                        st.markdown(
                            f"<div class='chat-bubble'>{safe_answer}</div>",
                            unsafe_allow_html=True,
                        )

                    # Tab 1..n：每条证据一个卡片
                    for i, h in enumerate(ev):
                        with tabs[i + 1]:
                            snippet = _clean_kb_snippet(h.get("snippet", ""))
                            score = float(h.get("score", 0.0))
                            fname = _esc(Path(h.get("path", "")).name)

                            st.markdown(
                                f"""
                                <div class="evidence-card">
                                    <div class="evidence-title">📚 Evidence {i + 1} · {fname}</div>
                                    <div class="evidence-meta">Relevance score {score:.3f}</div>
                                    <div class="evidence-snippet">{snippet}</div>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )
                else:
                    # 没证据时退回普通气泡
                    safe_answer = _esc_br(content)
                    st.markdown(
                        f"<div class='chat-bubble'>{safe_answer}</div>",
                        unsafe_allow_html=True,
                    )

            continue

        # 普通聊天消息
        with st.chat_message(role):
            safe = _esc_br(msg.get("content", ""))
            cls = "user" if role == "user" else ""
            st.markdown(
                f'<div class="chat-bubble {cls}">{safe}</div>',
                unsafe_allow_html=True
            )

    if st.session_state.messages and st.session_state.messages[-1].get("role") == "user":

        #
        #
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                # 1) 获取刚发出的用户消息
                text = st.session_state.messages[-1]["content"]

                # 2) Intent Router
                try:
                    raw = route_intent(text)
                except Exception as e:
                    route = {
                        "intent": "HEALTH_PLAN",
                        "confidence": 0.0,
                        "reason": f"router error: {e}",
                    }
                else:
                    route = normalize_route_result(raw)

                intent = (route.get("intent") or "HEALTH_PLAN").upper()
                conf = float(route.get("confidence", 0.0) or 0.0)

                # 3) Risk Guard 一次闸
                gate = _run_one_gate(text)
                st.session_state["last_gate"] = gate  # 存起来给后续 Planner/Act 用

                if gate:
                    # 高风险：直接覆盖为 HIGH_RISK
                    if gate.get("high"):
                        intent = "HIGH_RISK"

                #
                #
                st.session_state.messages.insert(-1, {
                    "role": "meta",
                    "content": f"{intent}::{conf}",
                })

                # 4) 高风险：直接分诊提示，终止自动规划
                if intent == "HIGH_RISK":
                    triage_tip = (
                        "⚠️ A possible high-risk / medical-related issue has been detected.\n\n"
                        "The assistant will not create training plans or provide instructions on medication/dosage."
                        "Please consult a professional doctor as soon as possible or go to the nearest medical institution for treatment."
                        "If you experience acute chest pain, breathing difficulties, severe bleeding, or any signs of unconsciousness, please immediately call the local emergency number.\n"
                    )
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": triage_tip,
                    })
                    _save_current_session(update_timestamp=True)
                    st.rerun()

                # 5) 非高风险情况下：尝试从本轮输入中抽取「长期偏好」，写入 Profile
                if intent != "HIGH_RISK":
                    try:
                        updates = extract_profile_updates_from_text(text)
                    except Exception:
                        updates = {}

                    if updates:
                        old_prof = st.session_state.get("profile", {}) or {}
                        new_prof = merge_profile(old_prof, updates)
                        st.session_state["profile"] = new_prof

                        # 轻量反馈（不刷屏）：提示本次自动记住了什么
                        try:
                            human = _format_profile_updates_for_toast(updates)
                            if human:
                                st.toast(f"Your long-term preferences have been updated:{human}", icon="📝")
                        except Exception:
                            pass

                # 6) 根据「计划生成模式」与 intent 分流
                agent_on = bool(st.session_state.agent_enabled)

                # 公共：构造对话历史（仅 user/assistant）
                history = [
                    {"role": m.get("role"), "content": m.get("content")}
                    for m in st.session_state.messages
                    if m.get("role") in ("user", "assistant")
                ]

                # ---------- A. 未开启计划生成模式：全部走对话，不出计划 ----------
                if not agent_on:
                    if intent == "SMALL_TALK":
                        # 纯闲聊：不给知识库添堵
                        reply = ollama_chat(
                            st.session_state.model_name,
                            history,
                            st.session_state.gen_params,
                        )
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": reply,
                        })
                        _save_current_session(update_timestamp=True)
                        st.rerun()
                    else:
                        # 其他情况：统一尝试「知识库 + LLM」问答
                        answer, hits = llm_answer_with_kb(text, intent, history)
                        msg = {
                            "role": "assistant",
                            "content": answer,
                        }
                        if hits:
                            msg["type"] = "kb_answer"
                            msg["evidence"] = hits
                        st.session_state.messages.append(msg)
                        _save_current_session(update_timestamp=True)
                        st.rerun()

                # ---------- B. 开启计划生成模式 ----------
                else:
                    # 是否为“明确要我生成计划”的请求
                    explicit_plan = is_explicit_plan_request(
                        text,
                        intent,
                        st.session_state.messages,
                    )

                    # 1) 同时满足：计划模式已开启 + 显式要计划 + 意图属于可计划类 → 才生成计划
                    if explicit_plan and intent in ALLOWED_PLAN_INTENTS:
                        cfg = dict(st.session_state.agent_config)

                        if not cfg.get("plan_types"):
                            if intent == "FITNESS_GYM":
                                cfg["plan_types"] = ["fitness"]
                            elif intent == "NUTRITION":
                                cfg["plan_types"] = ["nutrition"]
                            elif intent == "REHAB":
                                cfg["plan_types"] = ["rehab"]
                            else:
                                cfg["plan_types"] = ["lifestyle"]

                        memory = {
                            "profile": st.session_state.get("profile") or {},
                        }

                        plan_obj = draft_plan(
                            user_input=text,
                            agent_config=cfg,
                            memory=memory,
                        )
                        base_draft = _enrich_draft(normalize_draft(plan_obj))

                        plan_gen_params = dict(st.session_state.gen_params)
                        if cfg.get("deterministic"):
                            plan_gen_params["deterministic"] = True
                            try:
                                plan_gen_params["seed"] = int(cfg.get("seed", 42))
                            except Exception:
                                plan_gen_params["seed"] = 42

                        # ✅ 只有在开启 llm_coplan 时才调用 LLM 润色
                        if cfg.get("llm_coplan", True):
                            refined = refine_plan_texts_with_llm(
                                base_draft,
                                user_text=text,
                                model_name=st.session_state.model_name,
                                gen_params=plan_gen_params,
                            )
                        else:
                            refined = base_draft

                        # 安全兜底
                        try:
                            v = verify_draft(refined)
                            if v.ok:
                                norm = refined
                            else:
                                norm = base_draft
                        except Exception:
                            norm = refined or base_draft

                        gate = st.session_state.get("last_gate") or {}
                        if gate and gate.get("level") == "CAUTION":
                            gc = gate.get("constraints") or {}
                            if gc:
                                c0 = dict((norm.get("constraints") or {}))
                                norm["constraints"] = _merge_constraints(c0, gc)

                        preview_id = uuid.uuid4().hex[:8]

                        st.session_state.messages.append({
                            "role": "assistant",
                            "type": "plan_preview",
                            "preview_id": preview_id,
                            "draft": norm,
                        })

                        _log_plan_preview(
                            user_query=text,
                            intent=intent,
                            conf=conf,
                            draft=norm,
                            preview_id=preview_id,
                        )

                        _save_current_session(update_timestamp=True)
                        st.rerun()


                    # 2) SMALL_TALK：即使开着计划模式，也只是聊天
                    elif intent == "SMALL_TALK":
                        reply = ollama_chat(
                            st.session_state.model_name,
                            history,
                            st.session_state.gen_params,
                        )
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": reply,
                        })
                        _save_current_session(update_timestamp=True)
                        st.rerun()

                    # 3) 健康相关问答：
                    #    - intent 是 HEALTH_QA
                    #    - 或 intent 在 ALLOWED_PLAN_INTENTS 但没有显式要计划
                    #    → 一律走 KB+LLM 问答，不强行出计划
                    elif intent in {"HEALTH_QA"} or (intent in ALLOWED_PLAN_INTENTS and not explicit_plan):
                        answer, hits = llm_answer_with_kb(text, intent, history)
                        msg = {
                            "role": "assistant",
                            "content": answer,
                        }
                        if hits:
                            msg["type"] = "kb_answer"
                            msg["evidence"] = hits
                        st.session_state.messages.append(msg)
                        _save_current_session(update_timestamp=True)
                        st.rerun()

                    # 4) 其它意图：尝试 KB+LLM，作为安全兜底
                    else:
                        answer, hits = llm_answer_with_kb(text, intent, history)
                        msg = {
                            "role": "assistant",
                            "content": answer,
                        }
                        if hits:
                            msg["type"] = "kb_answer"
                            msg["evidence"] = hits
                        st.session_state.messages.append(msg)
                        _save_current_session(update_timestamp=True)
                        st.rerun()

    #
    # -----------------------------------------------------------------

    if st.session_state.messages:
        # 120px spacer for chat history
        st.markdown('<div class="spacer-below"></div>', unsafe_allow_html=True)
    else:
        # 32px spacer for empty state (hero/<code>)
        st.markdown('<div class="spacer-below-empty"></div>', unsafe_allow_html=True)


# ---------------------------------------------------------
# Fixed input footer
# ---------------------------------------------------------
def _merge_constraints(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """偏保守合并约束：取更严格的那一侧，同时保留所有未知但可能有用的字段。"""
    base = dict(base or {})
    extra = dict(extra or {})

    # 1) 已知字段做“更严格”合并

    # max_daily_minutes: 取更小
    if "max_daily_minutes" in extra:
        try:
            em = int(extra["max_daily_minutes"])
            bm = int(base.get("max_daily_minutes", 0) or 0)
            base["max_daily_minutes"] = em if not bm else min(bm, em)
        except Exception:
            pass

    # postpone_days: 取更大
    if "postpone_days" in extra:
        try:
            ep = int(extra["postpone_days"])
            bp = int(base.get("postpone_days", 0) or 0)
            base["postpone_days"] = max(bp, ep)
        except Exception:
            pass

    # rpe_max: 取更小
    if "rpe_max" in extra:
        try:
            er = int(extra["rpe_max"])
            br = int(base.get("rpe_max", 0) or 0)
            base["rpe_max"] = er if not br else min(br, er)
        except Exception:
            pass

    # avoid_tags: 合并去重
    if "avoid_tags" in extra:
        merged = []
        seen = set()
        for t in (base.get("avoid_tags") or []) + (extra.get("avoid_tags") or []):
            s = str(t).strip()
            if not s:
                continue
            k = s.lower()
            if k not in seen:
                seen.add(k)
                merged.append(s)
        if merged:
            base["avoid_tags"] = merged

    # 2) 兜底：把其他没特别处理的字段全部并进去（新约束优先）
    for k, v in extra.items():
        if k not in base:
            base[k] = v

    return base


def render_fixed_footer():
    # 开启 footer，设置 2 行垂直布局 (column)
    st.markdown(
        '<div class="fixed-footer"><div class="footer-inner" style="flex-direction: column; align-items: stretch; gap: 8px;">',
        unsafe_allow_html=True
    )

    # --- 📌 Row 1: Controls (Button + Status) ---

    c_controls, c_empty = st.columns([0.3, 0.7])

    with c_controls:
        c_plus, c_status = st.columns([1, 2])  # 1:2 比例

        with c_plus:
            # st.markdown('<div id="plus-sentinel"></div>', unsafe_allow_html=True)
            if hasattr(st, "popover"):
                with st.popover("＋", use_container_width=True):
                    st.caption("The configuration items are merely saved and will not be executed immediately.")
                    render_agent_controls()
                    render_profile_editor()
            else:
                st.button("＋", use_container_width=True)

        with c_status:
            cls = "status-on" if st.session_state.agent_enabled else "status-off"
            txt = "Plan Generation mode activated" if st.session_state.agent_enabled else "Plan Generation mode not activated"
            st.markdown(
                f'<div class="status-pill {cls}">{txt}</div>',
                unsafe_allow_html=True
            )

    st.markdown('<div class="input-shell">', unsafe_allow_html=True)

    with st.form(key="chat_form", clear_on_submit=True):
        user_text = st.text_area(
            "Ask any question",
            value="",
            placeholder="Please enter your question...",
            label_visibility="collapsed",

        )
        submitted = st.form_submit_button("Send")

        if submitted and user_text.strip():
            text = user_text.strip()

            # 1) 只追加用户消息
            st.session_state.messages.append({
                "role": "user",
                "content": text,
            })

            # 2) 立即重跑
            # 这将导致 render_chat_area 立即显示用户的消息
            # 并在 render_chat_area 的末尾触发助手思考逻辑

            # 保存当前会话（包含刚发的用户消息），但不更新时间戳
            # （时间戳将在助手回复后再更新，以确保会话排序正确）
            _save_current_session(update_timestamp=False)
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)  # <-- 结束 input-shell

    # --- 结束 footer-inner 和 fixed-footer ---
    st.markdown('</div></div>', unsafe_allow_html=True)


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------
def main():
    st.set_page_config(
        page_title="FitForU",
        page_icon="💬",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    st.markdown(CSS, unsafe_allow_html=True)
    init_state()

    # 初始化 / 自动构建知识库索引（Step 7）
    _ = get_retriever_autoload(
        autobuild=st.session_state.get("kb_auto", True),
        cooldown_sec=20,
    )

    render_sidebar()
    top_header()
    render_chat_area()
    render_fixed_footer()


if __name__ == "__main__":
    main()