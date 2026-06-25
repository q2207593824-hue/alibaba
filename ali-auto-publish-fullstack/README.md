# Alibaba 自动发品与运营管理系统 (全栈版)

本项目是一个为阿里巴巴国际站（Alibaba.com）量身定制的自动化运营工具。它将原本分散的 Python 自动化脚本和独立的前端界面整合为一个现代化的前后端分离全栈应用。

## 核心特性

- **前后端分离架构**：FastAPI 后端 + React/Vite 前端，松耦合设计。
- **模块化后端**：所有核心业务逻辑（属性融合、图片处理、数据下载）均被封装为独立的服务层，易于修改和扩展。
- **自动化操作**：基于 Playwright/Selenium 的浏览器自动化，实现自动登录、自动填表、自动发布。
- **实时任务监控**：通过 WebSocket 实现任务日志的实时推送，前端界面实时展示执行进度。
- **可视化配置**：所有的文件路径、属性映射规则、阶梯价格公式等都可以在前端界面进行可视化配置。

## 项目结构

整个项目采用 Monorepo 结构，非常适合在 PyCharm 或 VSCode 中直接打开根目录进行开发。

```
ali-auto-publish-fullstack/
├── backend/                  # FastAPI 后端目录
│   ├── app/
│   │   ├── api/              # API 路由层 (Controller)
│   │   ├── core/             # 核心配置、日志、任务管理器
│   │   ├── services/         # 业务逻辑层 (Service)
│   │   │   ├── automation/   # 浏览器自动化相关模块
│   │   │   ├── image_service.py
│   │   │   └── upload_service.py
│   │   └── main.py           # FastAPI 应用入口
│   ├── data/                 # 默认数据存储目录
│   ├── requirements.txt      # Python 依赖
│   └── run.py                # 后端启动脚本
│
├── frontend/                 # Vite + React 前端目录
│   ├── client/
│   │   └── src/
│   │       ├── components/   # UI 组件
│   │       ├── hooks/        # 自定义 Hooks (包含 API 轮询和 WS)
│   │       ├── lib/          # API 请求封装 (axios)
│   │       └── pages/        # 页面组件
│   ├── package.json          # Node 依赖
│   └── vite.config.ts        # Vite 配置 (包含代理设置)
│
└── README.md                 # 项目说明文档
```

## 快速开始

### 1. 环境准备

- Python 3.9+
- Node.js 18+ (推荐使用 pnpm)
- Chrome/Edge 浏览器 (用于自动化操作)

### 2. 后端启动

```bash
cd backend
# 建议创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 启动服务 (默认运行在 http://localhost:8000)
python run.py
```

#用python -3.11

```bash
#创建虚拟环境
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
python run.py

```

### 3. 前端启动

```bash
cd frontend

# 安装依赖
pnpm install

# 启动开发服务器 (默认运行在 http://localhost:3000)
pnpm run dev
```

##打包命令：powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1
或在 frontend 目录执行：pnpm run desktop:build

前端会自动将 `/api` 开头的请求代理到 `http://localhost:8000`。

### 部署模式：仅会员/积分上云 + 客户安装桌面包（推荐）

| 位置 | 跑什么 | 说明 |
|------|--------|------|
| **云端服务器**（宝塔） | `/api/membership/*`、积分、充值回调 | 权威会员库与积分，多端共享 |
| **客户电脑（安装包）** | 本地后端 `127.0.0.1:8000` + 发品/数据/自动化 | 不占云服务器算力，数据在客户本机 |

```text
客户安装包
  界面 → http://127.0.0.1:8000（本地）
  发品/下载/配置/任务 → 仅本地，不走云
  登录/注册/积分/会员状态 → 本地 API 转发 → 云端 https://echo-yiwu.cloud/api/membership
```

- 前端 `api.ts` 在桌面版已固定连 `127.0.0.1:8000`，**不会**让发品功能直连云端。
- 安装包启动时通过环境变量 `CLOUD_MEMBERSHIP_API_BASE` 指向你的云（见 `frontend/electron/main.cjs`）。
- **宝塔上不必给客户部署完整网站**；只需保证域名下会员 API 可访问。可选再部署网页版给管理员用。

### 宝塔（云端）最简部署 — 只服务会员/积分

