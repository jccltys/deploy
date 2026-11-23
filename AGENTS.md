<!-- 全局规范: ~/trae/projects/AGENTS.md -->
# deploy
> 本项目遵循全局规范，核心规则内联如下：
- 缩进：4 空格，命名：snake_case / camelCase
- 禁止硬编码凭证，SQL 用参数化查询

# AGENTS.md

## 入口

```bash
# CLI 部署模式（传统）
python3 install.py --localaddr 192.168.217.100 --nodesfile config.yaml --install-dir /data/service --package-dir /data/softs

# Web 管理界面（推荐）
python3 install.py --web --web-port 18080 --nodesfile config.yaml --localaddr 192.168.217.100
```

所有 CLI 参数：

| 参数 | 默认值 |
|------|--------|
| `--localaddr` | **(必填)** |
| `--nodesfile` | **(必填)** |
| `--install-dir` | **(必填)** |
| `--package-dir` | **(必填)** |
| `--config-dir` | `conf/template/` |
| `--http-port` | `8000` |
| `--service` | 无（部署全部） |
| `--debug` | 关闭（仅打印步骤，不实际执行） |
| `--fail-fast` | 开启（出错即停；`--no-fail-fast` 禁用） |
| `--json-log` | 关闭（JSON 格式日志供 ELK 采集） |
| `--web` | 关闭（启动 Web 管理界面替代 CLI 部署） |
| `--web-port` | `18080` |

> 所有命令必须在 `deploy/` 目录下执行。

示例：
```bash
python3 install.py --localaddr 192.168.217.100 --nodesfile config.yaml --install-dir /data/service --package-dir /data/softs
python3 install.py --localaddr 192.168.217.100 --nodesfile config.yaml --install-dir /data/service --package-dir /data/softs --http-port 8080
python3 install.py --localaddr 192.168.217.100 --nodesfile config.yaml --install-dir /data/service --package-dir /data/softs --service redis
python3 install.py --localaddr 192.168.217.100 --nodesfile config.yaml --install-dir /data/service --package-dir /data/softs --debug
```

## 架构

`install.py` → 解析 YAML 配置 → 启动 HTTP 文件服务 → 每个组件**在所有主机上并行部署** → 下一个组件（按顺序依次推进）。

- **预检查**：`core/precheck.py` 验证 SSH 连通性、主机数量要求，以及 8 个核心服务（mysql, redis, zookeeper, kafka, clickhouse, hadoop, nacos, ckman）的**必填地址配置**。缺少任何必要地址都会立即退出。

- **组件按序部署**：
  1. **Core（按序）**：`java → mysql → redis → zookeeper → kafka → hadoop → nacos → ckman → clickhouse → nebula → nebula_studio`
  2. **Other common（字母序）**：其余通用基础设施，如 `nginx` 等，在 core 之后、自定义应用之前部署
  3. **Custom（按序）**：`sso → odmp → dolphinscheduler → jax-pyenv → datax → refiner → aimeter → odc`
  4. **Other custom（字母序）**：其余未归类的分组。所有主机完成当前组件后才进入下一个组件。

- **安装器**按产品域分组在 `installers/<group>/` 下：`installers/common/`（通用基础设施组件 + `base_installer.py`）、`installers/sso/`、`installers/odmp/`、`installers/aimeter/`、`installers/refiner/`、`installers/odc/`（产品特定组件各一个）。安装器通过递归扫描自动发现，分组从目录路径推断。

- **安装包**按相同分组结构放在 `--package-dir/<group>/`（如 `softs/common/`、`softs/sso/`）。ODMP 算子包（JAR/Python/data）放在 `job/{jar,python,data}/` 下，workflow 资源包放在 `job/workflow/` 下。

- **`--service`** 参数跳过未指定的组件。**HTTP 文件服务**（`core/http_server.py`）提供安装包目录的下载服务，远程主机通过 `curl` 下载（支持子目录路径）。**SSH**（`core/ssh_client.py`）使用 `subprocess` + 系统 `ssh` 命令（无需 `paramiko`），密钥认证。

