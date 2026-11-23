# 自动化组件部署平台

一键部署基础设施（MySQL、Redis、Kafka、ClickHouse 等）和业务应用（SSO、ODMP、AIMETER 等）到多台目标主机。

## 前置准备（部署前必须完成）

1. **Python 3.10** — 自行将 Python 3.10 安装包上传到部署机，解压到 `/opt/python/` 目录，然后创建软链接：

   ```bash
   ln -sf /opt/python/bin/python3 /usr/local/bin/python3
   ln -sf /opt/python/bin/pip3 /usr/local/bin/pip3
   ```

   确认版本：`python3 --version` 应输出 `Python 3.10.x`。

2. **Python 依赖包离线安装** — 将项目所需的 Python 依赖包（`*.whl` 或 `*.tar.gz`）放到 `/opt/packages/` 目录，然后执行：

   ```bash
   pip3 install --no-index --find-links=/opt/packages -r requirements.txt
   ```

3. **部署用户需 NOPASSWD 免密 sudo**：安装流程包含 `sudo chown`、`sudo tee /etc/my.cnf`、`sudo systemctl` 等命令，SSH 非交互执行无 TTY，sudo 要求密码会直接失败。验证：

   ```bash
   ssh <部署用户>@<目标机> "sudo -n true" && echo "免密sudo可用"
   ```

   验证失败时（报 `sudo: a password is required`，即部署用户有 sudo 但未免密），请在目标机上由管理员执行 `visudo` 添加免密配置，例如：

   ```bash
   <部署用户> ALL=(ALL) NOPASSWD: ALL
   ```

   改完后再次执行上面的验证命令，输出「免密sudo可用」即表示就绪。

4. **MySQL 安装目录权限要求**：

   - **安装目录禁止放在部署用户家目录下**（如 `/home/eoi`）：家目录默认权限 `700`，`mysql` 系统用户无法穿越进入，即使数据目录已 `chown mysql:mysql` 也会报 Permission denied；且 `/home` 受 SELinux 限制。安装目录建议使用 `/data/service` 之类的公共路径。

   - **数据目录属主**：安装时 `data/`、`logs/` 目录会自动 `chown` 给 `mysql` 用户，请勿手动改回部署用户属主，否则 mysqld 无法读写。

## 快速开始

```bash
# CLI 部署模式
python3 install.py --localaddr 192.168.217.100 --nodesfile config.yaml --install-dir /data/service --package-dir /data/softs

# Web 管理界面（推荐）
python3 install.py --localaddr 192.168.217.100 --nodesfile config.yaml --web --web-port 18080
```

> 所有命令必须在 `deploy/` 目录下执行。
>
> Web 模式下 `--install-dir` 和 `--package-dir` 不是必需参数，可在 Config 页面中配置。

## 文档

| 文档 | 说明 |
|------|------|
| [部署文档](docs/deployment.md) | 环境准备、配置说明、部署步骤、工具使用 |
| [模板变量参考](docs/template-vars.md) | 配置模板中可用的所有变量（自动生成） |
| [AGENTS.md](../AGENTS.md) | 项目架构、CLI 参数、组件安装顺序 |

## Web 管理界面

启动 Web 模式后访问 `http://<localaddr>:18080`，提供以下功能页面：

| 页面 | 功能 |
|------|------|
| **Dashboard** | 部署概览、组件/主机数量统计、部署历史趋势 |
| **Wizard** | 向导式组件选择和部署参数配置 |
| **Components** | 按分组（Core/Common/Custom）展示所有组件，支持搜索和状态标记 |
| **Hosts** | 主机列表，展示各主机分配的组件和 SSH 认证方式（密钥/密码） |
| **Config** | config.yaml 在线编辑、语法校验、章节导航快速跳转 |
| **Deploy** | 组件选择、安装顺序流水线、部署参数（4 项）、执行部署、实时日志输出 |
| **Service Check** | 一键巡检组件健康状态（30s 缓存），展示正常/异常/待检测汇总，支持按状态筛选 |
| **Service Manager** | 查看和管理目标主机上的 systemd 服务，支持启动/停止/重启/查看状态 |
| **Mockdata** | Web 界面的 POC 数据模拟工具，选择模块和参数后执行数据注入 |
| **History** | 部署历史记录，支持分页浏览和状态追溯 |

### Config 页面

- 编辑框左侧行号显示，右侧章节导航（All / mysql / redis / zookeeper / ...）
- 点击导航按钮平滑滚动到对应配置段，光标同步定位
- Validate 按钮校验 YAML 语法，校验失败以弹窗（Modal）提示错误详情
- Save 按钮保存配置变更