**详细步骤（Python 项目管理、快速重启）** → [docs/宝塔云端-Python项目管理.md](./docs/宝塔云端-Python项目管理.md)

1. 上传代码到 `/www/wwwroot/ali-auto-publish-fullstack`
2. 宝塔 **Python 项目**：项目路径 **`backend`**，启动方式 **python**，启动文件 **`run_cloud.py`**（**不要**填 `/bin/bash`，否则会 `SyntaxError: null bytes`）。端口 `8000`。
3. Nginx：`https://echo-yiwu.cloud` 反代到 `127.0.0.1:8000`
4. 日常在面板点 **重启**（勿再 SSH 常驻 `python run.py`）
5. 自检：

```bash
curl -sk -o /dev/null -w "%{http_code}\n" https://echo-yiwu.cloud/api/membership/me
# 401 或 200 均表示云端会员 API 已通
```

**可不构建** `frontend/dist` 上云（客户只用安装包时）。若要在浏览器管理会员，再执行 `pnpm run build` 并由后端挂载静态页。

### 打客户安装包（Windows）

```bash
cd frontend
pnpm install
pnpm run desktop:build:web
pnpm run desktop:build:backend
pnpm run desktop:build
```

打包前确认云端地址（改域名时只改一处默认值或构建前设环境变量）：

```powershell
$env:CLOUD_MEMBERSHIP_API_BASE = "https://echo-yiwu.cloud/api/membership"
pnpm run desktop:build
```

### 会员 / 积分架构（推荐方案）

| 能力 | 走哪里 | 说明 |
|------|--------|------|
| 登录、注册、`/me`、流水、充值 | **云端** `echo-yiwu.cloud/api/membership` | 前端 `cloudMembershipApi` 直连；开发态经 Vite `/cloud-api` 代理 |
| 发品、配置、任务、扣积分业务 | **本地** `127.0.0.1:8000/api` | 本地后端 `cloud_consume_points()` 调云端扣费 |
| 节点注册、关键词遥测 | **本地** `/api/membership/...` | 控制面数据入库本机 |
| 开发环境管理员登录 | **本地** `/api/membership/auth/admin-login` | `admin_accounts` 表 |

- **VPN/Clash 不影响会员登录（内置）**：后端启动时会 `NO_PROXY` 会员域名并禁用 HTTP 代理；访问云端时自动 **DoH 解析真实 IP + HTTPS SNI 直连**，绕过 `198.18.x.x` 假 DNS。诊断：`GET /api/membership/connectivity` 看 `fake_dns`、`resolved_ips`、`ok`。
- 若仍失败，可在 hosts 增加：`43.164.196.172 echo-yiwu.cloud`，或设置 `CLOUD_MEMBERSHIP_API_IP` / `CLOUD_MEMBERSHIP_API_IPS`。
- 纯离线调试本地库：`ALI_OFFLINE_DEV=1 python run.py`（仅开发，不与生产一致）。

### 云端相关环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CLOUD_MEMBERSHIP_API_BASE` | `https://echo-yiwu.cloud/api/membership` | 本地后端转发云端时的统一前缀 |
| `CLOUD_MEMBERSHIP_API_IP` | `43.164.196.172` | VPN 环境下 IP 回退（与 DoH 结果合并） |
| `CLOUD_MEMBERSHIP_API_IPS` | 未设置 | 多个 IP，逗号分隔 |
| `ALI_CLOUD_BYPASS_PROXY` | `1` | 后端启动时清空 HTTP 代理环境变量 |
| `MEMBERSHIP_POINTS_SOURCE` | `cloud` | 桌面/开发默认；`local` 仅离线调试 |
| `MEMBERSHIP_IS_CLOUD_HOST` | 未设置 | **云端服务器必设 `1`**：本机库为权威，禁止再请求公网 membership |
| `MEMBERSHIP_GUARD_CLOUD_OVERRIDE` | 未设置 | 设为 `1` 时，本地判「非会员」会再请求云端复核 |
| `VITE_CLOUD_MEMBERSHIP_API_BASE` | 开发：`/cloud-api/membership` | 前端会员 API 基址（见 `frontend/.env.development`） |
| `ALI_OFFLINE_DEV` | 未设置 | 开发机 `run.py` 设为 `1` 时强制 `MEMBERSHIP_POINTS_SOURCE=local` |

