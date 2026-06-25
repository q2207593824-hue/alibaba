# 云端：宝塔「Python 项目管理」部署指南

用宝塔 **Python 项目** 托管云端会员 API，可在面板里 **停止 / 重启**（通常几秒），不必每次 SSH 手敲 `python run.py`，也避免和面板守护进程抢 **8000** 端口。

---

## 一、部署范围（云端只跑什么）

| 跑在云端 | 不跑在云端 |
|----------|------------|
| `/api/membership/*` 登录、积分、充值 | 客户发品、Playwright 自动化 |
| `membership.db` 权威数据 | 客户桌面包里的本地业务 |

客户安装包仍连 `https://你的域名/api/membership`；云端只需 **backend** 目录 + Nginx 反代。

---

## 二、一次性准备

### 1. 上传代码

建议路径（与下文一致）：

```text
/www/wwwroot/ali-auto-publish-fullstack/
└── backend/          ← Python 项目根目录必须是这里
    ├── run.py
    ├── start_cloud_host.sh
    ├── requirements.txt
    └── app/
```

数据目录（可自定义）：

```text
/www/wwwroot/ali-auto-publish-fullstack/data/
```

### 2. 停掉旧的手工进程（只做一次）

在 SSH 或宝塔终端：

```bash
# 若以前用 nohup / screen 跑过，先杀掉，避免和面板抢 8000
pkill -f "run.py" 2>/dev/null || true
ss -lntp | grep ':8000 ' || echo "8000 空闲"
```

**以后只通过面板启停**，不要再 SSH 里 `python run.py` 常驻。

### 3. 安装依赖（虚拟环境）

**方式 A（推荐）**：宝塔添加 Python 项目时勾选「创建虚拟环境」，在 **模块** 里安装 `requirements.txt`。

**方式 B**：SSH 手动：

```bash
cd /www/wwwroot/ali-auto-publish-fullstack/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

宝塔自动生成的 venv 目录名可能是 `xxxx_venv`（一串 hash），`start_cloud_host.sh` 会自动优先使用该目录。

---

## 三、宝塔面板配置（核心步骤）

路径：**网站 → Python 项目 → 添加项目**（或编辑已有项目）

| 配置项 | 填写值 | 说明 |
|--------|--------|------|
| **项目名称** | `ali-membership-cloud` | 任意，便于识别 |
| **项目路径** | `/www/wwwroot/ali-auto-publish-fullstack/backend` | **必须是 backend 目录** |
| **Python 版本** | 3.10 或 3.11 | 与 venv 一致 |
| **框架** | 自定义 / 其他 | 无官方 FastAPI 就选自定义 |
| **启动方式** | `python` | 不要用「命令行」填 bash |
| **启动文件** | `run_cloud.py` | 见 `backend/run_cloud.py` |
| **端口** | `8000` | 与 Nginx 反代一致 |
| **进程数 / workers** | **`1`**（必须） | 填 `4` 会起 4 个进程，日志里多次 `Application startup complete`、端口冲突 |
| **启动文件（若相对路径无效）** | `/www/wwwroot/ali-auto-publish-fullstack/backend/run_cloud.py` | 填相对路径仍报 `/www/server/panel/run_cloud.py` 时用**绝对路径** |
| **开机启动** | 开启 | 服务器重启后自动拉起 |

### 启动文件（重要：不要用 /bin/bash）

宝塔「Python 项目管理」会用 **Python 解释器** 执行你填的「启动文件」。  
若填 `/bin/bash` 或 `start_cloud_host.sh`，会报错：

```text
SyntaxError: source code cannot contain null bytes
```

**正确配置：**

| 配置项 | 值 |
|--------|-----|
| **启动方式** | `python` |
| **启动文件** | `run_cloud.py` |

`run_cloud.py` 已内置云端环境变量（`MEMBERSHIP_IS_CLOUD_HOST=1` 等），无需再填 bash。

**错误示例（勿用）：** 启动文件 = `/bin/bash`、启动文件 = `start_cloud_host.sh`

**SSH 手工启动** 仍可用：`bash start_cloud_host.sh` 或 `python3 run_cloud.py`

### 环境变量（若不用 start_cloud_host.sh，必须在面板填写）

在 Python 项目 → **环境变量** / **配置文件** 中添加：

```bash
MEMBERSHIP_POINTS_SOURCE=local
MEMBERSHIP_IS_CLOUD_HOST=1
ALI_BACKEND_WORKERS=1
ALI_BACKEND_RELOAD=0
ALI_APP_DATA_DIR=/www/wwwroot/ali-auto-publish-fullstack/data
CLOUD_MEMBERSHIP_API_BASE=https://echo-yiwu.cloud/api/membership
BACKEND_PORT=8000
```

> **不要**只在 SSH 里 `export` 后启动——面板拉起的进程读不到那次 SSH 的环境变量，会导致又去请求公网 membership、登录失败。

### 赋予脚本执行权限

```bash
chmod +x /www/wwwroot/ali-auto-publish-fullstack/backend/start_cloud_host.sh
```

---

## 四、Nginx（网站反代）

**网站** → 你的域名（如 `echo-yiwu.cloud`）→ **反向代理**：

| 项 | 值 |
|----|-----|
| 目标 URL | `http://127.0.0.1:8000` |
| 发送域名 | `$host` |

