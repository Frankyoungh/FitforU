#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工具函数：将2019.txt文件中的数据转换为huanhuan.json格式
新格式要求：
1. Description内容作为instruction
2. 第一组对话使用instruction作为input
3. 后续对话组使用病人的话作为input，医生的话作为output
4. 每组对话生成一个{"instruction":"", "input":"", "output":""}条目

作者：AI Assistant
日期：2024
"""

import json
import re
import logging
from typing import List, Dict, Any, Optional
import os
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def clean_text(text: str) -> str:
    """
    清理文本，去除多余的空白字符
    
    Args:
        text: 原始文本
        
    Returns:
        清理后的文本
    """
    if not text:
        return ""
    
    # 去除多余的空白字符
    text = re.sub(r'\s+', ' ', text.strip())
    return text

def parse_txt_data(file_path: str) -> List[Dict[str, str]]:
    """
    解析2019.txt文件，按照新格式要求提取对话数据
    
    Args:
        file_path: 2019.txt文件路径
        
    Returns:
        包含对话数据的列表，每个元素包含instruction、input、output字段
        
    Raises:
        FileNotFoundError: 文件不存在
        Exception: 解析过程中的其他错误
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    conversations = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        logger.info(f"成功读取文件，大小: {len(content)} 字符")
        
        # 按id分割数据
        entries = re.split(r'id=\d+', content)[1:]  # 跳过第一个空元素
        
        logger.info(f"找到 {len(entries)} 个数据条目")
        
        for i, entry in enumerate(entries):
            if not entry.strip():
                continue
                
            try:
                # 提取描述部分作为instruction
                description_match = re.search(r'Description\s*\n(.*?)(?=Dialogue|$)', entry, re.DOTALL)
                instruction = ""
                if description_match:
                    instruction = clean_text(description_match.group(1))
                
                # 提取对话部分
                dialogue_match = re.search(r'Dialogue\s*\n(.*?)(?=\nid=|$)', entry, re.DOTALL)
                if not dialogue_match:
                    continue
                    
                dialogue_text = dialogue_match.group(1).strip()
                
                # 解析对话
                dialogue_lines = dialogue_text.split('\n')
                current_speaker = ""
                current_text = ""
                dialogue_parts = []
                
                for line in dialogue_lines:
                    line = line.strip()
                    if not line:
                        continue
                        
                    # 检查是否是说话者标识
                    if line.endswith('：'):
                        # 保存之前的对话
                        if current_speaker and current_text:
                            dialogue_parts.append({
                                "speaker": current_speaker,
                                "text": clean_text(current_text)
                            })
                        
                        current_speaker = line[:-1]  # 去掉冒号
                        current_text = ""
                    else:
                        # 继续当前说话者的文本
                        if current_text:
                            current_text += " " + line
                        else:
                            current_text = line
                
                # 添加最后一个对话
                if current_speaker and current_text:
                    dialogue_parts.append({
                        "speaker": current_speaker,
                        "text": clean_text(current_text)
                    })
                
                # 按照新格式构建对话
                if len(dialogue_parts) >= 2:
                    # 第一组对话：使用instruction作为input
                    if len(dialogue_parts) >= 1:
                        first_dialogue = dialogue_parts[0]
                        conversations.append({
                            "instruction": instruction,
                            "input": instruction,  # 第一组使用instruction作为input
                            "output": f"{first_dialogue['text']}"
                        })
                    
                    # 后续对话组：使用病人的话作为input，医生的话作为output
                    for j in range(1, len(dialogue_parts), 2):
                        if j + 1 < len(dialogue_parts):
                            patient_dialogue = dialogue_parts[j]
                            doctor_dialogue = dialogue_parts[j + 1]
                            
                            # 确保病人和医生的顺序正确
                            if "病人" in patient_dialogue['speaker'] and "医生" in doctor_dialogue['speaker']:
                                conversations.append({
                                    "instruction": instruction,
                                    "input": f"{patient_dialogue['text']}",
                                    "output": f"{doctor_dialogue['text']}"
                                })
                            elif "医生" in patient_dialogue['speaker'] and "病人" in doctor_dialogue['speaker']:
                                conversations.append({
                                    "instruction": instruction,
                                    "input": f"{doctor_dialogue['text']}",
                                    "output": f"{patient_dialogue['text']}"
                                })
                            else:
                                # 如果无法确定角色，按顺序处理
                                conversations.append({
                                    "instruction": instruction,
                                    "input": f"{patient_dialogue['text']}",
                                    "output": f"{doctor_dialogue['text']}"
                                })
                        else:
                            # 处理最后一个单独的对话
                            last_dialogue = dialogue_parts[j]
                            conversations.append({
                                "instruction": instruction,
                                "input": f"{last_dialogue['text']}",
                                "output": ""
                            })
                    
            except Exception as e:
                logger.warning(f"解析第 {i+1} 个条目时出错: {e}")
                continue
        
        logger.info(f"成功解析 {len(conversations)} 个对话")
        return conversations
        
    except Exception as e:
        logger.error(f"解析文件时出错: {e}")
        raise

