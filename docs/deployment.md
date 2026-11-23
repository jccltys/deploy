# 自动化组件部署平台 — 部署文档

> **前置准备**（部署前必须完成）：
>
> 1. **Python 3.10** — 自行将 Python 3.10 安装包上传到部署机，解压到 `/opt/python/` 目录，然后创建软链接：
>    ```bash
>    ln -sf /opt/python/bin/python3 /usr/local/bin/python3
>    ln -sf /opt/python/bin/pip3 /usr/local/bin/pip3
>    ```
>    确认版本：`python3 --version` 应输出 `Python 3.10.x`。
>
> 2. **Python 依赖包离线安装** — 将项目所需的 Python 依赖包（`*.whl` 或 `*.tar.gz`）放到 `/opt/packages/` 目录，然后执行：
>    ```bash
>    pip3 install --no-index --find-links=/opt/packages -r requirements.txt
>    ```
>
> 3. **Java 版本手动指定** — Java 安装包因文件名不含 "java" 字样，须在 `config.yaml` 的 `packages` 中手动配置包名和版本（见 §2.1），否则安装器会报错退出
>
> 4. **SSH 免密登录** — 部署机到所有目标主机、目标主机之间必须配好密钥认证；若部署 DolphinScheduler，还需本机到本机免密（`ssh localhost`）以及本机到其他所有 DolphinScheduler 部署机器
>
> 5. **nebula-console 必选** — `--package-dir/common/` 下必须放入 Nebula Console 连接工具（文件名以 `nebula-console` 开头即可），否则 NebulaGraph 安装后无法创建 SPACE，部署将失败
>
> 6. **组件主机数量合规** — 各组件主机数必须满足引擎预检查要求（见 §2.2 注意事项），否则部署启动时直接报错退出
>
> 7. **核心服务地址必配** — `mysql`、`redis`、`zookeeper`、`kafka`、`clickhouse`、`hadoop`、`nacos`、`ckman` 这 8 个核心服务必须在 `deploy` 中配置主机地址（见 §2.2），部署引擎预检查阶段会强制校验，缺失任一服务的地址配置都会直接报错退出。即使这些服务已部署好不需要再次安装，也必须配置地址（只需不放置安装包即可）。
>
> 8. ~~**mockdata 使用前必须修改 `mockdata/config/common_config.yaml`** — 将 MySQL 和 Kafka 地址替换为实际环境地址，否则数据模拟会连接错误的地址导致失败（见 §6.7）~~ **已废弃** — `install.py` 预检查后自动从 `config.yaml` 推断并写入 MySQL/Kafka 地址
> >
> > 9. **ZooKeeper Admin Server 端口** — ZooKeeper 3.5+ 内嵌 Admin Server（Jetty），部署时自动写入 `admin.serverPort=8081`（通过 `config.yaml` 中 `zookeeper.admin_port` 配置，默认 8081），避免与 18080 端口冲突
> >
> > 10. **ODMP 门户认证** — ODMP 门户认证默认关闭（`authProvider: none`, `licenseProvider: none`）。如需启用统一门户认证，上传许可文件后在 ODMP 的 `application.yml` 中将 `website.security.authProvider` 改为 `unifiedAuth`、`website.security.licenseProvider` 改为 `unifiedLicense`，然后重启 ODMP 服务

> **前置阅读**: 请先阅读 [`AGENTS.md`](../AGENTS.md) 了解项目架构、CLI 参数概览。
> 本文档聚焦于部署前的准备工作和执行细节。

## 一、环境准备

### 1.1 部署机要求

部署机是执行 `install.py` 的机器，需要满足：

| 要求 | 说明 |
|------|------|
| Python | 3.10，已安装项目所需依赖（见前置准备第 2 条） |
| SSH | `ssh` 命令可用，支持密钥认证 |
| 网络 | 能与所有目标主机通信，HTTP 端口（默认 8000）在目标主机上可达 |
| 系统工具 | `ssh`, `tar`, `curl`（目标主机也需要） |

可选工具：
- `sshpass`：如果使用密码认证 SSH
- 目标主机如需编译 nginx，需要 `gcc`, `make`, `pcre-devel`, `zlib-devel`, `openssl-devel`

### 1.2 部署机项目目录

项目根目录（即本仓库）包含以下结构：

```
deploy/
├── install.py              # 部署入口脚本
├── config.yaml             # 示例配置文件
├── web/                    # Web 管理界面（FastAPI + Jinja2）
│   ├── main.py             #   应用入口和路由注册（12 个路由）
│   ├── routers/            #   页面路由
│   │   ├── dashboard.py    #     部署概览
│   │   ├── config.py       #     配置编辑
│   │   ├── deploy.py       #     执行部署
│   │   ├── wizard.py       #     部署向导
│   │   ├── components.py   #     组件列表
│   │   ├── hosts.py        #     主机列表
│   │   ├── history.py      #     部署历史
│   │   ├── service_check.py    #  健康巡检
│   │   ├── service_manager.py  #  systemd 服务管理
│   │   ├── mockdata.py     #     数据模拟
│   │   └── __init__.py
│   ├── services/           #   业务逻辑
│   │   ├── config_service.py   #  配置读写
│   │   ├── deploy_service.py   #  部署引擎
│   │   ├── history_service.py  #  历史记录
│   │   ├── mockdata_service.py #  数据模拟
│   │   └── data_service.py     #  数据加载
│   ├── templates/          #   Jinja2 HTML 模板
│   └── static/css/         #   CSS 样式
├── core/                   # 核心引擎模块
│   ├── parser.py           #   YAML 配置加载/解析
│   ├── ssh_client.py       #   SSH 远程执行（基于系统 ssh 命令）
│   ├── http_server.py      #   HTTP 文件服务（供远程主机下载安装包）
│   ├── logger.py           #   日志模块
│   ├── precheck.py         #   部署前预检查（SSH 免密验证、主机数量校验）
│   ├── health_check.py     #   健康检查编排
│   ├── config_utils.py     #   配置工具（端口提取、组件变量获取）
│   ├── mysql_db.py         #   MySQL 数据库初始化工具
│   ├── clickhouse_db.py    #   ClickHouse 数据库初始化工具
│   └── ckman_api.py        #   ckman REST API 封装
├── installers/             # 安装器插件（按产品域分组）
│   ├── common/             #   通用/基础设施组件（14 个安装器 + base_installer.py）
│   ├── sso/                #   SSO 认证服务安装器
│   ├── odmp/               #   ODMP 及相关组件安装器（dolphinscheduler/datax/jax-pyenv）
│   ├── aimeter/            #   AIMETER 安装器
│   ├── refiner/            #   REFINER 安装器
│   └── odc/                #   ODC 安装器
├── utils/                  # 通用工具模块（健康检查器、Hadoop/Spring 配置预处理）
├── mockdata/               # POC 数据模拟套件
├── tools/                  # 独立可用的工具脚本
│   ├── service_check.py    #   组件健康巡检
│   ├── odmp_api.py         #   ODMP 采集层/建模层/系统配置初始化
│   ├── odmp_publish.py     #   ODMP 模型发布
│   ├── nacos_api.py        #   Nacos 配置中心管理
│   ├── generate_var_docs.py    # 模板变量文档自动生成
│   └── _odmp_api/          #   odmp_api 内部子模块
├── docs/                   # 文档目录
│   ├── deployment.md       #   部署文档（本文档）
│   ├── template-vars.md    #   配置模板变量参考（自动生成）
│   ├── service-status.md   #   服务监控状态（自动生成）
│   └── suggestions.md      #   代码审查报告
├── conf/
│   └── template/           #   各组件配置模板目录
├── lib/                    # 本地辅助文件（不上传到目标主机）
│   ├── nginx/              #   Nginx 编译依赖（zlib / pcre / openssl）
│   ├── odmp/               #   ODMP 建模层导入文件
│   ├── packages/           #   离线 Python whl 依赖包（FastAPI、uvicorn 等）
│   └── aimeter/            #   AIMETER 辅助文件
├── requirements.txt        # Python 项目依赖
├── AGENTS.md               # 项目架构说明
├── README.md               # 项目快速开始说明
└── logs/                   # 部署日志（位于部署脚本目录下）
```