会员 API 路径为 `/api/membership/...`，无需单独再配一条；整站反代到 8000 即可（云端可不部署前端静态页）。

SSL 在宝塔 **SSL** 里申请 Let's Encrypt 并开启强制 HTTPS。

---

## 四点五、进程数在哪里改？（只保留 1 个进程）

日志里若出现 **4 次** `Started server process` / `Application startup complete`，说明 **workers=4** 或仍在跑 **`run.py`**。

**在宝塔改（不要改业务代码）：**

1. Python 项目列表 → 你的项目 → 点 **「配置」**
2. 找到 **进程数** / **workers** / **启动参数** → 改为 **`1`**
3. 环境变量里加上：`ALI_BACKEND_WORKERS=1`
4. **启动文件** 必须是 `run_cloud.py`（不是 `run.py`）
5. **项目路径** 必须是 `.../backend`（完整路径，不要 `.../ba`）

改完后：**停止** → SSH 执行 `pkill -9 -f run.py; pkill -9 -f run_cloud.py` → 再 **启动**。

正确日志只有 **1 条** worker 启动，且应有：

```text
[run_cloud] app=app.cloud_app:app
```

不应出现：`Starting Alibaba Auto Publish Backend Server...`（那是 `run.py`）。

---

## 五、日常运维：快速重启

1. 宝塔 → **Python 项目** → 找到 `ali-membership-cloud`
2. 点 **重启**（或 停止 → 启动）
3. 点 **日志**，确认出现：

```text
[run_cloud] app=app.cloud_app:app
[run_cloud] listening 0.0.0.0:8000
```

并执行 `curl http://127.0.0.1:8000/api/health` 返回 JSON（不是 504）。

一般 **3～10 秒** 可完成；`ALI_BACKEND_WORKERS=1` 比多 worker 停得快。

**更新代码后：**

```bash
cd /www/wwwroot/ali-auto-publish-fullstack
# git pull 或上传覆盖 backend/
```

然后在面板 **重启** Python 项目即可（无需重装整个网站）。

---

## 六、运行时配置入库（方案 B，首次升级必做）

管理员 **API Key / 大模型 / 积分单价** 已改为云端数据库表 `app_runtime_settings` 权威存储（不再仅依赖 `admin_runtime_config.json`）。

在服务器项目目录执行一次迁移（需已设置 `MEMBERSHIP_IS_CLOUD_HOST=1` 与 `ALI_APP_DATA_DIR` 指向云端 `data` 目录）：

```bash
cd /www/wwwroot/ali-auto-publish-fullstack/backend
export MEMBERSHIP_IS_CLOUD_HOST=1
export ALI_APP_DATA_DIR=/www/wwwroot/ali-auto-publish-fullstack/data

# 宝塔/OpenCloudOS 通常没有 python 命令，用 python3 或项目 venv（目录名可能是 xxxx_venv）
PY=$(ls -d *_venv/bin/python3 2>/dev/null | head -1)
if [ -z "$PY" ]; then PY=python3; fi
$PY ../scripts/migrate_runtime_json_to_db.py
```