部署后自检：`curl -s -o /dev/null -w "%{http_code}" https://你的域名/api/membership/me`（401 也算连通）。

**宝塔 Python 项目**：启动文件填 **`run_cloud.py`**（勿填 `/bin/bash`）。环境变量也可在面板追加，但 `run_cloud.py` 已内置云端默认值。

重启后日志应含：`☁️ 云端会员主机模式已启用`。本机验证：

```bash
curl -sS -X POST "http://127.0.0.1:8000/api/membership/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"你的账号","password":"你的密码"}'
```

### 依赖安装约定（避免锁文件冲突）

- **前端只使用 pnpm**：请在 `frontend/` 目录执行 `pnpm install`
- **不要在项目根目录执行 `npm install`**：根目录仅用于 monorepo 容器/脚本，不应生成 `package-lock.json`

## 如何二次开发和修改代码？

本项目的架构设计充分考虑了未来的扩展性，如果你需要修改或增加功能，请参考以下指南：

### 场景 1：修改属性融合逻辑或发品流程

发品的核心逻辑在 `backend/app/services/automation/` 目录下：

- 如果要修改**属性映射规则**：修改 `attribute_filler.py`
- 如果要修改**阶梯价格计算**：修改 `price_setter.py`
- 如果要修改**图片上传逻辑**：修改 `image_uploader.py`
- 如果阿里**后台页面结构变化**：修改 `page_helpers.py` 中的元素定位器 (XPath/CSS)

### 场景 2：增加新的配置项

1. **后端**：在 `backend/app/core/settings.py` 的 `Settings` 类中添加新字段。
2. **前端**：在 `frontend/client/src/pages/ProductConfig.tsx` 中添加对应的 UI 控件（Input/Switch），并绑定 `updateConfig` 函数。

### 场景 3：增加新的 API 接口

1. **后端**：在 `backend/app/api/` 目录下找到对应的路由文件（如 `upload_router.py`），添加新的 `@router.get()` 或 `@router.post()` 方法。
2. **前端**：在 `frontend/client/src/lib/api.ts` 中添加对应的请求函数，然后在页面组件中调用。

## 技术栈

- **后端**: FastAPI, Uvicorn, Pydantic, Playwright/Selenium (根据原脚本依赖)
- **前端**: React 19, Vite, TailwindCSS 4, Wouter (路由), Radix UI (组件基础), Lucide React (图标)

## 客户分发（Windows 桌面安装包）

客户只需安装 **exe**，无需 Python/Node。会员与积分走云端 `https://echo-yiwu.cloud`；发品与任务在本机 `127.0.0.1:8000` 执行。

**给客户看的文档**：[客户交付说明.md](./客户交付说明.md)

### 交付物（`frontend/release/`）

| 文件 | 用途 |
|------|------|
| `AliAutoPublish-*-win-x64.exe` | 安装版（推荐正式交付） |
| `免安装.exe` | 便携版，免安装 |
| `AliAutoPublish-*-win-x64.zip` | 绿色压缩包备用 |

### 一键打包（开发机 Windows）

```powershell
# 结束可能占用的进程（可选）
taskkill /F /IM "Ali Auto Publish.exe" 2>$null
taskkill /F /IM ali-backend.exe 2>$null
taskkill /F /IM ali-backend-service.exe 2>$null

# 推荐：根目录脚本
powershell -ExecutionPolicy Bypass -File scripts\build-desktop.ps1

# 或手动（在 frontend 目录）
cd frontend
pnpm install
pnpm run desktop:build
```

`desktop:build` 依次执行：Vite 前端构建 → PyInstaller 打 `backend/dist/ali-backend.exe` → `electron-builder` 生成安装包。

**打包前**：云端主机已按上文 **宝塔（云端）最简部署** 与 **云端相关环境变量** 配置；本地用安装包冒烟：会员登录 → 进入系统 → 发品页可打开。

### 分步 / 排错

```powershell
cd frontend
pnpm run desktop:build:web      # 仅前端
pnpm run desktop:build:backend  # 仅后端 exe（需 backend/venv）
pnpm run desktop:preflight      # 检查 dist 下 ali-backend.exe
pnpm exec electron-builder      # 仅 Electron 壳（需前两步已完成）
```