> **日志路径**：部署引擎日志保存在 `deploy/logs/` 目录下，`config-snapshots/` 也在该目录中。
> **service-status.md** 由 `service_check.py` 自动生成/追加到 `deploy/docs/service-status.md`。

`lib/nginx/` 目录存放 Nginx 源码编译依赖：

```
lib/nginx/
├── zlib-1.3.1.tar.gz        # zlib 压缩库
├── pcre-8.41.tar.gz         # PCRE 正则库
└── openssl-1.1.1g.tar.gz    # OpenSSL 加密库
```

> nginx 安装器在部署时会自动将这三个依赖包从 `lib/nginx/` 复制到 HTTP 包目录，供远程主机编译时使用。

`lib/packages/` 目录存放项目所需的离线 Python whl 依赖包，启动 Web 管理界面时自动加载：

```
lib/packages/
├── fastapi-0.115.12-py3-none-any.whl
├── uvicorn-0.34.2-py3-none-any.whl
├── pydantic-2.13.4-py3-none-any.whl
├── jinja2-3.1.6-py3-none-any.whl
├── httpx-0.28.1-py3-none-any.whl
├── kafka_python-2.2.15-py2.py3-none-any.whl
├── openpyxl-3.1.5-py2.py3-none-any.whl
├── PyMySQL-1.1.1-py3-none-any.whl
├── PyYAML-6.0.2-*.whl
├── requests-2.32.3-py3-none-any.whl
├── websockets-14.1-*.whl
├── click-8.4.1-py3-none-any.whl
├── starlette-0.46.2-py3-none-any.whl
├── python_multipart-0.0.20-py3-none-any.whl
└── ...（其他依赖）
```

> 旧版 `lib/python/`（tar.gz 格式）已废弃，迁移至 `lib/packages/` whl 格式。`lib/packages/` 在部署启动时自动通过 `pip install --no-index` 安装。

`lib/odmp/` 目录存放 ODMP ImportFlow 建模层导入的 Excel 文件，文件名与导入类型的对应关系如下：

```
lib/odmp/
├── 01-aiops_dataDomain_20260508.xlsx         # 数据域
├── 02-aiops_object_20260508.xlsx             # 对象模型
├── 03-aiops-table_20260508.xlsx              # 维度建模
├── 04-aiops-measure_20260508.xlsx            # 度量单位
├── 05-aiops-enum_20260508.xlsx               # 数据字典
├── 06-aiops-dimLabel_20260508.xlsx           # 维度标签
├── 07-aiops-objectIndicatorGroup_20260508.xlsx  # 指标模型
├── 08-aiops-objectRelationPath_20260508.xlsx    # 关系路径
├── 09-aiops-api_20260508.xlsx                # 数据服务
├── 10-aiops-objectInstance_20260508.xlsx     # 对象关系
├── 11-aiops-flexibleJob_20260508.xlsx  # 弹性作业
└── 12-aiops-dataDevelopment_20260508.zip     # 开发任务
```

> 文件名映射规则：`{序号}-AIOPS-{导入类型}_{日期}.xlsx`（或 `.zip`），导入类型由 `odmp_api.py` 中 `_FILE_PATTERN` 正则和 `_TYPE_CN_MAP` 字典解析。`dataDevelopment` 例外使用 `.zip` 格式且按关键词扫描。这些文件通过 `odmp_api.py import` 命令导入（见 §6.3）。

### 1.3 目标主机要求

#### 1.3.1 SSH 免密配置

**部署机到所有目标主机**（必须使用密钥认证）：

```bash
# 部署机上执行（如无密钥则先生成）
ssh-keygen -t rsa -b 2048 -N ""
ssh-copy-id root@192.168.1.2
ssh-copy-id root@192.168.1.3
```

**各目标主机之间**也需要免密登录（Kafka、Hadoop 等集群组件需要在节点间通过 SSH 通信）：

```bash
# 每台目标主机上执行
ssh-keygen -t rsa -b 2048 -N ""
ssh-copy-id root@<其他节点IP>
```

**DolphinScheduler 特殊要求**：部署 DolphinScheduler 的机器之间必须提前完成免密配置，包括 **本机到本机**（`ssh localhost`）和本机到集群中其他所有需要安装 DolphinScheduler 的机器。这是因为 DolphinScheduler 的 `install.sh` 脚本会通过 SSH 在节点间分发配置和启停服务。验证方法：

```bash
# 在所有 DS 节点上执行
ssh localhost "hostname"
ssh 192.168.1.2 "hostname"
ssh 192.168.1.3 "hostname"
# 以上命令均不应提示输入密码
```

#### 1.3.2 防火墙

```bash
# 所有目标主机上执行（或开放对应端口）
systemctl stop firewalld
systemctl disable firewalld
```

#### 1.3.3 系统软件

```bash
# 所有目标主机需要预装
yum install -y tar curl
```

### 1.4 上传安装包

#### 1.4.1 组件安装包（--package-dir）

各组件安装包放到 `--package-dir` 目录下，按分组结构存放：

