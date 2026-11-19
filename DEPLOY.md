# 部署与复现

目标：从一台空机器开始，到浏览器里能打开「雾镇旅馆」。

有两条路：

- 方案 A：Docker，推荐，评委复现最省事。
- 方案 B：裸机 Python，适合不能装 Docker 的机器。

## 方案 A：Docker

### 1. 安装 Docker

Windows / macOS 安装 Docker Desktop；Linux 安装 Docker Engine。

安装后确认：

```bash
docker --version
docker run --rm hello-world
```

第二条能正常输出，说明 Docker 守护进程可用。

### 2. 拿到项目

把整个仓库目录放到机器上。以下命令都在仓库根目录执行，也就是 `Dockerfile` 所在目录。

### 3. 构建镜像

```bash
docker build -t mistvale .
```

首次构建会下载 `python:3.10-slim` 并安装依赖，需要网络。构建完成后镜像默认启用 `MOCK_LLM=1`，不需要任何密钥。

### 4. 启动并打开

```bash
docker run --rm -p 8000:8000 mistvale
```

浏览器打开：

```text
http://127.0.0.1:8000/
```

接口文档：

```text
http://127.0.0.1:8000/docs
```

如果机器不是本机，把 `127.0.0.1` 换成服务器 IP，并确认防火墙 / 云安全组放行 8000。

停止服务：前台运行时按 `Ctrl+C`。

### 5. 使用真实模型

先在宿主机准备 `project/.env`：

```bash
cp project/.env.example project/.env
```

填写：

```dotenv
MAAS_API_KEY=你的密钥
MAAS_ENDPOINT=https://api.modelarts-maas.com/v1
MAAS_MODEL=你的模型名
```

启动：

```bash
docker run --rm -p 8000:8000 \
  -e MOCK_LLM=0 \
  --env-file project/.env \
  mistvale
```

说明：

- 镜像里的 `ENV MOCK_LLM=1` 必须用 `-e MOCK_LLM=0` 覆盖。
- `--env-file` 把 `MAAS_*` 传进容器；`.env` 本身不会被打进镜像。
- 端点可以传基础地址，程序会自动补 `/chat/completions`。

### 6. 容器里换剧本

剧本文件在宿主机 `project/data/scripts/`。挂载单个文件，并设置 `SCRIPT_PATH`：

macOS / Linux：

```bash
docker run --rm -p 8000:8000 \
  -v "$PWD/project/data/scripts/my-story.json:/app/data/scripts/my-story.json:ro" \
  -e SCRIPT_PATH=data/scripts/my-story.json \
  mistvale
```

Windows PowerShell：

```powershell
docker run --rm -p 8000:8000 `
  -v "${PWD}\project\data\scripts\my-story.json:/app/data/scripts/my-story.json:ro" `
  -e SCRIPT_PATH=data/scripts/my-story.json `
  mistvale
```

`SCRIPT_PATH` 相对于容器工作目录 `/app`。

先校验剧本：

```bash
cd project
python -m app.script_loader --script data/scripts/my-story.json
```

### 7. 清理

前台按 `Ctrl+C` 后，容器会随 `--rm` 自动删除。需要删镜像时：

```bash
docker rmi mistvale
```

## 方案 B：裸机 Python

要求：Python 3.10+、pip、能访问 MaaS 的网络。

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

### 安装依赖

```bash
cd project
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Windows 激活方式：

```powershell
.\.venv\Scripts\Activate.ps1
```

或 cmd：

```bat
.venv\Scripts\activate.bat
```

### 本地启动（仅本机访问）

```bash
MOCK_LLM=1 python -m app.main
```

打开 `http://127.0.0.1:8000/`。

### 服务器启动（外部浏览器访问）

`python -m app.main` 默认绑定 `127.0.0.1`，远程访问需要显式绑定 `0.0.0.0`：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

然后放行防火墙 / 云安全组的 8000 端口，用浏览器打开：

```text
http://服务器IP:8000/
```

### 真实模型

```bash
cd project
cp .env.example .env
```

填写 `MAAS_*` 后：

```bash
python tools/check_maas.py
python -m app.main
```

或：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

程序会读取 `project/.env`；同名环境变量优先。

### 裸机换剧本

```bash
cd project
python -m app.script_loader --script data/scripts/my-story.json
SCRIPT_PATH=data/scripts/my-story.json MOCK_LLM=1 python -m app.main
```

远程服务：

