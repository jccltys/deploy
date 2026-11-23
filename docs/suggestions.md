# 审查报告

> **审查日期**: 2026-06-03
> **审查范围**: deploy/ 全部核心模块（install.py, base_installer.py, ssh_client.py, http_server.py, logger.py, config/parser.py, 全部 installer 及测试）
> **兼容性约束**: Python 3.6+（不引入 3.6 标准库未包含的模块）

---

## 一、设计哲学

本系统不是配置管理（CM）工具，而是**离线内网一次性部署工具**。其设计核心原则：

- **极简依赖**: 仅依赖 PyYAML + 系统 ssh/tar/curl，在离线环境零摩擦启动
- **自包含**: 单脚本 + 包目录即可运行，无需在目标主机预装任何 agent
- **声明式**: 通过 `config.yaml` 声明"哪些主机装什么组件"，引擎自动编排顺序
- **可审计**: 每次部署的配置文件快照保存到本地，支持事后追溯

---

## 二、核心设计决策（及原因）

### 2.1 SSH 每次新建连接（不复用 ControlMaster）

**设计选择**: `ssh_client.py:5` 明确注释 — "每次请求建立独立 TCP 连接（不复用 ControlMaster），避免 socket 残留导致卡死"

**原因**:
- 避免长时间部署中 ControlMaster socket 文件残留或权限问题
- 避免网络闪断后复用脏连接导致命令 hang 住
- 简单可预期：每条命令一个独立进程，调试和排障更直观

**影响**: 大规模场景（100+ 主机）下 TCP 握手开销增加，但在此系统的目标场景（通常 <20 台）中可接受。

### 2.2 密码通过模板配置管理

**设计选择**: 初始密码直接写入配置模板文件，而非通过外部 vault 或命令行注入。

**原因**:
- 内网离线环境通常无 Vault/KMS 基础设施
- 密码修改只需更新模板文件，重新部署即可生效
- 符合"一次性部署"定位

### 2.3 无幂等性

**设计选择**: 每次运行都会重新下载、解压、覆盖配置。

**原因**: "一次性部署"场景下，重复执行的概率极低。如需重试，使用 `--service` 参数只重新部署失败组件即可。

---

## 三、已完成的优化