```
{package-dir}/
├── common/              # 通用基础设施组件包
│   ├── jdk-8u201-linux-x64.tar.gz
│   ├── mysql-8.0.32-linux-glibc2.12-x86_64.tar.xz
│   ├── redis-6.2.6.tar.gz
│   ├── apache-zookeeper-3.7.0-bin.tar.gz
│   ├── kafka_2.13-3.4.0.tgz
│   ├── hadoop-3.3.5.tar.gz
│   ├── nacos-server-2.2.3.tar.gz
│   ├── ckman-3.3.3.tar.gz
│   ├── clickhouse-23.8.2.7.x86_64.rpm # RPM 包
│   ├── nebula-graph-3.6.0.tar.gz
│   ├── nebula-graph-studio-3.7.0.tar.gz
│   ├── nebula-console-*                     # Nebula Console 连接工具（必选，文件名以 nebula-console 开头即可）
│   └── nginx-1.22.1.tar.gz            # 源码包
├── sso/                 # SSO 产品包
├── odmp/                # ODMP 及其依赖包（dolphinscheduler、datax、jax-pyenv 等）
├── aimeter/             # AIMETER 产品包
├── refiner/             # REFINER 产品包
└── odc/                 # ODC 产品包
```

> **分组说明**：`--package-dir` 下必须按上述分组结构创建子目录（`common/`、`sso/`、`odmp/` 等），各组件的安装包必须放到对应的分组目录下。部署引擎会根据组件所属分组自动从对应目录查找安装包。
>
> > **已部署的服务**：如果 `mysql`、`redis`、`zookeeper`、`kafka`、`clickhouse`、`hadoop`、`nacos`、`ckman` 等核心服务已经部署好不需要再次安装，只需在 `deploy` 中配置主机地址，**不需要**在 `--package-dir` 中放置对应的安装包。部署引擎会跳过安装步骤，但仍可通过已配置的地址在部署流程中使用这些服务。

nginx 为源码包，安装器会自动完成编译安装。编译依赖包（zlib, pcre, openssl）存放在 `deploy/lib/nginx/` 下，部署时自动复制到 HTTP 包目录供远程主机下载。

**包名发现规则**：

| 组件 | 发现方式 | 说明 |
|------|---------|------|
| Java (JDK 8/11/21) | 需在 `config.yaml` 的 `packages` 中显式配置 | 文件名不含 "java" 字样 |
| ClickHouse | 如果包名不含 "clickhouse" 则需在 `packages` 中配置 |  |
| 其余组件 | 自动按组件名忽略大小写匹配 | 无需在 `packages` 中列出 |

#### 1.4.2 ODMP 算子包及 workflow 资源（job/）

ODMP 的算子包（JAR、Python 脚本、数据处理器）和 workflow 资源包放在 `--package-dir` 下的 `job/` 目录中：

```
{package-dir}/job/
├── jar/           # JAR 算子包（.jar 文件）
├── python/        # Python 算子包（.zip 文件，如 analyzer）
├── data/          # 数据服务算子包（full-monitor、data-service 等）
└── workflow/      # workflow 资源包（如 jax-integration.jar）
```

> 算子包和 workflow 资源由 `odmp_api.py ingestion` 命令在部署后上传注册（见 §6.3）。

### 1.5 更新 /etc/hosts

如果使用 Hadoop HA 或 Kafka 集群，建议在部署机和所有目标主机上配置 `/etc/hosts`：

```
192.168.1.2  node1
192.168.1.3  node2
192.168.1.4  node3
```

部署脚本会自动从部署机的 `/etc/hosts` 解析主机名用于 Hadoop 配置文件。

---

## 二、配置 config.yaml

### 2.1 安装包映射 — Java 必须手动指定版本

Java 系列（`java`/`java11`/`java21`）**必须**在 `packages` 中手动配置包名，因为其文件名不包含 "java" 字样，自动发现无法匹配。

**关键规则**：
1. `packages` 中的键名为 `java`（JDK 8）、`java11`、`java21`（有额外 JDK 11/21 安装器时）
2. 值为 _实际文件名_（含扩展名），**版本号必须和上传的安装包完全一致**
3. `java`（JDK 8）会**自动安装到所有目标主机**；`java11`/`java21` 也自动安装到所有主机
4. 不配置或文件名不匹配 → 安装器报错退出

```yaml
packages:
  java: jdk-8u201-linux-x64.tar.gz           # 版本号必须和文件一致
  java11: amazon-corretto-11.0.14.10.1-linux-x64.tar.gz
  java21: jdk-21.0.6_linux-x64_bin.tar.gz
```

其他组件（mysql / redis / zookeeper / kafka / hadoop / nacos / ckman / clickhouse / nebula / nginx 等）自动在安装包目录中按组件名忽略大小写匹配，**无需在 `packages` 中列出**。

### 2.2 其他配置项

以下配置直接在 `deploy/config.yaml` 中填写，部署文档**不再逐项说明**，以实际配置文件为准：

| 配置段 | 说明 | 注意事项 |
|--------|------|---------|
| `servers` | SSH 目标主机列表 | 推荐密钥认证；`key_file` 不指定则用默认密钥 |
| `mysql.client_components` | 需要 MySQL 客户端的组件 | 部署引擎会向这些组件所在主机自动分发 mysql CLI |
| `java_env` | 各组件使用的 Java 版本 | 不配置则全部默认使用 `java`（JDK 8） |
| `deploy` | 组件 → 主机映射 | `java`/`java11`/`java21` 自动安装在所有主机，无需在此列出；组件安装顺序由引擎自动编排，不可修改 |
| 各组件端口/密码 | mysql, redis, nacos, clickhouse 等 | 不配置则使用默认值（见 `config.yaml` 各段注释） |

> **注意事项 — 各组件主机数量要求**（部署引擎会在安装前自动校验以下规则，不满足则报错退出；不部署某组件则对应主机列表留空即可）：
> - **1 台**：mysql、nginx、ckman、nebula_studio、sso、aimeter、refiner、odc、odmp
> - **1 台或 3 台**：zookeeper、nacos、redis、nebula（2 台会被拒绝）
> - **至少 1 台**：kafka
> - **至少 2 台**：hadoop（不足 2 台会被拒绝）
> - **偶数台**（2、4、6...）：clickhouse（奇数台会被拒绝）
> - **至少 1 台**：dolphinscheduler
> - **随依赖组件自动部署**(不需要独立主机):**jax-pyenv 随 odmp、datax 随 dolphinscheduler**
>
> > **核心服务地址必须配置**：以下 8 个核心服务即使已经部署好不需要再次安装，也**必须**在 `deploy` 中配置主机地址（只是不放置对应安装包即可）。部署引擎预检查阶段会强制校验，缺失任一服务的地址配置都会报错退出：`mysql`、`redis`、`zookeeper`、`kafka`、`clickhouse`、`hadoop`、`nacos`、`ckman`。
> >
> > **ZooKeeper Admin Server 端口**：ZooKeeper 3.5+ 内嵌 Admin Server（Jetty），部署时自动写入 `admin.serverPort=8081`（通过 `config.yaml` 中 `zookeeper.admin_port` 配置，默认 8081），避免与 18080 端口冲突。

