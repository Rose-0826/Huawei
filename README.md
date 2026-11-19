# 雾镇 · AI 原生推理桌游

> 北京邮电大学第一届人机协作编程大赛 参赛作品
> MVP v0.1 —— 单人侦探视角的 AI 推理桌游

**每个 NPC 只知道一部分真相。有人撒谎，有人只是记错了。**

## 最快跑起来（Mock，不需要密钥）

要求：Python 3.10+、pip。

```bash
cd project

python -m venv .venv

# macOS / Linux
source .venv/bin/activate
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# Windows cmd
.venv\Scripts\activate.bat

pip install -r requirements.txt
```

启动：

```bash
# macOS / Linux / Git Bash
MOCK_LLM=1 python -m app.main
```

```powershell
# Windows PowerShell
$env:MOCK_LLM="1"; python -m app.main
```

```bat
:: Windows cmd
set MOCK_LLM=1 && python -m app.main
```

打开：

```text
http://127.0.0.1:8000/
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

`MOCK_LLM=1` 时不会请求真实模型，台词是固定文案，但检索、决策、压力、线索解锁、指认结算整条链路都会真实运行。

## 配置真实模型

在 `project/` 下：

```bash
cp .env.example .env
```

编辑 `project/.env`：

```dotenv
MAAS_API_KEY=你的密钥
MAAS_ENDPOINT=https://api.modelarts-maas.com/v1
MAAS_MODEL=你的模型名
```

`.env` 已在 `.gitignore` 里，不会进仓库。程序读取环境变量的优先级高于 `.env`。

先验证连通：

```bash
cd project
python tools/check_maas.py
```

去掉 `MOCK_LLM=1` 启动，就是真实模型：

```bash
python -m app.main
```

如果当前终端里还留着 `MOCK_LLM=1`，先清掉：

```bash
unset MOCK_LLM
```

```powershell
Remove-Item Env:MOCK_LLM
```

`MAAS_ENDPOINT` 传基础地址即可，例如 `https://api.modelarts-maas.com/v1`；程序会自动补 `/chat/completions`。传完整地址也能用。

## 换一个剧本

剧本是 `project/data/scripts/` 下的 JSON 文件。新增一个文件，例如 `my-story.json`，然后先跑数据校验和概况：

```bash
cd project
python -m app.script_loader --script data/scripts/my-story.json
```

校验通过会打印角色、事实、线索和知识分布；不通过会指出具体条目和字段，例如：

```text
facts[f05].holders: 破案链上的事实必须至少有一个持有者，否则玩家永远挖不出来
```

用环境变量切换剧本：

```bash
# macOS / Linux / Git Bash
SCRIPT_PATH=data/scripts/my-story.json MOCK_LLM=1 python -m app.main
```

```powershell
# Windows PowerShell
$env:SCRIPT_PATH="data/scripts/my-story.json"
$env:MOCK_LLM="1"
python -m app.main
```

剧本必须满足以下硬约束：

- `topic` 只能是 `time / weapon / motive / relation / event`
- `culprit` 必须是真实角色 id
- `solution_path` 中的事实必须存在、至少有一个持有者，且不能空、不能重复
- 每个角色至少持有 5 条事实
- `relations`、`holders`、`belief`、`source_of_error`、`clues.from` 的 id 必须存在
- 有 `belief` 的事实必须填 `source_of_error`

## 测试

默认测试不访问网络，也不调用真实模型：

```bash
cd project
python -m pytest -q
```

当前结果：

```text
177 passed, 1 skipped
```

`tests/test_regression.py` 里有 31 条回归用例，专门固化已经踩过的坑，包括：

- 阿蘅压力 0 被问目击时，回答不能出现书房、出来、袖、灰、23:00
- 周砚青说的是他记错的 23:10，不是客观的 22:45
- 同一张线索对同一 NPC 第二次出示必须 409
- 出示两张线索后，阿蘅必须改口
- 模型不可用时只调用一次就模板兜底
- 物证只对持有者可见、裸中文数字不误判、主题值域非法会被拦

真实模型用例单独标记，默认跳过；只有显式开启才会跑：

```bash
RUN_REAL_MODEL=1 python -m pytest -q -m real_model
```

```powershell
$env:RUN_REAL_MODEL="1"
python -m pytest -q -m real_model
```

需要先配置 `MAAS_*`，否则用例会 skip。

