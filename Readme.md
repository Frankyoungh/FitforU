
### 🚀 模型部署 (deployment)
- **FAST_DEPLOYMENT_GUIDE.md**: 详细的快速部署指南
- **Modelfile**: Ollama模型配置文件
- **WellnessOne_fast_lora.gguf**: 训练好的LoRA权重文件
- 支持一键部署到Ollama服务

### 📱 Web应用 (application)
- **FitforU.py**: 基于 Streamlit 的对话Web界面
- 支持实时对话、参数调节、聊天历史管理
- 提供直观的用户界面和流式对话体验

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

### 基于Streamlit开发Web应用
- 启动Web应用
```bash
streamlit run application/FitForU_web.py
```

- 访问Web界面
```bash
# 浏览器自动打开: http://localhost:8501
```