---

## 三、执行部署

> **执行目录**：以下所有命令 **必须在 `deploy/` 目录下执行**（即先 `cd deploy`），不可在项目根目录或其他目录执行。脚本中的相对路径均以此目录为基准。

### 3.1 Web 管理界面（推荐）

Web 模式启动时不需要 `--install-dir` 和 `--package-dir` 参数，可在页面中配置：

```bash
python3 install.py --localaddr 192.168.1.100 --nodesfile config.yaml --web --web-port 18080
```

启动后访问 `http://192.168.1.100:18080`，提供以下功能页面：

| 页面 | 功能 |
|------|------|
| **Dashboard** | 部署概览、组件/主机数量统计、部署历史趋势 |
| **Wizard** | 向导式组件选择和部署参数配置 |
| **Components** | 按分组展示所有组件，支持搜索和状态标记 |
| **Hosts** | 主机列表，展示各主机分配的组件和 SSH 认证方式（密钥/密码） |
| **Config** | config.yaml 在线编辑、语法校验、**章节导航**快速跳转、光标同步定位 |
| **Deploy** | 组件选择（按 Core/Common/Business Applications 分组）、安装顺序流水线展示、目标主机分配一览、4 项部署参数、执行部署、WebSocket 实时日志 |
| **Service Check** | 一键巡检组件健康状态（30s 缓存），从 config.yaml 读取真实数据，支持按状态筛选（全部/正常/异常/待检测） |
| **Service Manager** | 查看和管理目标主机上的 systemd 服务，支持 start/stop/restart/status 操作（30s 缓存，操作后自动清除） |
| **Mockdata** | Web 界面的 POC 数据模拟工具，可视化选择模块和参数，无需命令行操作 |
| **History** | 部署历史记录，支持分页浏览 |

**Deployment Parameters**（4 项）：

| 参数 | CLI 对应 | 说明 |
|------|---------|------|
| Install Dir | `--install-dir` | 安装根目录 |
| Package Dir | `--package-dir` | 安装包目录 |
| Config Dir | `--config-dir` | 配置模板目录 |
| HTTP Port | `--http-port` | HTTP 文件服务端口 |

`--localaddr` 由启动时的参数自动注入，无需在页面中填写。

### 3.2 CLI 部署模式

```bash
python3 install.py --localaddr 192.168.1.100 --nodesfile config.yaml --install-dir /data/service --package-dir /data/softs
```

### 3.3 CLI 参数说明

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--localaddr` | 是 | — | 部署机 IP（目标主机通过此地址下载安装包） |
| `--nodesfile` | 是 | — | config.yaml 配置文件路径 |
| `--install-dir` | CLI 必需 | — | 远程主机安装根目录（如 `/data/service`）；Web 模式可在页面配置 |
| `--package-dir` | CLI 可选 | `{install-dir}/pkgs` | 部署机本地安装包目录路径；Web 模式可在页面配置 |
| `--config-dir` | 否 | `conf/template/` | 配置模板目录 |
| `--http-port` | 否 | `8000` | HTTP 文件服务端口 |
| `--service` | 否 | 全部部署 | 只部署指定服务（逗号分隔，如 `redis,kafka`） |
| `--debug` | 否 | 关闭 | 调试模式：打印步骤日志，不实际执行 SSH |
| `--fail-fast` | 否 | 启用 | 任意主机失败立即终止，用 `--no-fail-fast` 禁用 |
| `--json-log` | 否 | 关闭 | 以 JSON 格式输出日志（适合 ELK 等日志平台） |
| `--web` | 否 | 关闭 | 启动 Web 管理界面（替代 CLI 部署流程） |
| `--web-port` | 否 | `18080` | Web 服务端口 |

### 3.4 部署流程

1. 解析 CLI 参数和 YAML 配置
2. 自动安装 `deploy/lib/packages/` 下的 Python whl 依赖包（`pip install --no-index`）：
   - `PyMySQL` — MySQL 数据库驱动
   - `kafka-python` — Kafka 消息队列客户端
   - `openpyxl` — Excel 文件读写
   - `fastapi` / `uvicorn` — Web 管理界面框架
   - `pydantic` / `jinja2` / `python_multipart` / `httpx` — Web 和模板支持
   - `PyYAML` 已包含在部署机 Python 环境中，无需额外安装
   - （旧版 `lib/python/` tar.gz 格式已废弃）
3. 启动 HTTP 文件服务（提供安装包下载）
4. 自动发现并注册安装器
5. 自动为每台主机添加 Java 版本
6. 执行预检查（SSH 免密验证、组件主机数量校验）
7. 在所有目标主机上并行创建公共目录
8. 按组件顺序依次部署，同组件跨主机并行：
   - 下载安装包 → 解压 → 创建软链接 → 创建 data/log 目录
   - 渲染配置模板（`${variable}` 替换）→ 保存配置快照
   - 启动服务 → 健康检查（重试 3 次）→ 清理安装包
9. 输出部署结果汇总

### 3.5 使用示例

```bash
# 指定安装包目录
python3 install.py --localaddr 192.168.1.100 --nodesfile config.yaml --install-dir /data/service --package-dir /data/softs

# 只部署 Redis 和 Kafka
python3 install.py --localaddr 192.168.1.100 --nodesfile config.yaml --install-dir /data/service --package-dir /data/softs --service redis,kafka

# 调试模式（验证配置和流程，不实际安装）
python3 install.py --localaddr 192.168.1.100 --nodesfile config.yaml --install-dir /data/service --package-dir /data/softs --debug

# 自定义 HTTP 端口
python3 install.py --localaddr 192.168.1.100 --nodesfile config.yaml --install-dir /data/service --package-dir /data/softs --http-port 8080

