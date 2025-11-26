#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
格式：{"instruction":"", "input":"", "output":""}
"""

import json
import re
import logging
from typing import List, Dict, Any, Optional
import os
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def clean_text(text: str) -> str:
    """
    Function: 
        清理文本，去除多余的空白字符
    Args:
        text: 原始文本
        
    Returns:
        清理后的文本
    """
    if not text:
        return ""
    
    text = re.sub(r'\s+', ' ', text.strip())
    return text

def parse_text_data(file_path: str) -> List[Dict[str, str]]:
    """
    Function: 
        解析txt文件，提取对话数据
    Args:
        file_path: txt文件路径
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
                # 提取对话部分
                dialogue_match = re.search(r'Dialogue\s*\n(.*?)(?=\nid=|$)', entry, re.DOTALL)
                if not dialogue_match:
                    continue
                    
                dialogue_text = dialogue_match.group(1).strip()
                
                # 提取描述部分作为context
                description_match = re.search(r'Description\s*\n(.*?)(?=Dialogue|$)', entry, re.DOTALL)
                context = ""
                if description_match:
                    context = clean_text(description_match.group(1))
                
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
                            dialogue_parts.append(f"{current_speaker}：{clean_text(current_text)}")
                        
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
                    dialogue_parts.append(f"{current_speaker}：{clean_text(current_text)}")
                
                # 构建对话字符串
                if len(dialogue_parts) >= 2:
                    # 将对话分为instruction和output
                    instruction = dialogue_parts[0]
                    output = dialogue_parts[1]
                    
                    # 如果有更多对话，添加到output中
                    if len(dialogue_parts) > 2:
                        output += "\n" + "\n".join(dialogue_parts[2:])
                    
                    conversations.append({
                        "instruction": instruction,
                        "input": context,  # 使用描述作为input
                        "output": output
                    })
                    
            except Exception as e:
                logger.warning(f"解析第 {i+1} 个条目时出错: {e}")
                continue
        
        logger.info(f"成功解析 {len(conversations)} 个对话")
        return conversations
        
    except Exception as e:
        logger.error(f"解析文件时出错: {e}")
        raise

def convert_to_huanhuan_format(input_file: str, output_file: str, max_samples: Optional[int] = None):
    """
    将2019.txt文件转换为huanhuan.json格式
    
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
    conversations = parse_text_data(input_file)
    
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
        input_file: 原始文件路径
        output_file: 转换后的文件路径
        
    Returns:
        验证是否通过
    """
    try:
        # 检查输出文件是否存在
        if not os.path.exists(output_file):
            logger.error("输出文件不存在")
            return False
        
        # 读取并验证JSON格式
        with open(output_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not isinstance(data, list):
            logger.error("输出文件格式错误：不是列表")
            return False
        
        # 验证每个样本的格式
        for i, item in enumerate(data):
            if not isinstance(item, dict):
                logger.error(f"样本 {i+1} 格式错误：不是字典")
                return False
            
            required_fields = ['instruction', 'input', 'output']
            for field in required_fields:
                if field not in item:
                    logger.error(f"样本 {i+1} 缺少字段: {field}")
                    return False
                
                if not isinstance(item[field], str):
                    logger.error(f"样本 {i+1} 字段 {field} 不是字符串")
                    return False
        
        logger.info(f"验证通过，共 {len(data)} 个样本")
        return True
        
    except Exception as e:
        logger.error(f"验证时出错: {e}")
        return False

def main():
    """主函数"""
    input_file = "data/2019.txt"
    output_file = "data/processed/2019_huanhuan.json"
    
    try:
        # 执行转换
        convert_to_huanhuan_format(input_file, output_file)
        
        # 验证转换结果
        if validate_conversion(input_file, output_file):
            logger.info("转换和验证都成功完成！")
        else:
            logger.error("验证失败！")
            
    except Exception as e:
        logger.error(f"转换失败: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main()) 