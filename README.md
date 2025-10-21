# Talent Search System - 简化版

这是一个基于AI的人才搜索和招聘系统，前端直接调用后端module，无需复杂的API服务。

## 🏗️ 系统架构

```
├── backend/
│   └── talent_search_module/     # 后端核心模块
│       ├── agents.py             # 智能代理函数（查询解析、搜索执行）
│       ├── schemas.py            # 数据模型定义
│       ├── search.py             # 搜索逻辑
│       ├── utils.py              # 工具函数
│       ├── config.py             # 配置常量
│       └── llm.py                # LLM配置
├── frontend/
│   └── targeted_search.py        # Streamlit前端界面
└── README.md                     # 说明文档
```

## ✨ 功能特性

- 🔍 **智能查询解析**: 使用LLM将自然语言查询转换为结构化搜索参数
- 🎯 **精准人才匹配**: 基于研究领域、学位级别、发表论文等条件筛选
- 📊 **实时搜索结果**: 支持实时搜索和结果展示
- 💻 **现代化前端**: 基于Streamlit的直观用户界面
- 🔄 **优雅降级**: 当后端不可用时自动切换到mock数据模式

## 🚀 快速开始

### 1. 安装依赖

```bash
# 安装后端依赖
cd backend/talent_search_module
pip install -r requirements.txt

# 安装前端依赖
cd ../../frontend
pip install streamlit requests pandas
```

### 2. 启动前端

```bash
cd frontend
streamlit run targeted_search.py
```

前端界面将在 `http://localhost:8501` 启动。

## 📖 使用方法

### 1. 自然语言查询

在搜索框中输入自然语言查询，例如：
- "Find 10 current PhD students working on social simulation with LLMs"
- "Looking for Master's candidates in computer vision with ICLR publications"
- "Need 5 PhD interns working on multi-agent systems in Asia"

### 2. 查询解析预览

系统会自动解析你的查询并显示：
- 目标候选人数量
- 关注年份
- 目标会议/期刊
- 研究关键词
- 学位级别要求
- 其他约束条件

### 3. 参数调整

你可以根据需要调整解析出的参数：
- 修改候选人数量
- 添加/删除年份
- 调整学位级别要求
- 添加额外约束

### 4. 执行搜索

点击"Run Targeted Search"执行实际搜索，系统将返回匹配的候选人列表。

## ⚙️ 配置说明

### 支持的会议/期刊
- **机器学习**: ICLR, ICML, NeurIPS
- **自然语言处理**: ACL, EMNLP, NAACL
- **数据挖掘**: KDD, WWW
- **人工智能**: AAAI, IJCAI
- **计算机视觉**: CVPR, ECCV, ICCV
- **信息检索**: SIGIR

### 支持的学位级别
- PhD, MSc, Master, Graduate
- Undergraduate, Bachelor, Postdoc

### 支持的研究领域
- 大语言模型 (LLM)
- 多智能体系统
- 图神经网络 (GNN)
- 强化学习
- 计算机视觉
- 自然语言处理
- 社交模拟

## 🔧 开发说明

### 添加新的搜索源
1. 在 `search.py` 中实现新的搜索逻辑
2. 在 `agents.py` 中添加相应的关键词映射
3. 更新 `schemas.py` 中的数据结构

### 扩展查询解析能力
1. 在 `agents.py` 中增强 `agent_parse_search_query` 函数
2. 添加新的关键词识别规则
3. 集成LLM进行更智能的查询理解

### 自定义前端界面
1. 修改 `targeted_search.py` 中的UI组件
2. 更新样式和布局

## 🐛 故障排除

### 模块导入失败
- 检查Python路径设置
- 确认所有依赖包已安装
- 查看错误信息中的具体模块名

### 查询解析失败
- 检查查询语句是否清晰明确
- 确认使用了支持的关键词和会议名称
- 查看LLM配置是否正确

### 搜索结果为空
- 检查搜索参数是否过于严格
- 尝试放宽某些约束条件
- 确认搜索关键词的拼写正确

### LLM连接问题
- 检查 `config.py` 中的LLM配置
- 确认API密钥和模型名称正确
- 检查网络连接和防火墙设置

## 📝 注意事项

1. **LLM配置**: 系统使用阿里云通义千问作为默认LLM，请确保API密钥有效
2. **依赖管理**: 建议使用虚拟环境来管理Python依赖
3. **模块路径**: 确保前端能正确找到后端module路径

## 🤝 贡献指南

欢迎提交Issue和Pull Request来改进这个系统！

## �� 许可证

MIT License