# JSON 日志格式
python3 install.py --localaddr 192.168.1.100 --nodesfile config.yaml --install-dir /data/service --package-dir /data/softs --json-log
```

### 3.6 安装顺序

安装引擎自动将组件分组排序：

1. **核心顺序**: `java → mysql → redis → zookeeper → kafka → hadoop → nacos → ckman → clickhouse → nebula → nebula_studio`
2. **其他通用组件**: 核心顺序之后，按字母序（如 nginx 等）
3. **固定自定义顺序**: `sso → odmp → dolphinscheduler → jax-pyenv → datax → refiner → aimeter → odc`
4. **其他自定义组件**: 最后，按字母序

同组件跨主机并行部署，组件间串行（保证依赖关系）。

---

## 四、配置模板变量

部署工具使用 `${variable}` 语法渲染配置模板。详细变量列表见 [`template-vars.md`](template-vars.md)（自动生成）。

### 4.1 通用变量（所有组件可用）

| 变量 | 说明 | 示例值 |
|------|------|--------|
| `${install_dir}` | 安装根目录 | `/data/service` |
| `${comms_dir}` | 软件安装目录 | `/data/service/comms` |
| `${component_dir}` | 当前组件软链接路径 | `/data/service/comms/redis` |
| `${log_dir}` | 当前组件日志目录 | `/data/service/comms/redis/logs` |
| `${data_dir}` | 当前组件数据目录 | `/data/service/comms/redis/data` |
| `${host_ip}` | 部署机 IP（`--localaddr`） | `192.168.1.100` |
| `${node_ip}` | 当前目标主机 IP | `192.168.1.2` |
| `${java_home}` | 默认 JDK 路径 | `/data/service/comms/java` |

### 4.2 重新生成变量文档

修改安装器后，运行以下命令更新 `docs/template-vars.md`：

```bash
python3 tools/generate_var_docs.py
```

---

## 五、远程目录结构

部署完成后，目标主机上的目录结构：

```
{install-dir}/
├── comms/                # 软件安装目录
│   ├── jdk1.8.0_201/
│   ├── java -> jdk1.8.0_201
│   ├── java11 -> jdk-11.0.14/
│   ├── java21 -> jdk-21.0.1/
│   ├── redis-6.2.6/
│   ├── redis -> redis-6.2.6
│   │   ├── data/
│   │   ├── logs/
│   │   └── conf/
│   ├── hadoop-3.3.5/
│   ├── hadoop -> hadoop-3.3.5
│   └── ...
├── apps/                 # 应用部署目录
│   ├── sso/
│   ├── odmp/
│   │   ├── dolphinscheduler/
│   │   └── datax/
│   └── ...
└── logs/                 # 各组件的日志目录
```

---

## 六、工具脚本

`tools/` 目录下的工具脚本可以在部署前后独立使用。

### 6.1 service_check.py — 组件健康巡检 & 服务监控状态

对已部署的组件执行健康检查，不依赖安装器实例。巡检结果自动记录到 `docs/service-status.md`，支持事后查阅。

```bash
# 全量巡检
python3 tools/service_check.py --nodesfile config.yaml --install-dir /data/service

# 只巡检指定组件
python3 tools/service_check.py --nodesfile config.yaml --install-dir /data/service --service redis,kafka

# 调试模式（只打印步骤，不实际执行）
python3 tools/service_check.py --nodesfile config.yaml --install-dir /data/service --debug

# 查看最近一次监控状态（不重新巡检）
python3 tools/service_check.py --status
```

**支持的检查器**：

| 组件 | 检查方式 | 说明 |
|------|---------|------|
| Java / java11 / java21 | `java -version` | 验证 JDK 安装 |
| MySQL | `SELECT 1 AS ok` | 通过 mysql CLI 连接 |
| Redis | `redis-cli ping` → PONG | 验证进程和响应 |
| Redis Sentinel | `redis-cli -p 26379 ping` | 验证哨兵进程 |
| Zookeeper | `zkServer.sh status` | 检查 Mode |
| Kafka | 端口检查 9092 | 验证监听端口 |
| Hadoop | `dfsadmin -report` + `yarn node -list` | HDFS 和 YARN 状态 |
| Nacos | HTTP API `/nacos/actuator/health` | 验证 UP 状态 |
| ckman | 端口检查 8808 | 验证监听端口 |
| ClickHouse | 通过 ckman API 查集群状态 | 所有节点 green |
| Nebula Graph | 端口检查 + 进程检查 | graphd 端口和进程 |
| Nebula Studio | 端口检查 7001 | 验证监听端口 |
| Nginx | 端口检查 | 验证监听端口 |
| SSO | 端口 + Nacos 注册检查 | 认证/网关端口 + 服务注册状态 |
| ODMP | 端口 + Nacos 注册检查 | ODMP 服务注册状态 |
| DolphinScheduler | `status-all.sh` | 解析各节点服务状态 |

巡检结果会输出到控制台，同时追加到 `docs/service-status.md`。

> Web 界面的 Service Check 页面内置 **30 秒状态缓存**，避免重复 SSH 请求。缓存由 `web/routers/service_manager.py` 中的 `_status_cache` 管理（TTL 可配置），执行启动/停止/重启等操作后自动清除相关缓存条目。

### 6.2 nacos_api.py — Nacos 配置中心管理

> 此工具一般不对外使用，由部署引擎内部集成调用；以下文档供运维参考。

发布/查询 Nacos 配置、管理密码。支持 SSH 代理模式和直连 HTTP 两种方式。

```bash
# 发布配置（通过 SSH）
python3 tools/nacos_api.py --nacos-host 192.168.1.2:8848 --ssh-host 192.168.1.100 --data-id authentication.properties --file ./app.properties

# 发布配置（直连 Nacos）
python3 tools/nacos_api.py --nacos-host 192.168.1.2:8848 --data-id authentication.properties --file ./app.properties --username nacos --password nacos

# 仅登录获取 token
python3 tools/nacos_api.py --nacos-host 192.168.1.2:8848 --action login

# 修改 Nacos 管理员密码
python3 tools/nacos_api.py --nacos-host 192.168.1.2:8848 --action change-password --old-password nacos --new-password NewPassword123
```

**CLI 参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--nacos-host` | 必填 | Nacos 地址 (IP:Port) |
| `--username` | `nacos` | Nacos 用户名 |
| `--password` | `nacos` | Nacos 密码 |
| `--action` | `publish` | 操作类型: login / publish / change-password |
| `--ssh-host` | (直连) | 通过 SSH 主机执行 curl |
| `--ssh-port` | 22 | SSH 端口 |
| `--ssh-user` | root | SSH 用户名 |
| `--data-id` | — | 配置 Data ID（publish 必填） |
| `--group` | `DEFAULT_GROUP` | 配置分组 |
| `--file` | — | 配置文件路径（publish 必填） |
| `--new-password` | — | Nacos 新密码（change-password 必填） |
| `--old-password` | `0192023A7BBD...` | Nacos 当前密码 |

**代码调用**：

```python
from tools.nacos_api import NacosConfigManager

mgr = NacosConfigManager(logger=logger)
# 直连模式
token = mgr.login('192.168.1.2:8848', 'nacos', 'nacos')
mgr.publish_config('192.168.1.2:8848', 'app.properties', content, token)
# SSH 模式
token = mgr.login('192.168.1.2:8848', 'nacos', 'nacos', ssh=ssh_client)
mgr.publish_config('192.168.1.2:8848', 'app.properties', content, token, ssh=ssh_client)
```

