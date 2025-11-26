# -*- coding: utf-8 -*-
from langdetect import detect, LangDetectException

def detect_language(text: str) -> str:
    """检测文本语言，返回 'zh' 或 'en'"""
    try:
        lang = detect(text)
        return 'zh' if lang.startswith('zh') else 'en'
    except LangDetectException:
        return 'zh'  # 默认为英文