成功后 `/api/membership/admin/runtime-config` 的 GET 响应会包含 `points_pricing` 段；桌面客户端 pull 后本机 `config.json` 会同步单价。

---

## 七、自检命令

在服务器上执行：

```bash
# 1) 本机直连后端
curl -sS -X POST "http://127.0.0.1:8000/api/membership/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"测试账号","password":"测试密码"}'

# 2) 经域名（与客户端一致）
curl -sk -o /dev/null -w "HTTPS /me => %{http_code}\n" \
  -H "Authorization: Bearer 无效token" \
  https://echo-yiwu.cloud/api/membership/me
# 401 表示 API 已通；502/504 表示 Nginx 或后端未起
```

---

## 八、常见问题

### 0a. 浏览器打开 `/api/health` 显示 **504 Gateway Time-out**（nginx）

**含义**：Nginx 在跑，但 **反代的上游（127.0.0.1:8000）没有在超时内响应**。  
宝塔里项目显示「运行中」、端口却是 **`--`** 时，多半是 **进程没真正监听 8000**，或仍在用完整 `app.main` 启动过慢。

**按顺序处理（SSH 或宝塔终端）：**

```bash
# 1) 本机能否直连后端（最关键）
curl -sS -m 5 http://127.0.0.1:8000/api/health
# 正常应立刻返回 JSON：{"status":"ok","service":"ali-membership-cloud",...}
# 若连接失败 / 一直卡住 → 问题在 Python 项目，不是客户电脑

# 2) 8000 是否在监听
ss -lntp | grep ':8000 '

# 3) 看面板项目日志（应含 run_cloud、listening 0.0.0.0:8000）
# 宝塔 → Python 项目 → 日志
```

**面板侧必查：**

| 检查项 | 正确值 |
|--------|--------|
| 启动文件 | **`run_cloud.py`**（不是 `run.py`） |
| 端口 | **`8000`**（不能空着显示 `--`） |
| 项目路径 | `.../backend` |
| 网站反代 | `http://127.0.0.1:8000` |

**若 `ss` 显示 8000 在监听但 `curl` 超时（Recv-Q 很大，如 760）：**

进程已卡死（常在启动时跑 `init_db()` 或仍用完整 `app.main`）。执行：

```bash
cd /www/wwwroot/ali-auto-publish-fullstack/backend
chmod +x scripts/cloud_restart.sh
# 先停宝塔 Python 项目，再：
bash scripts/cloud_restart.sh /www/wwwroot/ali-auto-publish-fullstack
# 另开终端：curl -sS -m 3 http://127.0.0.1:8000/api/health
# 看到 JSON 后 Ctrl+C，回宝塔点「启动」
```

或手工：

```bash
kill -9 $(ss -lntp | grep ':8000 ' | grep -oP 'pid=\K[0-9]+') 2>/dev/null || true
pkill -9 -f run_cloud.py; pkill -9 -f run.py
rm -f /www/wwwroot/ali-auto-publish-fullstack/data/membership.db-wal \
      /www/wwwroot/ali-auto-publish-fullstack/data/membership.db-shm
```

**修复步骤：**

1. Python 项目 → **停止** → SSH 执行 `pkill -f run_cloud.py; pkill -f run.py`  
2. 确认 `ss -lntp | grep 8000` 无输出  
3. 上传最新代码（含 `app/cloud_app.py`，`run_cloud.py` 默认只起会员轻量应用）  
4. 面板 **启动**，等 5～15 秒后再执行 `curl http://127.0.0.1:8000/api/health`  
5. 本机 curl 正常后，浏览器再访问 `https://echo-yiwu.cloud/api/health` 应返回 JSON，而不是 504  