### 6.3 odmp_api.py — ODMP 初始化工具

封装 ODMP 的采集层（IngestionFlow）、建模层（ImportFlow）、系统配置（ConfigFlow）、数据处理配置更新（DataProcessUpdateFlow）和弹性作业配置更新（JobUpdateFlow）接口。支持作为独立 CLI 或代码导入使用。

**执行顺序（按依赖关系，从上至下依次执行）**：

```
 1. ingestion ──────────────────────────────────────────────────────
    创建基础设施：数据中心 → 注册中心(Nacos) → 数据源(MySQL/Redis/
    Kafka/Nebula/ClickHouse) → 集群 → 存储集群 → 业务分类 → 业务流
    → 注册内置算子包 → 上传本地算子包 → workflow资源包 → 授权客户端
    依赖: config.yaml（提供中间件地址）
         ↓
 2. config ────────────────────────────────────────────────────────
    系统管理配置初始化：Zookeeper / 数据缓存(Redis) / 对象模型(CK
    宽表) / Nebula 空间配置
    依赖: ingestion 创建的数据源(CK/Redis/Nebula) 和业务分类
         ↓
 3. import ────────────────────────────────────────────────────────
    建模层导入：业务分类 → 扫描 Excel → 创建 API 分组 → 导入数据域
    → 关联业务分类 → 导入 table/object/api/flexibleJob 等
    （自动触发 config + process + job 更新）
    依赖: ingestion 创建的业务分类(business-category)
         ↓
 4. process ───────────────────────────────────────────────────────
    数据处理任务配置更新：更新 streaming 任务的 Kafka 地址/group.id、
    MySQL JDBC 连接、ClickHouse JDBC 连接、指标来源 ID、集群 ID 等
    依赖: import 导入的数据开发任务和指标来源
         ↓
 5. job ───────────────────────────────────────────────────────────
    弹性作业配置更新：更新 aimeter-alert 的 Nacos 地址/密码、
    artifacts 路径
    依赖: import 导入的 aimeter-alert 弹性作业
```

**说明**：
- **大多数场景只需两步**：`ingestion` → `import`。`import` 内部会自动依次调用 `config` → `process` → `job`，无需单独执行后三个命令
- 单独执行 `config` / `process` / `job` 用于部署后调整中间件地址或重试失败的步骤，此时需确保其前置依赖已完成
- `process` 和 `job` 是幂等的 — 配置与当前值一致时不会重复提交

```bash
# 采集层初始化（数据中心、注册中心、数据源、集群、算子包、workflow 资源）
#   --package-dir: 算子包存放在 {dir}/job/{jar,python,data,workflow} 下（默认 .）
python3 tools/odmp_api.py ingestion --api 192.168.217.101:9900 --package-dir /data/softs

# 建模层导入（业务分类 + Excel 数据导入，自动触发 process + job）
#   --import-dir: 导入的 Excel 文件所在目录（默认 lib/odmp/）
#   --install-dir: flexibleJob 导入后自动更新弹性作业 artifacts，路径为 {dir}/apps/aimeter/{pkg}#app（默认 /data）
python3 tools/odmp_api.py import --api 192.168.217.101:9900 --import-dir ./lib/odmp/ --install-dir /data

# 系统管理配置初始化（Zookeeper / 数据缓存 / 对象模型等）
python3 tools/odmp_api.py config --api 192.168.217.101:9900

# 数据处理任务配置更新（Kafka / MySQL / ClickHouse 地址和指标来源）
python3 tools/odmp_api.py process --api 192.168.217.101:9900

# 弹性作业配置更新（aimeter-alert Nacos 地址/密码/artifacts）
#   --install-dir: aimeter 安装器将 alert 包拷贝到 {install-dir}/apps/aimeter/ 下（默认 /data）
python3 tools/odmp_api.py job --api 192.168.217.101:9900 --install-dir /data
```

**CLI 参数**：

| 命令 | 参数 | 说明 |
|------|------|------|
| ingestion | `--api` | ODMP API 地址 (IP:Port) |
| ingestion | `--package-dir` | 包目录，扫描 `{dir}/job/{jar,python,data,workflow}` |
| ingestion | `--list` | 列出已上传的内置算子包，不上传 |
| ingestion | `--builtin-only` | 仅注册内置算子包 |
| ingestion | `--local-only` | 仅上传本地非内置包 |
| import | `--api` | ODMP API 地址 (IP:Port) |
| import | `--import-dir` | Excel 文件所在目录（默认 `lib/odmp/`） |
| import | `--mode` | 导入模式: cover（覆盖）/ skip（跳过已存在） |
| import | `--install-dir` | 安装根目录（默认 `/data`），flexibleJob 导入后自动更新弹性作业 artifacts |
| config | `--api` | ODMP API 地址 (IP:Port) |
| process | `--api` | ODMP API 地址 (IP:Port) |
| job | `--api` | ODMP API 地址 (IP:Port) |
| job | `--install-dir` | 安装根目录（默认 `/data`），artifacts 路径为 `{dir}/apps/aimeter/{pkg}#app` |

**IngestionFlow 执行步骤**：
1. 创建数据中心
2. 注册注册中心（Nacos）
3. 创建数据源（MySQL、ClickHouse、Kafka）
4. 创建集群
5. 创建存储集群（指标集群）
6. 创建业务分类
7. 创建业务流
8. 注册内置算子包
9. 上传本地算子包
10. 上传 workflow 资源包（`job/workflow/`，如 jax-integration.jar）
11. 创建授权管理客户端

**ImportFlow 执行步骤**：
1. 查询业务分类（aiops）
2. 扫描导入文件
3. 创建 API 分组（全息监控、标准数据服务）
4. 导入数据域（dataDomain）
5. 关联数据域到业务分类
6. 执行系统配置初始化（ConfigFlow）
7. 导入其余类型（enum、measure、table、object、flexibleJob 等），每类导入后自动发布：
   - table → 发布维度建模
   - object → 发布对象模型
   - api → 上线数据服务并授权
   - dataDevelopment → 创建开发任务
8. dataDevelopment 导入完成后自动调用 **DataProcessUpdateFlow**，更新所有 streaming 任务的 Kafka/MySQL/ClickHouse 连接地址和指标来源
9. 若有 flexibleJob 导入，完成后自动调用 **JobUpdateFlow**，更新 aimeter-alert 弹性作业的 Nacos 地址/密码和 artifacts 路径