### Deploy 页面

- **Select Components** — 按 Core / Common / Business Applications 分组选择组件
- **Installation Order** — 展示部署顺序流水线（Core → Common → Custom）
- **Target Hosts** — 各主机的组件分配列表
- **Deployment Parameters** — 4 个参数：Install Dir、Package Dir、Config Dir、HTTP Port
- 右侧 Execution 面板显示部署进度和实时日志

### Service Check 页面

- 从 config.yaml 读取真实组件和主机信息，无硬编码 Mock 数据
- 组件列表按 Core（按序）→ Common（字母序）→ Custom（按序）分组
- 支持筛选（全部/正常/异常/待检测）
- Run Check 按钮异步调用 `tools/service_check.py` CLI，实时更新巡检结果
- **30 秒状态缓存**，避免重复 SSH 请求
- Java/java11/java21 自动安装到所有主机，不在 deploy 中列出

### Service Manager 页面

- 查看指定主机的 systemd 服务列表及运行状态
- 支持对单个服务进行 start/stop/restart/status 操作
- **30 秒状态缓存**，操作后自动清除缓存
- 服务名大小写不敏感匹配

### Mockdata 页面

- Web 界面的 POC 数据模拟，无需命令行操作
- 支持选择模拟模块（alert / metrics / trans-metrics / trans-details / itsm-devops）
- 可指定时间范围
- 实时日志输出到页面

## CLI 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--localaddr` | **(required)** | 部署机 IP（目标主机通过此地址下载） |
| `--nodesfile` | **(required)** | config.yaml 配置文件路径 |
| `--install-dir` | CLI 必需 | 安装根目录；Web 模式可在页面配置 |
| `--package-dir` | `{install-dir}/pkgs` | 安装包目录；Web 模式可在页面配置 |
| `--config-dir` | `conf/template/` | 配置模板目录 |
| `--http-port` | `8000` | HTTP 文件服务端口（下载安装包用） |
| `--service` | (全部) | 只部署指定服务（逗号分隔） |
| `--debug` | (关闭) | 调试模式：仅打印步骤，不实际执行 |
| `--fail-fast` | (启用) | 任意主机失败立即终止；`--no-fail-fast` 禁用 |
| `--json-log` | (关闭) | JSON 格式日志（适合 ELK） |
| `--web` | (关闭) | 启动 Web 管理界面替代 CLI 部署 |
| `--web-port` | `18080` | Web 服务端口 |

## 目录结构

```
deploy/
├── install.py           # 部署入口
├── config.yaml          # 配置文件
├── web/                 # Web 管理界面（FastAPI + Jinja2）
│   ├── main.py          #   应用入口和路由注册（12 个路由）
│   ├── routers/         #   页面路由（dashboard, config, deploy, wizard,
│   │                     #   components, hosts, history, service_check,
│   │                     #   service_manager, mockdata）
│   ├── services/        #   业务逻辑（ConfigService, DeployService,
│   │                     #   HistoryService, MockdataService, DataService）
│   ├── templates/       #   Jinja2 HTML 模板
│   └── static/css/      #   CSS 样式
├── core/                # 核心引擎（SSH、HTTP、预检查、健康检查）
├── installers/          # 安装器（按产品域分组：common, sso, odmp,
│                        #   aimeter, refiner, odc）
├── tools/               # 工具脚本（巡检、ODMP 初始化、Nacos 管理等）
├── utils/               # 健康检查器、Hadoop/Spring 配置预处理
├── conf/template/       # 各组件配置模板
├── lib/                 # 本地辅助文件
│   ├── nginx/           #   Nginx 编译依赖（zlib / pcre / openssl）
│   ├── odmp/            #   ODMP 建模层导入文件
│   ├── packages/        #   离线 Python whl 包
│   └── aimeter/         #   AIMETER 辅助文件
├── docs/                # 文档
├── mockdata/            # POC 数据模拟套件
└── logs/                # 部署日志
```

## 组件安装顺序

1. **核心顺序**：java → mysql → redis → zookeeper → kafka → hadoop → nacos → ckman → clickhouse → nebula → nebula_studio
2. **其他通用组件**：按字母序（如 nginx 等）
3. **固定自定义顺序**：sso → odmp → dolphinscheduler → jax-pyenv → datax → refiner → aimeter → odc
4. **其他自定义组件**：按字母序

> java/java11/java21 自动安装到所有目标主机，无需在 `deploy` 中列出。

## 部署后巡检

```bash
python3 tools/service_check.py --nodesfile config.yaml --install-dir /data/service
```