def convert_to_instruction_format(input_file: str, output_file: str, max_samples: Optional[int] = None):
    """
    将2019.txt文件转换为huanhuan.json格式（新版本）
    
    Args:
        input_file: 输入的2019.txt文件路径
        output_file: 输出的JSON文件路径
        max_samples: 最大样本数量，None表示处理所有样本
        
    Raises:
        FileNotFoundError: 输入文件不存在
        Exception: 转换过程中的其他错误
    """
    logger.info(f"开始处理文件: {input_file}")
    
    # 解析数据
    conversations = parse_txt_data(input_file)
    
    # 限制样本数量
    if max_samples and len(conversations) > max_samples:
        conversations = conversations[:max_samples]
        logger.info(f"限制样本数量为: {max_samples}")
    
    # 确保输出目录存在
    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    
    # 写入JSON文件
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(conversations, f, ensure_ascii=False, indent=4)
        
        logger.info(f"转换完成，输出文件: {output_file}")
        logger.info(f"共处理 {len(conversations)} 个对话")
        
        # 显示前几个样本
        logger.info("\n前3个样本:")
        for i, conv in enumerate(conversations[:3]):
            logger.info(f"\n样本 {i+1}:")
            logger.info(f"Instruction: {conv['instruction']}")
            input_preview = conv['input'][:100] + "..." if len(conv['input']) > 100 else conv['input']
            logger.info(f"Input: {input_preview}")
            logger.info(f"Output: {conv['output']}")
            
    except Exception as e:
        logger.error(f"写入文件时出错: {e}")
        raise

def validate_conversion(input_file: str, output_file: str) -> bool:
    """
    验证转换结果
    
    Args:
        input_file: 原始输入文件
        output_file: 转换后的输出文件
        
    Returns:
        bool: 验证是否通过
    """
    try:
        # 检查输出文件是否存在
        if not os.path.exists(output_file):
            logger.error("输出文件不存在")
            return False
        
        # 读取转换后的数据
        with open(output_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not isinstance(data, list):
            logger.error("输出文件格式错误：不是列表")
            return False
        
        # 检查每个条目的格式
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                logger.error(f"第 {i+1} 个条目格式错误：不是字典")
                return False
            
            required_fields = ['instruction', 'input', 'output']
            for field in required_fields:
                if field not in item:
                    logger.error(f"第 {i+1} 个条目缺少字段: {field}")
                    return False
                
                if not isinstance(item[field], str):
                    logger.error(f"第 {i+1} 个条目的 {field} 字段不是字符串")
                    return False
        
        logger.info(f"验证通过，共 {len(data)} 个条目")
        return True
        
    except Exception as e:
        logger.error(f"验证过程中出错: {e}")
        return False

def main():
    # 文件路径
    input_file = "data/original_data.txt"
    output_file = "data/raw/txt2instruction.json"
    
    try:
        # 执行转换
        convert_to_instruction_format(input_file, output_file)
        
        # 验证结果
        if validate_conversion(input_file, output_file):
            logger.info("转换和验证完成")
        else:
            logger.error("验证失败")
            
    except Exception as e:
        logger.error(f"程序执行出错: {e}")

if __name__ == "__main__":
    main()