**DataProcessUpdateFlow 执行步骤**（import 完成后自动执行，也支持独立 CLI 调用）：
1. 查询 AIOPS 业务流 ID（从 /query 接口获取 BIZFLOW 节点的 nodeId）
2. 查询该业务流下所有数据开发任务（/query-list 接口）
3. 过滤出 type=streaming 的任务，跳过 type=STORAGE_CK 和 OFFLINE_WORKFLOW
4. 查询指标来源列表（/metric-source/query），建立名称到 ID 的映射
5. 对每个 streaming 任务，更新以下配置：
   - **KafkaByteSourceJob**: bootstrapServers、groupId、optsId
   - **KafkaSinkJob**: bootstrapServers
   - **SingleMetricBindJob**: dataSourceUrl、password、metricSourceId
   - **JdbcEnrichJob**: jdbcUrl、password、SQL（库名替换为 odmp）
6. metricSourceId 按任务名自动匹配：听云 → 听云、APM指标 → APM、优云 → 优云、其他 → 基础监控

**代码调用**：

```python
from tools.odmp_api import IngestionFlow, ImportFlow, ConfigFlow, DataProcessUpdateFlow, JobUpdateFlow

# 采集层初始化
flow = IngestionFlow('192.168.1.2:9900')
flow.run(package_dir='/data/softs')

# 建模层导入（自动触发 DataProcessUpdateFlow 和 JobUpdateFlow）
flow = ImportFlow('192.168.1.2:9900')
flow.run(import_dir='./lib/odmp/', install_dir='/data')

# 系统管理配置初始化
flow = ConfigFlow('192.168.1.2:9900')
flow.run(zk_connect='192.168.1.2:2181')

# 单独运行数据处理任务配置更新
flow = DataProcessUpdateFlow('192.168.1.2:9900')
flow.run()

# 单独运行弹性作业配置更新
flow = JobUpdateFlow('192.168.1.2:9900')
flow.run(install_dir='/data')
```

**JobUpdateFlow（job）** — 弹性作业配置更新：

仅修改 `name=aimeter-alert` 的弹性作业，更新 Nacos 地址/密码和 artifacts 路径。

```bash
python3 tools/odmp_api.py job --api 192.168.217.101:9900 --install-dir /data
```

**CLI 参数**：

| 命令 | 参数 | 说明 |
|------|------|------|
| job | `--api` | ODMP API 地址 (IP:Port) |
| job | `--install-dir` | 安装根目录（默认 `/data`），artifacts 路径为 `{dir}/apps/aimeter/{pkg}#app` |

**执行步骤**：
1. 从 config.yaml 读取 Nacos 地址/密码
2. 查询弹性作业列表（`POST /api/v2/ingestion/application/query`），找到 `name=aimeter-alert`
3. 获取作业详情（`GET /api/v2/ingestion/application/{id}`）
4. 从当前 artifacts URL 中提取包名，只更新目录前缀为 `{install-dir}/apps/aimeter/`
5. 更新 `settingMap.executorEnv` 中的 `NACOS_HOST` 和 `NACOS_PASSWORD`
6. 提交修改（`PUT /api/v2/ingestion/application/{id}`）

如需单独运行（import 之后或重跑）：

```python
from tools.odmp_api import DataProcessUpdateFlow, JobUpdateFlow

# 数据处理任务配置更新
flow = DataProcessUpdateFlow('192.168.1.2:9900')
flow.run()

# 弹性作业配置更新
flow = JobUpdateFlow('192.168.1.2:9900')
flow.run(install_dir='/data')
```

> **ODMP 门户认证**：ODMP 门户认证默认关闭（`authProvider: none`, `licenseProvider: none`）。如需启用统一门户认证，上传许可文件后在 ODMP 的 `application.yml` 中将 `website.security.authProvider` 改为 `unifiedAuth`、`website.security.licenseProvider` 改为 `unifiedLicense`，然后重启 ODMP 服务。

### 6.4 odmp_publish.py — ODMP 模型发布

将已导入的模型发布上线。发布流程分两步：创建发布记录（生成默认建表脚本）→ 执行发布。

```bash
# 发布维度建模
python3 tools/odmp_publish.py table --api 192.168.217.101:9900

# 发布对象建模
python3 tools/odmp_publish.py object --api 192.168.217.101:9900

# 发布数据服务
python3 tools/odmp_publish.py api --api 192.168.217.101:9900
```

**支持的模型类型**：

| 类型 | 发布器 | 说明 |
|------|--------|------|
| table | TablePublisher | 维度建模发布（支持 CLICKHOUSE / KAFKA 双平台） |
| object | ObjectPublisher | 对象建模发布 |
| api | ApiPublisher | 数据服务发布 |

**代码调用**：

```python
from tools.odmp_publish import TablePublisher
pub = TablePublisher('192.168.217.101:9900')
total, ok, fail = pub.publish_all()
```

### 6.5 update_spring_config.py — Spring 配置替换

替换 `.properties` / `.yml` / `.yaml` 文件中的 `${ENV_NAME:default_value}` 占位符。

```bash
# 1. 扫描文件，查看有哪些占位符
python3 utils/update_spring_config.py --file application.properties --scan

# 2. 替换占位符的默认值（保留 ${ENV_NAME:...} 格式）
python3 utils/update_spring_config.py --file application.properties --replace NACOS_HOST=192.168.1.100:8848 --replace MYSQL_HOST=192.168.1.100:3306

# 3. 直接替换为实际值（去掉 ${...} 包裹）
python3 utils/update_spring_config.py --file application.properties --replace NACOS_HOST=192.168.1.100:8848 --inline

# 4. 预览模式（不写入文件）
python3 utils/update_spring_config.py --file application.properties --replace NACOS_HOST=192.168.1.100:8848 --dry-run
```

### 6.6 nacos_api 代码调用 — Python 集成

```python
from tools.nacos_api import NacosConfigManager
mgr = NacosConfigManager(logger=logger)
token = mgr.login('192.168.1.2:8848', 'nacos', 'nacos')
mgr.publish_config('192.168.1.2:8848', 'app.properties', content, token)
```

### 6.7 mockdata — POC 数据模拟套件

> **注意**：`mockdata/config/common_config.yaml` 由 `install.py` 在预检查通过后自动从 `config.yaml` 推断并生成（MySQL 地址取部署 MySQL 的主机，Kafka brokers 取部署 Kafka 的所有主机 + 端口），**无需手动修改**。

位于 `mockdata/`，用于向 Kafka 和 MySQL 写入模拟的监控数据，包含 5 个数据模拟模块：

| 模块标识 | 功能 | 数据目标 |
|---------|------|---------|
| `alert` | 告警及告警规则 | Kafka |
| `metrics` | 基础设施和 APM 指标 | Kafka |
| `trans-metrics` | 交易指标（交易量、成功率等） | Kafka |
| `trans-details` | 交易链路明细 | Kafka |
| `itsm-devops` | ITSM 变更单 + DevOps 投产单 | MySQL |