| # | 优化项 | 涉及文件 |
|---|--------|---------|
| 1 | Shell 命令注入防护：所有路径参数使用 `shlex.quote()` | 全部 installer + base_installer |
| 2 | health_check 失败阻断部署：失败改为 `raise RuntimeError` | Redis/MySQL/ZK/Kafka/Hadoop |
| 3 | curl 下载重试：`--retry 3 --retry-delay 5` | `base_installer.py` |
| 4 | 网络容错增强：ServerAlive + TCPKeepAlive 配置 | `ssh_client.py` |
| 5 | 关键路径错误检查：`execute(check=True)` 用于配置写入等 | `base_installer.py` |
| 6 | Hadoop 串行渲染：NN1 先渲染，其余节点等待 `.nn1.done` | `hadoop_installer.py` |
| 7 | ThreadingHTTPServer：支持并发下载 | `http_server.py` |
| 8 | Kafka 集群配置内聚到 Installer：移除 `install.py` 中的特判 | `kafka_installer.py` + `install.py` |
| 9 | Hadoop 配置备份时间戳化：`{dir}.bak.20260514_120000` | `hadoop_installer.py` |
| 10 | 配置版本化快照：渲染后保存到 `config-snapshots/{component}/{ip}/` | `base_installer.py` |
| 11 | base64 命令日志静默：`log_command=False` 避免刷屏 | `ssh_client.py` + `base_installer.py` |
| 12 | 结构化日志（JSON）：支持 `--json-log` 开关 | `logger.py` + `install.py` + `base_installer.py` |
| 13 | **cfg 字典拆分**：拆分为 `DeployConfig`（只读）+ `RuntimeContext`（可变） | `base_installer.py` + `install.py` + 全部 installer |
| 14 | **模板变量文档自动化**：`get_template_vars_doc()` + 自动生成脚本 | `base_installer.py` + Hadoop/Nginx installer + `tools/generate_var_docs.py` |
| 15 | **模板目录重组**：从 `config/template/` 移到 `conf/template/` | `install.py` + `service_check.py` + 文档 |
| 16 | **Nacos 四阶段部署**：并行准备 → 首台 DB 初始化 → 依次启动 → 统一检查 | `install.py` + `nacos_installer.py` + `core/mysql_db.py` |
| 17 | **ClickHouse 通过 ckman API 部署**：上传 RPM → API 创建集群 | `clickhouse_installer.py` + `core/ckman_api.py` |
| 18 | **NebulaGraph 集群部署**：支持 1/3 节点，自动复制 .default 配置 | `nebula_installer.py` |
| 19 | **部署前预检查**：SSH 免密验证 + 组件主机数量校验 | `core/precheck.py` + `install.py` |
| 20 | **健康检查模块拆分**：从 base_installer 抽离为独立 `core/health_check.py` | `core/health_check.py` |
| 21 | **fail-fast 默认启用**：任意主机失败终止部署，通过 `--no-fail-fast` 禁用 | `install.py` |
| 22 | **Nacos 集群健康检查**：通过 HTTP API 验证，支持 3 节点 | `utils/health.py` + `install.py` |
| 23 | **额外 Java 版本自动安装**：有安装器的 Java 版本自动安装到所有主机 | `install.py` |
| 24 | **Nebula Console 自动发现**：包目录按 `nebula-console` 前缀匹配文件名 | `nebula_installer.py` |
| 25 | **自定义产品安装器扩展**：新增 ODMP、SSO、DolphinScheduler、DataX、JaxPyEnv 安装器 | `installers/odmp/` + `installers/sso/` |

---

## 四、剩余风险与待优化项

### P1 — 建议尽快处理

| # | 问题 | 说明 | 位置 |
|---|------|------|------|
| 1 | **单元测试已移除** | 不再使用测试 | — |
| 2 | **HTTP 服务无认证** | 绑定 `0.0.0.0`，任意能访问部署机端口的第三方可下载安装包 | `http_server.py` |
| 3 | **ClickHouse 包名匹配脆弱** | 通过 `glob` 大小写不敏感模式匹配，对包名格式敏感 | `clickhouse_installer.py:51` |

### P2 — 中期可优化

| # | 问题 | 说明 | 位置 |
|---|------|------|------|
| 4 | **默认组件顺序硬编码** | 标准组件顺序由 `DEFAULT_INSTALL_ORDER` 固定 | `install.py:80` |
| 5 | **`safe_substitute` 不报错** | `Template.safe_substitute()` 在变量缺失时静默保留 `${var}` | `base_installer.py` |
| 6 | **变量名 `vars` 遮蔽内置函数** | `vars = self.template_vars()` 覆盖了 `vars()` | `base_installer.py`（各 installer 中均有） |
| 7 | **部署机 `/etc/hosts` 隐式依赖** | Hadoop 从本地 hosts 解析主机名，部署机可能缺少集群 hosts 记录 | `hadoop_installer.py:100` |
| 8 | **无回滚机制** | 新版本部署失败后无法自动恢复软链接到上一版本 | 全局 |
| 9 | **RPC 端口隐式使用 8020** | HDFS 配置中 NN 使用 8020，需确认与现有环境无冲突 | `hadoop_installer.py:271` |
| 10 | **Nacos 集群 MySQL 依赖** | 3 节点 Nacos 集群依赖 MySQL，MySQL 需先部署 | `nacos_installer.py` |

### P3 — 长期优化方向