后端单独重打：在 `backend` 下先 `pnpm run desktop:build:web`（或 `cd frontend && pnpm run desktop:build:web`），再 `python build_backend_exe.py`。若 PyInstaller/NumPy 报错，在 venv 内升级：`pip install -U pyinstaller`。

## 新发链接监控数据链路说明

本节说明“数据分析 -> 综合分析 -> 新发链接监控”页面内容的来源、生成过程与读取字段。

### 1) 运行入口（哪些代码会触发生成）

执行综合分析任务时，会进入：

- `backend/app/services/analysis_service.py`
- 函数：`_run_comprehensive_analysis(...)`
- 步骤标记：`task.current_step = "新发链接监控"`

该步骤会生成输出文件：

- `data_analysis.new_output_file`
- 默认：`新发链接数据监控.xlsx`

### 2) 输入来源（从哪读）

新发链接监控由两类输入数据拼出来：

1. 新发产品ID名单
  - 文件：`data_analysis.new_links_file_path`
  - 默认：`新发链接监控.xlsx`
  - Sheet：`data_analysis.new_links_sheet_name`（默认 `新链接`）
  - 列名：`data_analysis.new_links_column_name`（默认 `新发链接`）
2. 综合统计指标明细
  - 文件：`data_analysis.output_file`
  - 默认：`统计csss.xlsx`
  - Sheet：按 `data_analysis.target_columns` 逐个读取同名 sheet
  - 常见 sheet（取决于配置）：
    - `全店曝光次数`
    - `全站推广曝光次数`
    - `搜索曝光次数`
    - `全店点击次数`
    - `全站推广点击次数`
    - `搜索点击次数`
    - `访问人数`
    - `收藏人数`
    - `询盘人数`
    - `TM咨询人数`

### 3) 输出结构（生成了什么）

生成文件：`新发链接数据监控.xlsx`

- 每个 `target_columns` 指标生成一个同名 sheet
- 每个 sheet 基于“新发链接名单”对 `统计csss.xlsx` 对应指标 sheet 进行过滤
- 保留并按新发名单顺序重排

其中 `全店曝光次数` sheet 会额外追加两列：

- `最近橱窗状态`
- `最近P4P状态`

### 4) 前端页面当前读取方式

“推荐关注产品”右侧“新发链接监控（四周≥30）”当前读取：

- 接口：`analysisApi.getNewLinksMonitor(undefined, "全店曝光次数")`
- 即读取 `新发链接数据监控.xlsx` 的 `全店曝光次数` sheet

用于展示时的列处理规则：

- 主键列优先 `产品ID`
- 排除列：`异动`、`涨跌`、`最近橱窗状态`、`最近P4P状态`
- 其余列视为“周列”（如 `260301-260307`）
- 取最新4个周列展示，并筛选“4周中至少3周 > 30”的产品

### 5) 新发链接名单自动写入（发品成功后）

自动发品成功后，系统会在成功跳转 URL 中提取 `primaryId`，并写入新发链接监控源文件：

- 提取位置：`backend/app/services/automation/submit_handler.py`
  - `submit_and_verify()` 在成功 URL 中解析 `primaryId`
- 传递位置：`backend/app/services/automation/product_publisher.py`
  - `publish_single_product()` 返回 `(success, primary_id)`
- 落盘位置：`backend/app/services/upload_service.py`
  - `save_new_link_product(primary_id)`

写入规则：

- 文件：`data_analysis.new_links_file_path`（默认 `新发链接监控.xlsx`）
- Sheet：`data_analysis.new_links_sheet_name`（默认 `新链接`）
- 表头：
  - `发品日期`（格式：`yyMMdd`）
  - `新发链接`
- 新记录插入最前面（第2行起）
- 若 `新发链接` 中已存在该 `primaryId`，则跳过去重

### 6) 常用配置项总览

位于：`backend/app/core/settings.py` -> `DataAnalysisConfig`

- `new_links_file_path`: 新发链接源文件路径
- `new_links_sheet_name`: 新发链接源 sheet 名
- `new_links_column_name`: 新发链接ID列名
- `output_file`: 综合统计文件路径（统计csss）
- `new_output_file`: 新发链接监控输出文件路径
- `target_columns`: 综合分析指标列表（决定输出有哪些 sheet）

