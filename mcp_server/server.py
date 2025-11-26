import os
import sys
import json
import requests
from typing import Any, Dict, List, Optional
from datetime import datetime
from mcp.server.fastmcp import FastMCP
from sklearn.exceptions import FitFailedWarning


def get_ollama_host() -> str:
    """Get the Ollama host from environment variables"""
    return os.getenv("OLLAMA_HOST", "http://localhost:11434")

def get_model_name() -> str:
    """Get the model name from environment variables"""
    return os.getenv("Fit_MODEL", "fit")

OLLAMA_HOST = get_ollama_host()
MODEL_NAME = get_model_name()

mcp = FastMCP("Fit-chat")

@mcp.tool()
def chat_with_Fit(message: str, temperature: Optional[float] = 0.7, top_p: Optional[float] = 0.9, top_k: Optional[int] = 40, max_tokens: Optional[int] = 256) -> Dict[str, Any]:
    """与模型进行对话交流
    
    Args:
        message (str): 用户发送给模型的消息
        temperature (Optional[float]): 控制回复的随机性，范围0.1-2.0，默认0.7
        top_p (Optional[float]): 核采样参数，范围0.1-1.0，默认0.9
        top_k (Optional[int]): Top-k采样参数，范围1-100，默认40
        max_tokens (Optional[int]): 最大生成token数，范围50-500，默认256
        
    Returns:
        Dict[str, Any]: 包含模型回复和相关信息的字典
    """
    try:
        # 构建请求数据
        request_data = {
            "model": MODEL_NAME,
            "prompt": message,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "num_predict": max_tokens
            }
        }
        
        # 发送请求到Ollama
        response = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json=request_data,
            timeout=30
        )
        response.raise_for_status()
        
        result = response.json()
        
        return {
            "response": result.get('response', '抱歉，模型暂时无法回应。'),
            "model": MODEL_NAME,
            "timestamp": datetime.now().isoformat(),
            "params": {
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "max_tokens": max_tokens
            },
            "total_duration": result.get('total_duration'),
            "load_duration": result.get('load_duration'),
            "prompt_eval_count": result.get('prompt_eval_count'),
            "eval_count": result.get('eval_count')
        }
        
    except requests.exceptions.RequestException as e:
        return {"error": f"Ollama请求失败: {str(e)}"}
    except Exception as e:
        return {"error": f"对话处理失败: {str(e)}"}

@mcp.tool()
def get_model_info() -> Dict[str, Any]:
    """获取当前模型的信息
    
    Returns:
        Dict[str, Any]: 模型信息，包括名称、大小、修改时间等
    """
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        response.raise_for_status()
        
        data = response.json()
        models = data.get('models', [])
        
        Fit_model = None
        for model in models:
            if MODEL_NAME in model.get('name', ''):
                Fit_model = model
                break
        
        if Fit_model:
            return {
                "name": Fit_model.get('name'),
                "size": Fit_model.get('size'),
                "digest": Fit_model.get('digest'),
                "modified_at": Fit_model.get('modified_at'),
                "details": Fit_model.get('details', {})
            }
        else:
            return {"error": f"未找到模型 {MODEL_NAME}"}
            
    except requests.exceptions.RequestException as e:
        return {"error": f"获取模型信息失败: {str(e)}"}
    except Exception as e:
        return {"error": f"处理失败: {str(e)}"}

@mcp.tool()
def list_available_models() -> Dict[str, Any]:
    """列出Ollama中所有可用的模型
    
    Returns:
        Dict[str, Any]: 包含所有可用模型列表的字典
    """
    try:
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        response.raise_for_status()
        
        data = response.json()
        models = data.get('models', [])
        
        model_list = []
        for model in models:
            model_list.append({
                "name": model.get('name'),
                "size": model.get('size'),
                "modified_at": model.get('modified_at')
            })
        
        return {
            "models": model_list,
            "total_count": len(model_list),
            "current_model": MODEL_NAME
        }
        
    except requests.exceptions.RequestException as e:
        return {"error": f"获取模型列表失败: {str(e)}"}
    except Exception as e:
        return {"error": f"处理失败: {str(e)}"}

@mcp.tool()
def check_ollama_status() -> Dict[str, Any]:
    """检查Ollama服务的运行状态
    
    Returns:
        Dict[str, Any]: Ollama服务状态信息
    """
    try:
        # 检查Ollama是否运行
        response = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            models = data.get('models', [])
            
            # 检查模型是否存在
            Fit_available = any(MODEL_NAME in model.get('name', '') for model in models)
            
            return {
                "status": "running",
                "host": OLLAMA_HOST,
                "model_name": MODEL_NAME,
                "model_available": Fit_available,
                "total_models": len(models),
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "status": "error",
                "error": f"Ollama响应状态码: {response.status_code}",
                "host": OLLAMA_HOST
            }
            
    except requests.exceptions.ConnectionError:
        return {
            "status": "disconnected",
            "error": "无法连接到Ollama服务",
            "host": OLLAMA_HOST,
            "suggestion": "请确保Ollama服务正在运行"
        }
    except requests.exceptions.Timeout:
        return {
            "status": "timeout",
            "error": "连接Ollama服务超时",
            "host": OLLAMA_HOST
        }
    except Exception as e:
        return {
            "status": "error",
            "error": f"检查状态失败: {str(e)}",
            "host": OLLAMA_HOST
        }