## Docker

根目录有 `Dockerfile`，默认 `MOCK_LLM=1`，不配密钥也能起：

```bash
docker build -t mistvale .
docker run --rm -p 8000:8000 mistvale
```

打开 `http://127.0.0.1:8000/`。

真实模型：

```bash
docker run --rm -p 8000:8000 \
  -e MOCK_LLM=0 \
  --env-file project/.env \
  mistvale
```

更完整的部署步骤、裸机部署、换剧本挂载和排障见 [DEPLOY.md](DEPLOY.md)。

## 五个接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/games` | 开始一局 |
| POST | `/games/{game_id}/ask` | 向某个嫌疑人提问 |
| POST | `/games/{game_id}/clues` | 出示已解锁线索，压力 +0.25 |
| GET | `/games/{game_id}` | 查公开状态 |
| POST | `/games/{game_id}/accuse` | 指认并进入结算 |

对玩家可见的响应不会包含 `culprit`、`secret` 或事实原文；指认结算时才返回真相时间线，漏掉的破案链只返回编号。

## 项目结构

```text
.
├── docs/
│   ├── 00_方案说明.md      产品定位 / 玩法 / 评分映射 / 答辩话术 / 演示脚本
│   ├── 01_技术方案.md      架构 / 数据模型 / 核心算法 / API / 前端 / 部署
│   ├── 02_剧本Schema.md    剧本字段规范 / 校验规则 / 新增剧本流程
│   └── 03_码道开发剧本.md  分 7 段的码道 Prompt，逐段复制执行
├── project/
│   ├── app/
│   │   ├── main.py          FastAPI 适配层、静态页挂载
│   │   ├── game.py          内存局状态机
│   │   ├── llm.py           唯一网络请求层
│   │   ├── models.py        pydantic 剧本模型
│   │   ├── script_loader.py 加载/校验/概况 CLI
│   │   ├── config.py        检索、决策、模型阈值
│   │   └── engine/
│   │       ├── intent.py    关键词意图解析
│   │       ├── retrieval.py 知识边界检索
│   │       ├── policy.py    disclose / evade / lie / unparsed
│   │       ├── composer.py  唯一调用 LLM 的 engine 模块
│   │       └── verifier.py  时间、数字、秘密、长度校验
│   ├── data/
│   │   ├── scripts/mistvale-inn.json   剧本《雾镇旅馆》
│   │   └── regression/questions.json  一致性回归问题
│   ├── tests/               单元测试与回归测试
│   ├── web/                 原生前端
│   ├── tools/check_maas.py  MaaS 连通性自检
│   ├── conftest.py          真模型用例默认跳过
│   ├── pytest.ini
│   ├── requirements.txt
│   └── .env.example
├── proof/ai-trace/          码道使用痕迹（脚本自动导出）
├── video/                   演示视频
├── tools/export_traces.py   会话痕迹导出器
├── README.md
├── DEPLOY.md
├── Dockerfile
└── .dockerignore
```

## 参赛说明

### 开工顺序

1. 读 `docs/00_方案说明.md` 的第 4 节（MVP 范围），确认要做什么、不做什么
2. 读 `docs/02_剧本Schema.md`，理解 `holders` 和 `belief` 这两个字段
3. 打开码道，工程目录选 `project/`
4. 按 `docs/03_码道开发剧本.md` 的第 1 段开始，**一段一段喂，别一次性全给**

### 收尾

```bash
python tools/export_traces.py -o proof/ai-trace
```

### 交付四件套

- [ ] 方案说明（`docs/00` 改造成 PPT）
- [ ] 演示视频（脚本见 `docs/00` 第 7 节）
- [ ] 源码（`project/` + 根 `README.md` / `DEPLOY.md` / `Dockerfile`）
- [ ] 使用痕迹证明（`proof/ai-trace/` + 截图 + git log）
- [ ] 可复现（照着 README / DEPLOY.md / Dockerfile 能跑起来）

## 注意

- 一局存在进程内存里，重启就丢。演示时不要重启服务。
- 用单 worker 跑，不要用 `--workers 2` 或更多；内存状态不会共享。
- 这是演示项目，没有登录鉴权。不要直接暴露到公网。
- 前端没有构建步骤，直接改 `project/web/` 即可。
- `.env`、密钥、虚拟环境都不提交。