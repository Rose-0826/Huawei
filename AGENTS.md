# 工程准则（码道每次对话自动加载）

## 项目

「雾镇」——单人侦探视角的 AI 推理桌游。FastAPI 后端 + 原生前端。
玩家审问 5 个 AI 嫌疑人，每个 NPC 只知道一部分真相，有人撒谎，有人只是记错了。

## 只读文件（禁止修改）

- `docs/**`　方案文档，人来维护
- `project/data/scripts/*.json`　剧本数据，只读不写。需要新剧本由人新增文件
- `AGENTS.md`　本文件

需要改这些文件时，**停下来告诉我原因**，由我决定。

## 技术栈（不得擅自替换）

- Python 3.10+（当前环境 3.10.11）/ FastAPI / pydantic v2
- 前端：原生 HTML + JS + CSS，不引入构建工具
- 存储：MVP 阶段用内存 dict，不引入数据库
- **禁止引入**：LangChain、LangGraph、AutoGen、任何 ORM、任何前端框架、任何需要额外安装的分词库

新增第三方依赖必须先说明理由，并写入 `requirements.txt` 且固定版本号。

## 分层原则（最重要）

```
app/engine/     除 composer.py 外，一律不调用 LLM
app/llm.py      唯一允许发网络请求的地方
app/game.py     局状态机
app/main.py     只做 HTTP 适配，不含业务逻辑
```

- engine 里除 `composer.py` 外必须是**纯函数**：输入对象 → 输出对象，不读全局、不写文件
- 所有阈值（0.25 压力增量、0.9 基础阈值等）抽到 `app/config.py`，不要散落在函数里
- 任何"我不知道"的情况返回空值，由上层处理；**不要用异常做流程控制**

## 代码规范

- 全部函数写类型注解，返回类型必写
- 每个公开函数一行中文 docstring，说清"做什么"，不写"怎么做的"
- 变量名、函数名用英文；注释和 docstring 用中文
- 单行不超过 100 字符
- 不用 `print` 做日志，用 `logging`
- 不写裸 `except:`，不吞异常

## 测试

- 每写完一个模块，**必须**同时写 `tests/test_<module>.py`
- 用 pytest，测试只依赖标准库 + 被测模块
- 测试必须覆盖"边界"和"越权"：例如不持有某条 fact 的 NPC 检索必须返回空
- 交付前跑 `pytest -q`，全绿再说完成

## 版本控制（自己提交，不用等提醒）

- 一个模块做完、测试全绿之后，**自己 `git commit`**，不用问
- 提交信息格式：`<type>: <做了什么>`
  - type 只能是 `feat` / `fix` / `test` / `docs` / `refactor` / `chore`
  - 例：`feat: 剧本数据层，含 7 条交叉引用校验`
- 一句话说清改了什么。**禁止** "update"、"修改"、"优化一下" 这类空话
- 提交前必须 `pytest -q` 全绿；红了不许提交
- 只提交 `project/` 下的代码与测试。`docs/**` 和剧本 JSON 的改动要等我说，别自己 commit
- 绝不提交 `.env`、密钥、`venv/`、`__pycache__/`
- 不要 `push --force`，不要 amend 已经推送的提交
- **只 `commit`，不 `push`**。推送由我自己决定，我说 push 你再推
- 每段结束在汇报里附上 `git log --oneline -3` 的真实输出

## 交互协议（每一轮必须遵守）

1. **先给计划**：动手前用 3–5 行说明你打算改哪些文件、为什么
2. **一次只动一个模块**：不要跨模块顺手重构
3. **改完立刻跑测试**，把真实输出贴出来，不要只说"测试通过"
4. **结束时汇报**：
   ```
   改动文件：…
   执行命令：…
   执行结果：…
   下一步建议：…
   ```
5. 遇到报错先读错误信息再动手，**不要连续盲目重试**；两次改不动就停下来问我
6. 不确定需求就提问，**不要猜着实现**

## 禁止事项

- 不要为了让测试通过而修改测试的断言
- 不要删除已有测试
- 不要在代码里硬编码 API 密钥（走环境变量）
- 不要生成大段注释掉的"备用代码"
- 不要一次性生成多个未验证的模块
- 不要把 `secret` / `culprit` 直接暴露在给玩家的接口返回里

## 目录约定

```
project/
├── app/{main,config,models,script_loader,llm,game}.py
├── app/engine/{intent,retrieval,policy,composer,verifier}.py
├── data/scripts/mistvale-inn.json
├── data/regression/questions.json
├── tests/
├── web/
└── requirements.txt
```