| # | 建议 | 说明 |
|---|------|------|
| 11 | **组件依赖声明式管理** | 在安装器上声明 `depends_on`，自动拓扑排序消除 `DEFAULT_INSTALL_ORDER` |
| 12 | **服务进程启动后等待 PID** | Redis 等用 `nohup ... &` 启动的服务，启动后应等待 PID 文件出现 |
| 13 | **`--debug` 模式增强** | 当前仅跳过 SSH 执行，应扩展为完整的本地配置校验 |
| 14 | **远程端口预检** | 启动服务前用 `ss -tlnp` 检查端口占用，替代被动等待 `wait_for_port` 超时 |
| 15 | **NebulaGraph 模板化配置** | 当前通过 `sed` 替换配置文件，建议改为模板渲染 |

---

## 五、架构优劣评估

### 5.1 优势

| 方面 | 说明 |
|------|------|
| **Installer 发现机制** | 递归扫描 + 类名约定自动注册，新增组件只需放文件、继承基类、设 `GROUP`，无需修改注册表 |
| **模板系统务实** | `string.Template.safe_substitute` + base64 传输避免 shell 转义地狱，配置快照可审计 |
| **Hadoop 编排深度** | NN1/NN2 协调、ZKFC 格式化、JournalNode 启动顺序、屏障同步（`.nn1.done` / `.config.done`） |
| **分组包目录** | 支持 `--package-dir/{group}/` 分组隔离（如 `softs/common/`、`softs/sso/`） |
| **cfg 拆分** | `DeployConfig` + `RuntimeContext` 职责分离，避免全局可变字典混乱 |
| **Nacos 分阶段部署** | 并行准备 → 首台 DB 初始化 → 依次启动 → 统一检查，适应集群启动顺序要求 |
| **ClickHouse 通过 ckman API** | 复用 ckman 集群管理能力，上传 RPM 包 + API 创建分片集群 |
| **NebulaGraph 配置自动化** | 自动复制 .default 配置并 sed 替换 meta_server_addrs/local_ip |
| **部署前预检查** | SSH 免密验证 + 组件主机数量校验，提前暴露配置错误 |
| **健康检查模块化** | 检查器从 base_installer 抽离为独立模块，供部署和巡检脚本复用 |

### 5.2 限制

| 方面 | 说明 | 建议 |
|------|------|------|
| **组件间串行** | 默认顺序硬编码，无依赖图，只有线性顺序 | 当前场景足够；如需复杂依赖，可考虑引入 DAG |
| **模板能力有限** | `string.Template` 只支持 `${var}`，不支持条件/循环 | 当前场景足够；复杂逻辑可通过 installer 代码生成 |
| **线程异常隔离弱** | 线程异常只记录为 `failed`，无重试、无回滚 | 使用 `--fail-fast` 可快速止损 |
| **无幂等性** | 每次部署都重新下载、解压、渲染 | 符合"一次性部署"定位 |

---

## 六、扩展性评估

**50+ 组件**: 可以工作，Installer 发现（`os.walk` + `importlib`）50 次量级无压力。部署总时长串行无法避免（50 × 2min ≈ 100min）。

**100+ 主机**: 会遇到**连接风暴**（每台主机一个线程同时 fork `ssh` 子进程）。建议加 `threading.Semaphore(MAX_WORKERS)` 限制并发数。

---

## 七、与 Ansible / SaltStack 对比

| 维度 | 本系统 | Ansible | SaltStack |
|------|--------|---------|-----------|
| **定位** | 一次性离线部署 | 持续配置管理 | 持续配置管理 |
| **目标机依赖** | 仅需 ssh/tar/curl | 需 Python + 预装 Ansible | 需 Python + ZeroMQ |
| **离线能力** | ✅ 极强 | ❌ 需预装 | ❌ 需预装 |
| **幂等性** | ❌ 无 | ✅ 内置 | ✅ 内置 |
| **模板能力** | `string.Template` | Jinja2 | Jinja2 |
| **并发控制** | threading.Thread | 可配置 forks | 事件驱动 |
| **社区生态** | 无 | 3000+ 模块 | 大量 module |