```bash
SCRIPT_PATH=data/scripts/my-story.json \
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 环境变量

| 变量 | 作用 | 默认 |
|---|---|---|
| `MOCK_LLM` | `1` 时使用固定模拟文案，不请求网络 | 未设置；Docker 镜像为 `1` |
| `MAAS_API_KEY` | MaaS 密钥 | 无 |
| `MAAS_ENDPOINT` | MaaS 地址，可传基础地址或完整 chat completions 地址 | 无 |
| `MAAS_MODEL` | 模型名 | 无 |
| `SCRIPT_PATH` | 剧本 JSON 路径，相对当前工作目录 | `data/scripts/mistvale-inn.json` |

## 验证

页面：

```bash
curl -I http://127.0.0.1:8000/
```

应返回 `200 OK`。

接口：

```bash
curl -X POST http://127.0.0.1:8000/games
```

应返回 `game_id`、`title`、`opening`、`roles` 等公开字段。

测试：

```bash
cd project
python -m pytest -q
```

应看到 `177 passed, 1 skipped`。真模型冒烟测试默认跳过；显式开启：

```bash
RUN_REAL_MODEL=1 python -m pytest -q -m real_model
```

## 故障排查

### 页面打不开

- 确认进程在跑，端口没有被占用。
- 本机访问用 `127.0.0.1:8000`；远程访问必须让 uvicorn 绑定 `0.0.0.0`。
- Docker 必须做端口映射 `-p 8000:8000`。
- 云服务器检查安全组是否放行 8000。

### 提问返回 500

- 没设 `MOCK_LLM=1`，也没配齐 `MAAS_*`。
- 先设 `MOCK_LLM=1` 跑通链接，再配置真实模型。
- 真实模型 401/403 通常是 key、endpoint 或模型名不对；先跑 `python tools/check_maas.py`。

### 提示找不到 `app`

在 `project/` 目录下运行，不要直接在仓库根目录运行 `python -m app.main`。

### 静态页 404

确认 `project/web/` 存在，启动目录是 `project/`。Docker 镜像会自动带上。

### 出示线索返回 409

这是预期行为：同一张线索对同一个 NPC 只能出示一次。前端用 toast 提示，不是系统错误。

### 一局突然没了

局状态只在进程内存里。重启服务、重新部署、换 worker 都会丢局。演示时保持单进程。

## 限制

- 无数据库、无持久化；进程重启丢局。
- 单进程内存状态，不能开多个 worker。
- 没有登录鉴权，不要直接暴露公网。
- 模型请求超时 30 秒，网络失败会直接模板兜底，不会连续重试。
- `.env`、密钥、虚拟环境、`__pycache__` 都不应提交。

---

# 附录：华为云 ECS 部署（答辩用这条）

上面两条路线都能跑，但**要给评委一个链接，走这条**。Docker 路线在本机 Docker Desktop 抽风时可以直接跳过——ECS 上的 Docker 是 Linux 原生，没那个管道问题。

## 1. 买机器

| 项 | 建议 |
|---|---|
| 规格 | 1 核 2G 足够（模型走外部 API，本机不吃算力） |
| 镜像 | Ubuntu 22.04 LTS |
| 带宽 | 按流量计费，或 1–5 M 固定带宽 |
| 计费 | 用比赛发的代金券 |

## 2. 安全组（入方向）

| 端口 | 来源 | 用途 |
|---|---|---|
| 22 | 你的 IP | SSH |
| 80 | 0.0.0.0/0 | **对外访问** |
| 8000 | 你的 IP | 调试用，收尾时关掉 |

## 3. 装环境拉代码

```bash
sudo apt update && sudo apt install -y python3-venv python3-pip nginx git
git clone https://github.com/Rose-0826/Huawei.git
cd Huawei/project
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
vi .env                      # 填 MAAS_API_KEY / MAAS_ENDPOINT / MAAS_MODEL
chmod 600 .env
python tools/check_maas.py   # 必须看到 ✓ 连通 再往下
```

## 4. systemd：让服务在 SSH 断开后还活着

这是最容易翻车的一步。前台跑 `uvicorn`，你一关终端服务就没了。

`sudo vi /etc/systemd/system/mistvale.service`：

```ini
[Unit]
Description=Mistvale game
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/Huawei/project
ExecStart=/home/ubuntu/Huawei/project/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mistvale
sudo systemctl status mistvale    # 看到 active (running)
```

**注意**：`ExecStart` 里**不要加 `--workers`**。局状态存在进程内存里，多 worker 会让"开局"和"提问"落到不同进程，表现为随机 404。

## 5. Nginx 反代到 80

`sudo vi /etc/nginx/sites-available/mistvale`：

```nginx
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120s;
    }
}
```

```bash
sudo ln -sf /etc/nginx/sites-available/mistvale /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

`proxy_read_timeout 120s` 不能省。默认 60 秒，模型偶尔慢一点就 504，而你在答辩现场只会看到"点了没反应"。

## 6. 验证

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://服务器IP/
curl -s -X POST http://服务器IP/games | head -c 200
```

两条都该是 `200` 和一段 JSON。然后用**手机流量**打开一次（不要用校园网），确认外网真的能访问。

## 7. 常见坑

| 现象 | 原因 |
|---|---|
| 浏览器转圈后 504 | Nginx `proxy_read_timeout` 太短 |
| 随机 404 找不到对局 | uvicorn 开了多 worker |
| 502 Bad Gateway | systemd 服务没起来，`journalctl -u mistvale -n 50` 看日志 |
| 页面能开但提问报错 | `.env` 没配好，`curl http://IP/` 是静态页不校验模型 |
| SSH 一断就挂 | 还在前台跑 uvicorn，没上 systemd |

日志怎么看：

```bash
sudo journalctl -u mistvale -f
```