- **CLI 工具**在 `tools/` 下：
  - `odmp_api.py` — 5 个子命令：`ingestion`（采集层初始化）、`import`（建模层导入，自动触发 process+job）、`config`（系统配置）、`process`（数据处理任务配置更新）、`job`（弹性作业配置更新）
  - `odmp_publish.py` — 模型发布（table/object/api）
  - `service_check.py` — 部署后组件健康检查
  - `nacos_api.py` — Nacos 配置管理
  - `generate_var_docs.py` — 自动生成模板变量文档

## 配置模板

所有配置都在单一 YAML 文件（`config.yaml`）中。主要章节：

| 章节 | 用途 |
|------|------|
| `packages` | 服务名 → 实际文件名映射（支持 `.tar.gz`、`.tar.xz`、`.tgz` 等） |
| `servers` | SSH 主机定义 |
| `deploy` | 主机 → 组件列表映射 |
| `http_port` | HTTP 服务端口（默认 8000） |

- 日志路径：`{install_dir}/{component}/logs`；数据路径：`{install_dir}/{component}/data`；远程下载和解压路径：`{install_dir}/comms/`（安装包下载和解压在同一目录）
- 每个带版本号的解压目录会创建软链接：`comms/kafka -> comms/kafka-3.6.0`
- 配置模板放在 `conf/template/<component>/` 下，保持相对路径结构。模板文件使用 `{variable}` 替换（`{host_ip}`、`{data_dir}`、`{redis_password}` 等）
- Java 包命名灵活——在 `packages` 映射中配置即可，版本号从解压目录名自动检测
- **`java`（JDK 8）自动安装到每台主机**。如果安装器存在，`java11`/`java21` 也会自动安装到每台主机。两者可共存——`JAVA_HOME` 指向默认的 `java`
- 唯一的外部依赖是 `PyYAML`——它已包含在默认 Python 环境中，无需手动安装。Python 离线依赖包（`deploy/lib/packages/`）在部署启动时自动安装：`PyMySQL`、`kafka-python`、`openpyxl`

## 依赖

系统要求：`ssh`、`tar`、`curl`。

## 模板变量

配置模板使用 `{variable}` 替换。每个安装器通过 `get_template_vars_doc()` 类方法暴露支持的变量。

- **查看生成的文档**：完整参考见 [`docs/template-vars.md`](deploy/docs/template-vars.md)（自动生成）。
- **重新生成文档**：`python3 tools/generate_var_docs.py`，该命令扫描所有已注册的安装器，收集其 `get_template_vars_doc()` 输出，并重写 `deploy/docs/template-vars.md`。

## 服务检查

部署后，运行独立健康检查脚本验证所有服务：

```bash
python3 tools/service_check.py --nodesfile config.yaml --install-dir /data/service
python3 tools/service_check.py --nodesfile config.yaml --install-dir /data/service --service redis,kafka
python3 tools/service_check.py --nodesfile config.yaml --install-dir /data/service --debug
```

支持的检查器：`redis`、`nginx`、`zookeeper`、`kafka`、`mysql`、`hadoop`、`ckman`、`nacos`、`clickhouse`、`nebula`、`nebula_studio`、`java` / `java11` / `java21`。

## 注意事项

- **ClickHouse 数据目录权限**：非 root 安装时（`servers` 中配置了非 root 的 SSH 用户），`clickhouse` 用户必须对数据目录（config.yaml `clickhouse.path`，默认 `/data/clickhouse/`）具备读写权限，否则安装 clickhouse 会失败。

## 项目打包

分发部署时打包为 `deployhub.tar.gz`，顶层为 `deploy/` 目录：

```bash
# 打包命令（在项目目录上级执行，无需临时目录中转）
tar -czf /Users/jiacong/trae/deployhub.tar.gz \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='node_modules' \
  --exclude='.playwright-mcp' \
  --exclude='.opencode' \
  --exclude='.codegraph' \
  --exclude='.sisyphus' \
  --exclude='.comet' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='AGENTS.md' \
  --exclude='logs' \
  --exclude='.gitignore' \
  --exclude='.vscode' \
  --exclude='frontend' \
  --exclude='openspec' \
  --exclude='docs/superpowers' \
  --exclude='prompts.json' \
  --exclude='tests' \
  -s '/^install/deploy/' \
  install
```

解压后得到 `deploy/` 目录，在 `deploy/` 下执行所有命令。

## Git Remote

> 本项目 Git remote 名为 `test.git`（origin → https://github.com/jccltys/test.git）。
