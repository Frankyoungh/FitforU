
### 🚀 模型部署 (deployment)
- **FAST_DEPLOYMENT_GUIDE.md**: 详细的快速部署指南
- **Modelfile.WellnessOne**: Ollama模型配置文件
- **WellnessOne_fast_lora.gguf**: 训练好的LoRA权重文件
- 支持一键部署到Ollama服务

### 📱 Web应用 (application)
- **WellnessOne_web.py**: 基于 Streamlit 的医生角色对话Web界面
- 支持实时对话、参数调节、聊天历史管理
- 提供直观的用户界面和流式对话体验

### 🔌 MCP服务器 (mcp_server)
- **server.py**: MCP (Model Context Protocol) 服务器实现
- 支持对话、模型信息查询、状态检查等功能

##  模型部署-Ollama
###  下载并安装ollama
```bash
curl -fsSL https://ollama.ai/install.sh | sh
```
- 验证安装
```bash
# 检查 Ollama 安装
ollama --version

# 查看帮助信息
ollama --help
```

###  启动Ollma服务
```bash
# 启动 Ollama 服务（需要保持运行）
ollama serve
```

- 验证服务状态
```bash
# 新开终端验证服务状态
curl http://localhost:11434/api/tags
```
- 如果11434端口被占用，可以指定其他端口：
```bash
# 指定端口启动
OLLAMA_HOST=0.0.0.0:11435 ollama serve
```
###拉取基础模型
下载基础模型
```bash
# 检查现有模型
ollama list

# 拉取 Qwen2.5-0.5B 基础模型（项目使用）
ollama pull qwen2.5:0.5b

# 验证基础模型下载成功
ollama list | grep qwen2.5
```

## Web应用
基于Streamlit构建的和AI对话的Web应用，提供友好的用户界面和实时对话功能。支持模型选择、流式对话、连接状态监控、参数调节、对话历史管理等完整功能。

- 安装Streamlit：
```bash
pip install streamlit
```
- 确保Ollama服务运行
```bash
ollama serve
```

- 确保lora微调模型已部署
```bash
ollama list | grep WellnessOne
```
### 基于Streamlit开发Web应用
- 启动Web应用
```bash
streamlit run application/FitForU_web.py
```

- 访问Web界面
```bash
# 浏览器自动打开: http://localhost:8501
```

## agent应用-基于MCP协议集成至Claude Desktop中

***PS：仅支持MacOS和Windows***

### 模块概述
MCP模块解决的问题是为模型提供标准化的工具接口，让外部应用能够通过统一的协议与模型进行交互。通过标准化的MCP协议，将本地部署的医疗咨询模型集成到Claude Desktop中，实现AI助手扩展。
首先，因为MCP服务器需要管理多个工具函数（状态）和处理请求（行为），所以通过FastMCP框架来定义服务器实例。

```python
from mcp.server.fastmcp import FastMCP
```

### 8.2 创建MCP服务器实例
```python
mcp = FastMCP("WellnessOne-chat")

def get_ollama_host() -> str:
    """Get the Ollama host from environment variables"""
    return os.getenv("OLLAMA_HOST", "http://localhost:11434")

def get_model_name() -> str:
    """Get the model name from environment variables"""
    return os.getenv("WELLNESSONE_MODEL", "WellnessOne_fast")

OLLAMA_HOST = get_ollama_host()
MODEL_NAME = get_model_name()
```
- 定义工具函数，通过@mcp.tool()装饰器将普通函数转换为MCP工具。完成基础对话功能和对模型状态的获取
- 通过工具类扩展同一个模型的使用，比如角色扮演对话及诗词互动


### 8.3 使用方式
- 启动方式
```python
# 方式1: 直接运行模块
python -m mcp_server

# 方式2: 运行主文件
python mcp_server/server.py


```
- Claude Desktop配置文件 : `claude_desktop_config.json`
```json
{
  "mcpServers": {
    "WellnessOne-chat": {
      "command": "python",
      "args": ["-m", "mcp_server"],
      "cwd": "README.md",
      "env": {
        "OLLAMA_HOST": "http://localhost:11434",
        "WELLNESSONE_MODEL": "WellnessOne_fast"
      }
    }
  }
}
```