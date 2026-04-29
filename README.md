# Network Device MCP - 网络设备只读查询服务

一个基于 [MCP（Model Context Protocol）](https://modelcontextprotocol.io/) 的网络设备只读查询服务。让 AI 助手（如 Claude）能够安全地通过 SSH 查询交换机、路由器、防火墙、无线控制器等网络设备的运行状态，**绝对不会执行任何配置变更命令**。

## 它能做什么？

**用自然语言让 AI 帮你查网络设备：**

| 你对 AI 说 | AI 实际做的事 |
|-----------|-------------|
| "帮我看看这台交换机的版本" | 调用 `show_version` 查询设备信息 |
| "哪些接口是 UP 的？" | 调用 `show_ip_interface_brief`，分析输出筛选 UP 接口 |
| "帮我巡检一下这台设备" | 一次连接执行版本、CPU、内存、接口等多条命令，汇总报告 |
| "这 10 台设备的 CPU 使用率怎么样？" | 并发查询 10 台设备，汇总对比 |
| "从这台设备 ping 一下 10.0.0.1" | 调用 `ping` 命令并解读结果 |
| "帮我对比两台设备的路由表" | 分别查询后对比差异 |

**支持 10 个平台，318 条只读命令：**

| 平台 | 命令数 | 说明 |
|------|--------|------|
| Cisco IOS/IOS-XE | 70 | 交换机、路由器 |
| Cisco ASA | 28 | 防火墙（xlate、conn、failover、VPN） |
| Cisco NX-OS | 31 | 数据中心交换机（vPC、port-channel） |
| Huawei VRP | 44 | 交换机、路由器、无线 AC |
| H3C Comware | 33 | 交换机、无线 AC |
| Fortinet FortiGate | 20 | 防火墙（策略、VPN、HA） |
| Aruba | 19 | 无线控制器（AP、射频、客户端） |
| Juniper JunOS | 30 | 路由器、SRX 防火墙（安全域、集群） |
| Ruijie | 22 | 交换机、路由器 |
| Ruckus FastIron | 21 | ICX 交换机 |

## 它是怎么工作的？

```
用户 ──自然语言──> AI 助手（Claude）──MCP/SSE──> 本服务 ──SSH──> 网络设备
                  AI 选择命令并填参数            校验+拼装+执行     返回原始输出
                  AI 分析结果回答用户  <────────  返回结果  <──────
```

**关键设计：AI 不能自由输入命令。** AI 只能从预定义的 318 条命令菜单中选择 `command_id`，服务端负责拼装和执行。这从根本上杜绝了 AI 构造危险命令的可能。

## 安全机制

采用 5 层纵深防御，所有校验在 SSH 连接建立**之前**完成：

1. **封闭命令集** — AI 只能从 `config/commands.yaml` 中选择命令，不能自由输入
2. **参数类型校验** — ip_address（IPv4 校验）/ string（正则匹配）/ integer（范围约束）
3. **注入字符拦截** — 参数值禁止 `; | & $ \n` 等 Shell 特殊字符
4. **服务端拼装** — 命令主体锁死在配置文件中，AI 只能补充参数值
5. **兜底黑名单** — 拼装后的命令仍检查 `configure`、`system-view`、`delete`、`reboot` 等危险关键词

被拦截的操作会记录到审计日志（`logs/audit.log`），每行一条 JSON。

---

## 快速开始

### 1. 部署服务端

将项目部署到一台能 SSH 访问网络设备的服务器上：

```bash
# 克隆项目
git clone https://github.com/gj-hat/network-device-mcp.git
cd network-device-mcp

# 配置 SSH 凭据
cp .env.example .env
# 编辑 .env，填入 SSH 用户名和密码

# 启动服务（首次自动创建 venv 并安装依赖）
./start.sh
```

服务启动后监听 `http://0.0.0.0:8081/sse`。

### 2. 配置 AI 客户端

在 Claude Code（或其他支持 MCP 的 AI 客户端）的配置中添加：

```json
{
  "mcpServers": {
    "network-readonly": {
      "type": "sse",
      "url": "http://你的服务器IP:8081/sse"
    }
  }
}
```

### 3. 开始使用

连接成功后，直接用自然语言和 AI 对话即可：

```
> 帮我看看 192.168.1.1 这台华为交换机的版本和 CPU 使用率

AI 会自动：
1. 调用 list_available_commands 获取华为命令菜单
2. 选择 display_version 和 display_cpu_usage
3. 通过 execute_multi_commands 一次连接执行两条命令
4. 分析结果，用自然语言告诉你
```

---

## 4 个 MCP 工具

| 工具 | 用途 | 适用场景 |
|------|------|---------|
| `list_available_commands` | 查看指定设备类型的可用命令菜单 | 了解可用命令 |
| `execute_readonly_command` | 对单台设备执行一条只读命令 | 简单查询 |
| `batch_execute_readonly_command` | 对多台设备并发执行同一条只读命令 | 批量查询 |
| `execute_multi_commands` | 对单/多台设备执行多条只读命令（单连接） | 巡检 |

### execute_multi_commands - 巡检场景

一次 SSH 连接执行多条命令，减少重复建连开销：

```json
{
  "host": "192.168.1.1",
  "device_type": "huawei",
  "commands": [
    {"command_id": "display_version"},
    {"command_id": "display_cpu_usage"},
    {"command_id": "display_ip_interface_brief"},
    {"command_id": "display_arp"}
  ]
}
```

- 每条命令独立校验，某条失败不影响其他命令
- 支持 `host`（单台）或 `hosts`（多台）二选一，多台设备间并发
- 每条命令的结果独立返回，包含 `command_id` 对应关系

---

## 项目结构

```
network-device-mcp/
├── start.sh                        # 一键启动脚本
├── config/
│   └── commands.yaml               # 命令封闭集合（10 平台 318 条命令）
├── src/
│   ├── server.py                   # MCP 服务入口（FastMCP + SSE 传输）
│   ├── requirements.txt            # Python 依赖
│   ├── core/                       # 基础设施层
│   │   ├── config.py               #   全局配置常量
│   │   └── audit.py                #   JSON 行审计日志
│   ├── commands/                   # 命令解析层
│   │   └── registry.py             #   YAML 加载 + 参数校验 + 命令拼装
│   ├── security/                   # 安全校验层
│   │   ├── validator.py            #   注入字符检测 + 兜底危险关键词黑名单
│   │   └── credential.py           #   凭据管理（.env 默认 + 客户端覆盖）
│   ├── executor/                   # SSH 执行层
│   │   └── ssh.py                  #   netmiko 异步执行 + 并发控制
│   └── tools/                      # MCP 工具层（对外接口）
│       └── handlers.py             #   4 个 MCP 工具定义（编排层）
├── logs/
│   └── audit.log                   # 审计日志输出
├── .env                            # SSH 默认凭据（不入版本控制）
├── .env.example                    # 凭据格式示例
└── docs/                           # 产品与架构设计文档
```

## 配置说明

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SSH_USERNAME` | - | SSH 默认用户名（必填） |
| `SSH_PASSWORD` | - | SSH 默认密码（必填） |
| `SSH_TIMEOUT` | 30 | SSH 超时秒数 |
| `MCP_HOST` | 0.0.0.0 | 服务监听地址 |
| `MCP_PORT` | 8081 | 服务监听端口 |
| `MAX_CONCURRENCY` | 50 | 批量查询最大并发数 |

### 凭据优先级

客户端调用工具时可传入 `username` / `password` 参数覆盖默认凭据：

```
客户端传入 > 服务端 .env 默认值
```

### 扩展命令

编辑 `config/commands.yaml`，在对应设备类型下新增条目即可，无需修改代码：

```yaml
cisco:
  - id: show_mac_table
    name: "查看 MAC 地址表"
    description: "显示设备 MAC 地址表"
    command: "show mac address-table"
```

### 设备类型映射

| 本系统 | netmiko device_type |
|--------|---------------------|
| cisco | cisco_ios |
| cisco_asa | cisco_asa |
| cisco_nxos | cisco_nxos |
| huawei | huawei_vrp |
| h3c | hp_comware |
| fortinet | fortinet |
| aruba | aruba_os |
| juniper | juniper_junos |
| ruijie | ruijie_os |
| ruckus | ruckus_fastiron |

---

## 技术栈

- Python 3.10+
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)（FastMCP + SSE）
- [netmiko](https://github.com/ktbyers/netmiko)（SSH 多厂商设备连接）
- asyncio.to_thread（同步 SSH 转异步）+ Semaphore（并发控制）