**独特价值**: 在"内网无外网、目标机无 Python、只需部署一次"的场景下更轻量。

---

## 八、测试覆盖情况

测试已移除，不再使用。

---

## 九、代码质量检查清单

| 维度 | 状态 | 说明 |
|------|------|------|
| 代码风格（PEP8） | ✅ | 命名规范、格式统一 |
| 日志覆盖 | ✅ | 关键步骤有 INFO 日志、DEBUG 日志详细 |
| shlex.quote() 覆盖 | ✅ | 所有路径参数已转义 |
| health_check 覆盖 | ✅ | 16 个检查器覆盖所有有服务的组件 |
| 端口自动读取 | ✅ | `_get_port_from_template` 从模板文件读取 |
| 密码管理 | ⚠️ | 测试环境硬编码，用于快速部署，生产需换 |
| 测试覆盖 | ❌ | 覆盖率低（仅 3 个测试文件） |
| 幂等性 | ❌ | 不支持重复部署跳过 |
| 回滚机制 | ❌ | 无自动回滚 |
| 依赖管理 | ⚠️ | 标准组件硬编码顺序，自定义组件自动收集 |
| SSH 连接复用 | ❌ | 每次新建独立连接，不复用 ControlMaster |
| 配置版本化 | ✅ | `config-snapshots/` 目录快照 |
| cfg 拆分 | ✅ | `DeployConfig` + `RuntimeContext` 已实现 |
| 变量文档自动化 | ✅ | `get_template_vars_doc()` + 自动生成脚本 |

---

## 十、各组件健康检查覆盖

| 组件 | 检查方式 | 失败处理 |
|------|---------|---------|
| Java | `java -version` | `raise RuntimeError` |
| MySQL | `SELECT 1 AS ok` | `raise RuntimeError` |
| Redis | `redis-cli ping` → PONG | `raise RuntimeError` |
| Redis Sentinel | `redis-cli -p 26379 ping` | `raise RuntimeError` |
| Zookeeper | `zkServer.sh status` → Mode: | `raise RuntimeError` |
| Kafka | `wait_for_port` 9092 | `wait_for_port` 超时报错 |
| Hadoop | `dfsadmin -report` + `yarn node -list` | `raise RuntimeError` |
| Nacos | HTTP GET `/nacos/actuator/health` | `raise RuntimeError`（重试 3 次，间隔 60s） |
| ckman | `wait_for_port` 8808 | `wait_for_port` 超时报错 |
| ClickHouse | 通过 ckman API 查集群状态 | `raise RuntimeError`（所有节点需 green） |
| NebulaGraph | `nebula-console SHOW HOSTS` | `raise RuntimeError` |
| Nebula Studio | `wait_for_port` 7001 | `wait_for_port` 超时报错 |
| Nginx | `pgrep -f 'nginx: master process'` | `raise RuntimeError` |
| SSO | 端口 + Nacos 注册检查 | `raise RuntimeError` |
| ODMP | 端口 + Nacos 注册检查 | `raise RuntimeError` |
| DolphinScheduler | `status-all.sh` 解析各节点服务 | `raise RuntimeError` |

---

## 十一、结论

本系统在**离线内网一次性部署**场景下设计合理，Installer 发现机制和模板系统简洁有效。截至当前版本，支持 **15 个通用基础组件 + 8 个自定义产品安装器**（SSO、ODMP、DolphinScheduler、DataX、JaxPyEnv、AIMETER、REFINER、ODC），覆盖大数据基础组件和 ClickHouse/Nacos/NebulaGraph 等新兴系统。

核心风险不在于设计本身，而在于**使用场景错配**：

- ✅ 适用: 离线环境、<50 组件、<50 主机、一次性部署
- ❌ 不适用: 需要持续运维、>100 主机、频繁变更、需要幂等性

如场景匹配，当前架构无需大规模重构；如场景不匹配，建议迁移到 Ansible/SaltStack。
