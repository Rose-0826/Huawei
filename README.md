# 雾镇 · 电子血染

> 北京邮电大学第一届人机协作编程大赛 参赛作品
> MVP v0.1 —— 1 名真人 + 5 个 AI agent 的社交推理桌游

**白天公开讨论、提名与投票，夜晚有人下手。谁是混在住客里的凶手？**

## 玩法一览

- 6 人局：1 恶魔 + 1 爪牙 + 4 镇民，真人身份每局随机。
- 恶魔每夜杀人；恶魔被处决且爪牙存活时，爪牙接位，游戏继续。
- 镇民中可能有 1 人被下药，他的一条私下信息是错的。
- 镇民每局 1 次查验：只问“是不是恶魔”，可保密，也可公开“我查过 X”。
- 讨论阶段可密谈：每天 1 次、每局 3 次；正文只进私人日志，但可能被对方在公开场合漏出一句。
- 提名 → 自辩 → 质证 → 投票；严格过半才处决，平票进入加赛，再平票无人出局。
- 真人出局后仍可观战，并保留 1 次亡者票；终局揭晓恶魔、爪牙、传位链与被下药者。
- 右上角「规则」随时可查；「记录」可回看公开与私人日志。

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
http://127.0.0.1:8000/blood
```

根路径 `http://127.0.0.1:8000/` 会 307 跳转到 `/blood`。

接口文档：

```text
http://127.0.0.1:8000/docs
```

`MOCK_LLM=1` 时不会请求真实模型，台词是固定文案，但开局、讨论、提名、自辩、投票、处决、夜晚与胜负结算整条链路都会真实运行。

## 一键启动

`project/` 下提供两个脚本，会自动创建 `.venv`、安装依赖并启动：

```powershell
# Windows PowerShell
cd project
.\start.ps1          # 有 .env 用真实模型，没有则 Mock
.\start.ps1 -Mock    # 强制 Mock
.\start.ps1 -Real    # 强制真实模型，要求 .env 存在
```

```bash
# macOS / Linux / Git Bash
cd project
./start.sh           # 有 .env 用真实模型，没有则 Mock
./start.sh --mock    # 强制 Mock
./start.sh --real    # 强制真实模型，要求 .env 存在
```

打开 `http://127.0.0.1:8000/blood`。

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

测试覆盖阵营模式的边界与越权：凶手身份只返回给真人、出局者不能操作、发言与质证次数上限、投票门槛与平票加赛、亡者票、夜晚目标必填、爪牙不投存活恶魔、模型不可用时模板兜底，以及公开日志与回看日志不泄露秘密。

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

打开 `http://127.0.0.1:8000/blood`（`/` 会跳转到这里）。

真实模型：

```bash
docker run --rm -p 8000:8000 \
  -e MOCK_LLM=0 \
  --env-file project/.env \
  mistvale
```

更完整的部署步骤、裸机部署、换剧本挂载和排障见 [DEPLOY.md](DEPLOY.md)。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 307 跳转到 `/blood` |
| GET | `/blood` | 电子血染页面 |
| POST | `/blood/games` | 开始一局，1 真人 + 5 agent，随机一名凶手 |
| GET | `/blood/games/{game_id}` | 查公开状态 |
| POST | `/blood/games/{game_id}/discuss` | 全体存活 agent 各说一句 |
| POST | `/blood/games/{game_id}/speak` | 真人公开发言，一名 agent 回应 |
| POST | `/blood/games/{game_id}/nominate` | 提名处决目标并触发自辩 |
| POST | `/blood/games/{game_id}/vote` | 全体投票（理由并发生成），含平票加赛、门槛与亡者票 |
| POST | `/blood/games/{game_id}/night` | 夜晚结算，凶手必杀 |
| POST | `/blood/games/{game_id}/confide` | 真人密谈，每天 1 次、每局 3 次 |
| GET | `/blood/games/{game_id}/private-log` | 只给真人的密谈正文 |
| POST | `/blood/games/{game_id}/inspect` | 镇民 1 次查验，可选保密或公开 |
| POST | `/blood/games/{game_id}/advance` | 真人出局后推进观战 |
| POST | `/blood/games/{game_id}/last-words` | 出局后留 1 条遗言 |
| GET | `/blood/games/{game_id}/log` | 回看日志，不含秘密字段 |

凶手身份、队友与私有事实只返回给真人；公开日志和回看日志不含秘密，终局才揭晓凶手。

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
│   │   ├── main.py          FastAPI 适配层、血染路由、静态页挂载
│   │   ├── blood.py         电子血染状态机（讨论/提名/投票/夜晚/胜负）
│   │   ├── blood_ai.py      agent 发言与投票理由生成
│   │   ├── llm.py           唯一网络请求层
│   │   ├── models.py        pydantic 剧本模型
│   │   ├── script_loader.py 加载/校验/概况 CLI
│   │   ├── config.py        血染阈值与模型参数
│   │   └── engine/          预留包（当前仅 __init__.py）
│   ├── data/
│   │   ├── scripts/mistvale-inn.json   剧本《雾镇旅馆》
│   │   └── regression/questions.json  历史回归问题数据
│   ├── tests/               血染、模型、剧本、真模型测试
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