**Nginx 反代示例（站点配置 → 反向代理）：**

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_connect_timeout 60s;
    proxy_read_timeout 120s;
}
```

> 只有 `/api/health` 在本机 curl 通之后，客户桌面端登录才有可能成功；客户端无法代替修复云端 504。

### 0. 启动失败：`SyntaxError: source code cannot contain null bytes`（/bin/bash）

**原因**：启动文件填成了 `/bin/bash` 或 `.sh` 脚本。  
**处理**：改为启动文件 **`run_cloud.py`**，启动方式 **python**，保存后重启。

### 0b. `Address already in use` / 守护进程未运行

```bash
# 面板先点「停止」，再 SSH 清残留
pkill -f "run.py" 2>/dev/null || true
pkill -f "run_cloud.py" 2>/dev/null || true
ss -lntp | grep ':8000 '
```

确认只有 **一个** 进程监听 8000 后，再在面板点「启动」。进程数/workers 保持 **1**。

### 0c. 登录全是 `400 Bad Request` 且日志没有「☁️ 云端会员主机模式」

说明仍在用 `run.py` 且未设 `MEMBERSHIP_IS_CLOUD_HOST=1`，会去请求公网自己导致失败。  
**改用 `run_cloud.py` 启动**，日志应出现云端会员主机模式。

### 1. 重启后仍「云端会员服务不可用」

- 看 Python 项目日志是否含 `☁️ 云端会员主机模式`
- 若没有：环境变量未生效 → 改用 `start_cloud_host.sh` 或检查面板环境变量
- `ss -lntp | grep 8000` 若有两个进程：曾手工 `python run.py`，杀掉后只在面板启停

### 2. 端口被占用 (10048 / Address already in use)

```bash
ss -lntp | grep ':8000 '
```

在面板 **停止** 项目，确认无残留 `python run.py`，再 **启动**。

### 3. 重启很慢

- 确认 `ALI_BACKEND_WORKERS=1`
- 确认 `ALI_BACKEND_RELOAD=0`（生产不要开 reload）
- 云端不要装 Playwright 浏览器（会员 API 用不到）

### 4. 与「Supervisor」的关系

宝塔 Python 项目底层常用 **Supervisor** 守护；你只需用面板按钮，不必再单独配一份 supervisor 配置，避免双守护。

---

### 会员登录提示「账号或密码错误」

云端已启用 `MEMBERSHIP_IS_CLOUD_HOST=1` 时，**只认服务器上** `data/membership.db` 里 `users` 表的账号密码，与桌面本地库、旧环境无关。

在服务器执行（路径按实际修改）：

```bash
cd /www/wwwroot/ali-auto-publish-fullstack/backend
export ALI_APP_DATA_DIR=/www/wwwroot/ali-auto-publish-fullstack/data

# 查看账号是否存在
sqlite3 "$ALI_APP_DATA_DIR/membership.db" "SELECT id,username FROM users WHERE username='321654';"

# 创建或重置密码（示例密码请自行修改）
./abf6e215d777327786333f8c0d4b2a62_venv/bin/python3 scripts/reset_member_password.py 321654 '你的新密码'

# 验证登录
curl -sS -X POST "http://127.0.0.1:8000/api/membership/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"321654","password":"你的新密码"}'
```

返回 `success:true` 且含 `token` 后，客户端用同一密码登录即可。

## 九、创建管理员账号（admin_accounts 表）

代码中**不再内置**默认管理员，需在数据库中创建：

```bash
cd /www/wwwroot/ali-auto-publish-fullstack/backend
python3 scripts/create_admin_account.py 你的管理员名 你的密码
```

并配置管理端 API Key（环境变量 `ALI_ADMIN_API_KEY` 或 `config.json` 中 `payment.admin_api_key`）。

登录页同一入口会自动识别：`admin_accounts` → 管理员，`users` → 会员。

## 十、与本地开发的区别

| | 云端（宝塔 Python 项目） | 本地开发 `python run.py` |
|--|--------------------------|---------------------------|
| `MEMBERSHIP_IS_CLOUD_HOST` | **1** | 不设 |
| `MEMBERSHIP_POINTS_SOURCE` | **local** | 默认 cloud 或 `ALI_OFFLINE_DEV=1` |
| 重启方式 | 面板重启 | Ctrl+C 再运行 |
| 端口 | 8000 + Nginx | 8000 |

---

相关文件：

- `backend/start_cloud_host.sh` — 云端一键启动脚本
- `README.md` — 架构与变量总表