**依赖的 Python 模块**（部署引擎已自动安装）：
- `pymysql` — MySQL 数据库驱动（itsm-devops 模块需要）
- `kafka-python` — Kafka 客户端（告警、指标、链路模块需要）
- `openpyxl` — Excel 文件解析（所有模块需要，用于读取对象实例 xlsx）
- `PyYAML` — YAML 配置读取

**使用方法**：

```bash
cd deploy/mockdata

# 运行全部模块
python3 run_mockdata.py

# 运行指定模块
python3 run_mockdata.py alert
python3 run_mockdata.py alert metrics trans-metrics

# 调试模式（不发送 Kafka / 不写入数据库）
python3 run_mockdata.py --debug

# 指定时间范围
python3 run_mockdata.py --start "2026-03-17 10:00:00" --end "2026-03-17 10:10:00"

详细使用说明见 [`mockdata/README.md`](mockdata/README.md)。

### 6.8 generate_var_docs.py — 模板变量文档生成

扫描所有注册的安装器，收集 `get_template_vars_doc()` 输出，自动生成 `docs/template-vars.md`。

```bash
python3 tools/generate_var_docs.py
```

每次修改安装器后运行此脚本，保持变量文档与代码同步。

---

## 七、后置操作

### 7.1 部署后巡检

```bash
python3 tools/service_check.py --nodesfile config.yaml --install-dir /data/service
```

### 7.2 Hadoop 启停

在 NN1 主机上：

```bash
cd /data/service/comms/hadoop && ./hadoop.sh start
cd /data/service/comms/hadoop && ./hadoop.sh stop
```

### 7.3 MySQL

> **注意**：MySQL 数据目录（`{install_dir}/mysql/data/`）必须确保 `mysql` 系统用户有读写权限。安装器会自动执行 `sudo mkdir` 和 `sudo chown -R mysql:mysql`，因此部署机需要能**免密码 sudo** 到目标主机。如果目标主机上 `mysql` 用户不存在，安装脚本会自动创建。

初始密码为 `MySQL@123`，已配置 root 远程访问：

```bash
mysql -u root -p'MySQL@123' -h 192.168.1.3
```

### 7.4 Nacos

- 支持 1 台（单节点）或 3 台（集群）部署
- 需要 MySQL 数据库已就绪
- 初始密码可通过 `config.yaml` 的 `nacos.password` 配置（MD5 哈希值）
- 部署完成后自动修改密码
- 健康检查端口 8848

#### 7.4.1 配置自动上传

Nacos 健康检查通过后，安装器自动将 `conf/template/nacos/conf/` 下**各子目录**中的配置文件上传到 Nacos public 空间：

- **子目录名** = Nacos Group（如 `DEFAULT_GROUP/`、`alert/`、`processor/`）
- **文件名** = DataId（如 `refinerTwo`、`origin.yaml`）
- `application.properties` 是 Nacos 自身配置文件，不参与上传，走模板渲染

上传过程中自动将模板文件中的硬编码地址替换为实际部署值，替换范围包括：
- MySQL、Redis、Kafka、ZooKeeper 的连接地址和密码
- ClickHouse HTTP/TCP 地址和密码
- Nacos 集群地址（所有节点，支持客户端 failover）
- Redis **哨兵模式**：`nodes` 中的 sentinel 地址替换为 `sentinel_servers`，`masterName` 替换为配置文件中的 `sentinel_name`
- **refinerTwo 副库密码**：`password: 123456` 替换为 MySQL 实际密码

> **自定义参数**：如需修改上传到 Nacos 的配置内容（如调整某组件的连接参数、新增配置项），直接编辑 `conf/template/nacos/conf/<Group>/<DataId>` 下的模板文件即可。安装器会在部署时自动读取并上传。`application.properties` 中的参数通过模板变量 `${variable}` 配置，在 `config.yaml` 中修改对应组件的参数即可。

> **Redis 模式切换**：模板文件中同时保留了单机和哨兵两种模式的配置结构（一种激活、一种注释）。部署前根据实际 Redis 模式，在模板文件中注释/放开对应段落即可。安装器会自动替换其中的地址和密码为实际部署值。

### 7.5 ClickHouse

通过 ckman API 部署：
- 至少需要 2 台主机，每 2 台组成一个 shard（主从副本）
- 安装包（RPM 包）放在 `--package-dir/common/` 下
- ClickHouse Keeper 节点自动选择前 3 台主机
- SSH 私钥自动从 ckman 主机复制到 ckman 安装目录

### 7.6 Nacos 密码修改

部署完成后如需手动修改 Nacos 密码：

```bash
python3 tools/nacos_api.py --nacos-host 192.168.1.2:8848 --action change-password --old-password nacos --new-password NewPassword123
```

---

## 八、常见问题

### 8.1 SSH 连接失败

- 检查 SSH 密钥是否已推送：`ssh-copy-id root@<目标IP>`
- 确认 `servers` 中配置的用户名和端口正确

### 8.2 HTTP 下载失败

- 确认 `--localaddr` 是目标主机可达的 IP（非 `127.0.0.1`）
- 检查部署机防火墙是否开放了 HTTP 端口（默认 8000）
- 确认安装包文件已放在 `--package-dir` 目录下

### 8.3 配置文件未更新

`--config-dir` 默认值为 `conf/template/`，模板更改后确认文件路径正确。

### 8.4 部署中断后恢复

当前版本不支持幂等部署。推荐做法：
1. 查看日志定位中断原因并修复
2. 使用 `--service` 参数只重新部署失败的组件
3. 如需完全重来，手动清理远程主机的 `comms/` 目录后重新执行

### 8.5 各组件健康检查失败排查

| 组件 | 常见原因 | 排查方法 |
|------|---------|---------|
| MySQL | 数据目录权限、端口冲突 | 检查 `/etc/mycf` 中 `log-error` 路径 |
| Redis | 密码不匹配、端口被占用 | `ps aux | grep redis` |
| Zookeeper | 配置目录错误、JAVA_HOME | `zkServer.sh status` 查看错误 |
| Kafka | ZK 未就绪、broker.id 重复 | 检查 `logs/server.log` |
| Hadoop | SSH 免密未配置 | 先用 `--debug` 验证配置 |
| Nacos | MySQL 未就绪、DB 未初始化 | 检查 `logs/nacos.log` |
| ClickHouse | ckman 未就绪 | 检查 ckman Web UI |
| DolphinScheduler | 配置错误 | 检查各服务日志 |

### 8.6 JSON 日志格式

使用 `--json-log` 参数输出结构化日志，适合对接 ELK、Splunk 等平台：

```json
{"timestamp": "2026-05-14 09:11:35", "level": "INFO", "component": "redis", "host": "192.168.1.2", "message": "Redis 安装完成"}
```
