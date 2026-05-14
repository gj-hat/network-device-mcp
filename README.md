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

**支持 10 个平台，332 条只读命令：**

| 平台 | 命令数 | 说明 |
|------|--------|------|
| Cisco IOS/IOS-XE | 70 | 交换机、路由器 |
| Cisco ASA | 28 | 防火墙（xlate、conn、failover、VPN） |
| Cisco NX-OS | 31 | 数据中心交换机（vPC、port-channel） |
| Huawei VRP | 44 | 交换机、路由器、无线 AC |
| H3C Comware | 43 | 交换机、无线 AC、VPN 路由 |
| Fortinet FortiGate | 20 | 防火墙（策略、VPN、HA） |
| Aruba | 23 | 无线控制器（AP、射频、客户端） |
| Juniper JunOS | 30 | 路由器、SRX 防火墙（安全域、集群） |
| Ruijie | 22 | 交换机、路由器 |
| Ruckus FastIron | 21 | ICX 交换机 |

## 它是怎么工作的？

```
用户 ──自然语言──> AI 助手（Claude）──MCP/SSE──> 本服务 ──SSH──> 网络设备
                  AI 选择命令并填参数            校验+拼装           返回原始输出
                  AI 分析结果回答用户  <────────  健康检测+执行  <──────
```

**关键设计：AI 不能自由输入命令。** AI 只能从预定义的 318 条命令菜单中选择 `command_id`，服务端负责拼装和执行。这从根本上杜绝了 AI 构造危险命令的可能。

## 安全机制

所有校验在 SSH 连接建立**之前**完成：

1. **封闭命令集** — AI 只能从 `config/commands.yaml` 中选择命令，不能自由输入
2. **参数类型校验** — ip_address（IPv4 校验）/ string（正则匹配）/ integer（范围约束）
3. **注入字符拦截** — 参数值禁止 `; | & $ \n` 等 Shell 特殊字符
4. **服务端拼装** — 命令主体锁死在配置文件中，AI 只能补充参数值
5. **设备健康检测** — SSH 连接后、命令执行前，检测设备 CPU 和在线用户数，超阈值则拒绝执行

被拦截的操作会记录到审计日志（`logs/audit.log`），每行一条 JSON。

### 健康检测

连接设备后，系统会自动检测设备负载状态，避免对已过载设备造成额外压力：

| 指标 | 默认阈值 | 超阈值行为 |
|------|---------|-----------|
| CPU 使用率 | 80% | 断连，返回告警，命令不执行 |
| 在线 VTY 用户数 | 4 | 断连，返回告警，命令不执行 |

- 阈值可在 `config/settings.yaml` 中调整
- 检测失败（如输出格式无法解析）时跳过检测，不阻断业务
- 可通过 `health_check.enabled: false` 全局关闭

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

# 后台启动服务（首次自动创建 venv 并安装依赖）
./start.sh

# 或前台 Debug 模式启动（日志直接输出到终端，Ctrl+C 停止）
./start-debug.sh

# 停止后台服务
./stop.sh
```

服务启动后监听 `http://0.0.0.0:8081/network-device-mcp`。

### 2. 配置 AI 客户端

在 Claude Code（或其他支持 MCP 的 AI 客户端）的配置中添加：

```json
{
  "mcpServers": {
    "network-readonly": {
      "type": "sse",
      "url": "http://你的服务器IP:8081/network-device-mcp"
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

## 接口文档

本服务通过 MCP 协议对外暴露 4 个工具（Tool），AI 客户端通过 SSE 连接后即可调用。

### 工具总览

| 工具 | 用途 | 适用场景 |
|------|------|---------|
| `list_available_commands` | 查看指定设备类型的可用命令菜单 | 了解可用命令 |
| `execute_readonly_command` | 对单台设备执行一条只读命令 | 简单查询 |
| `batch_execute_readonly_command` | 对多台设备并发执行同一条只读命令 | 批量查询 |
| `execute_multi_commands` | 对单/多台设备执行多条只读命令（单连接） | 巡检 |

---

### 1. list_available_commands

查询指定设备类型可用的命令列表。AI 助手应先调用此工具了解可用命令（command_id），再执行查询。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `device_type` | string | 否 | `"cisco"` | 设备类型 |

**请求示例：**

```json
{
  "device_type": "huawei"
}
```

**返回示例：**

```json
[
  {
    "command_id": "display_version",
    "name": "查看版本信息",
    "description": "显示设备软硬件版本信息",
    "params": []
  },
  {
    "command_id": "display_ip_interface_brief",
    "name": "查看接口 IP 摘要",
    "description": "显示所有接口的 IP 地址和状态",
    "params": []
  },
  {
    "command_id": "ping",
    "name": "Ping 测试",
    "description": "从设备 ping 指定 IP 地址",
    "params": [
      {
        "name": "ip_address",
        "type": "ip_address",
        "required": true,
        "description": "目标 IP 地址"
      }
    ]
  }
]
```

**错误返回：**

```json
{
  "error": "不支持的设备类型: xxx，支持: aruba, cisco, cisco_asa, cisco_nxos, fortinet, h3c, huawei, juniper, ruijie, ruckus"
}
```

---

### 2. execute_readonly_command

对单台设备执行一条只读命令，返回原始执行结果。

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `host` | string | **是** | - | 设备 IP 地址 |
| `command_id` | string | **是** | - | 命令标识（从 `list_available_commands` 获取） |
| `device_type` | string | 否 | `"cisco"` | 设备类型 |
| `params` | object | 否 | `null` | 命令参数，key-value 形式 |
| `port` | integer | 否 | `22` | SSH 端口 |
| `username` | string | 否 | `null` | SSH 用户名（覆盖服务端默认凭据） |
| `password` | string | 否 | `null` | SSH 密码（覆盖服务端默认凭据） |

**请求示例（无参数命令）：**

```json
{
  "host": "192.168.1.1",
  "device_type": "huawei",
  "command_id": "display_version"
}
```

**请求示例（带参数命令）：**

```json
{
  "host": "192.168.1.1",
  "device_type": "cisco",
  "command_id": "ping",
  "params": {
    "ip_address": "10.0.0.1"
  }
}
```

**成功返回：**

```json
{
  "host": "192.168.1.1",
  "success": true,
  "command_executed": "display version",
  "output": "Huawei Versatile Routing Platform Software\nVRP (R) software, Version 5.170 ...",
  "error": ""
}
```

**失败返回：**

```json
{
  "host": "192.168.1.1",
  "success": false,
  "command_executed": "display version",
  "output": "",
  "error": "连接超时: 192.168.1.1:22（超时 30s）"
}
```

---

### 3. batch_execute_readonly_command

对多台设备并发执行同一条只读命令，汇总返回各设备的结果。

- 命令校验只做一次，校验失败则所有设备都不执行
- 各设备并发执行，单台失败不影响其他设备
- 并发上限 50 台，超出部分排队等待

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `hosts` | string[] | **是** | - | 设备 IP 地址列表 |
| `command_id` | string | **是** | - | 命令标识 |
| `device_type` | string | 否 | `"cisco"` | 设备类型 |
| `params` | object | 否 | `null` | 命令参数 |
| `port` | integer | 否 | `22` | SSH 端口 |
| `username` | string | 否 | `null` | SSH 用户名（覆盖服务端默认凭据） |
| `password` | string | 否 | `null` | SSH 密码（覆盖服务端默认凭据） |

**请求示例：**

```json
{
  "hosts": ["192.168.1.1", "192.168.1.2", "192.168.1.3"],
  "device_type": "cisco",
  "command_id": "show_version"
}
```

**成功返回：**

```json
[
  {
    "host": "192.168.1.1",
    "success": true,
    "command_executed": "show version",
    "output": "Cisco IOS Software ...",
    "error": ""
  },
  {
    "host": "192.168.1.2",
    "success": true,
    "command_executed": "show version",
    "output": "Cisco IOS Software ...",
    "error": ""
  },
  {
    "host": "192.168.1.3",
    "success": false,
    "command_executed": "show version",
    "output": "",
    "error": "连接超时: 192.168.1.3:22（超时 30s）"
  }
]
```

**校验失败返回（所有设备均不执行）：**

```json
{
  "success": false,
  "error": "未知命令: device_type=cisco, command_id=xxx",
  "results": []
}
```

---

### 4. execute_multi_commands

对一台或多台设备执行多条只读命令，每台设备一次 SSH 连接完成所有命令。

- 适用于巡检等需要同时获取多项信息的场景，减少重复建连开销
- 每条命令独立校验，某条校验失败不影响其他命令执行
- 多台设备时各自建立一次连接，设备间并发执行
- `host` 和 `hosts` 二选一

**参数：**

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `commands` | object[] | **是** | - | 命令列表，每项含 `command_id` 和可选 `params` |
| `device_type` | string | 否 | `"cisco"` | 设备类型 |
| `host` | string | 二选一 | `null` | 单台设备 IP |
| `hosts` | string[] | 二选一 | `null` | 多台设备 IP 列表 |
| `port` | integer | 否 | `22` | SSH 端口 |
| `username` | string | 否 | `null` | SSH 用户名（覆盖服务端默认凭据） |
| `password` | string | 否 | `null` | SSH 密码（覆盖服务端默认凭据） |

**commands 数组中每项的结构：**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `command_id` | string | **是** | 命令标识 |
| `params` | object | 否 | 命令参数 |

**请求示例（单台设备巡检）：**

```json
{
  "host": "192.168.1.1",
  "device_type": "huawei",
  "commands": [
    {"command_id": "display_version"},
    {"command_id": "display_cpu_usage"},
    {"command_id": "display_memory_usage"},
    {"command_id": "display_ip_interface_brief"},
    {"command_id": "display_arp"}
  ]
}
```

**请求示例（多台设备巡检）：**

```json
{
  "hosts": ["192.168.1.1", "192.168.1.2"],
  "device_type": "huawei",
  "commands": [
    {"command_id": "display_version"},
    {"command_id": "display_cpu_usage"}
  ]
}
```

**请求示例（带参数命令）：**

```json
{
  "host": "10.0.0.1",
  "device_type": "cisco",
  "commands": [
    {"command_id": "show_version"},
    {"command_id": "ping", "params": {"ip_address": "10.0.0.2"}},
    {"command_id": "show_interface", "params": {"interface": "GigabitEthernet0/1"}}
  ]
}
```

**单台设备返回：**

```json
{
  "host": "192.168.1.1",
  "results": [
    {
      "command_id": "display_version",
      "command_executed": "display version",
      "success": true,
      "output": "Huawei Versatile Routing Platform Software ...",
      "error": ""
    },
    {
      "command_id": "display_cpu_usage",
      "command_executed": "display cpu-usage",
      "success": true,
      "output": "CPU utilization for five seconds: 12% ...",
      "error": ""
    },
    {
      "command_id": "display_memory_usage",
      "command_executed": "display memory-usage",
      "success": true,
      "output": "System Total Memory Is: 512M bytes ...",
      "error": ""
    }
  ]
}
```

**多台设备返回：**

```json
[
  {
    "host": "192.168.1.1",
    "results": [
      {"command_id": "display_version", "command_executed": "display version", "success": true, "output": "...", "error": ""},
      {"command_id": "display_cpu_usage", "command_executed": "display cpu-usage", "success": true, "output": "...", "error": ""}
    ]
  },
  {
    "host": "192.168.1.2",
    "results": [
      {"command_id": "display_version", "command_executed": "display version", "success": true, "output": "...", "error": ""},
      {"command_id": "display_cpu_usage", "command_executed": "display cpu-usage", "success": false, "output": "", "error": "SSH 执行异常: ..."}
    ]
  }
]
```

**部分命令校验失败的返回（其他命令正常执行）：**

```json
{
  "host": "192.168.1.1",
  "results": [
    {
      "command_id": "invalid_command",
      "command_executed": "",
      "success": false,
      "output": "",
      "error": "未知命令: device_type=huawei, command_id=invalid_command"
    },
    {
      "command_id": "display_version",
      "command_executed": "display version",
      "success": true,
      "output": "Huawei Versatile Routing Platform Software ...",
      "error": ""
    }
  ]
}
```

---

### 错误码说明

所有工具的错误信息通过返回结构中的 `error` 字段传递，常见错误：

| 错误信息 | 原因 | 处理建议 |
|---------|------|---------|
| `未知命令: device_type=xxx, command_id=xxx` | command_id 不在命令菜单中 | 先调用 `list_available_commands` 获取正确的 command_id |
| `不支持的设备类型: xxx` | device_type 不在支持列表中 | 检查设备类型映射表 |
| `缺少必填参数: xxx` | 命令需要参数但未提供 | 查看命令菜单中的 params 定义 |
| `参数包含非法字符: xxx` | 参数值包含 `; \| & $ \n` 等注入字符 | 移除参数中的特殊字符 |
| `参数 xxx 不是合法的 IPv4 地址` | ip_address 类型参数格式错误 | 传入合法的 IPv4 地址 |
| `认证失败: host:port` | SSH 用户名或密码错误 | 检查凭据配置 |
| `连接超时: host:port（超时 30s）` | 设备不可达或网络延迟过高 | 检查网络连通性 |
| `设备不可达: host:port` | 无法建立 TCP 连接 | 检查 IP、端口、防火墙规则 |
| `未配置 SSH 凭据` | 服务端 .env 未配置且客户端未传入凭据 | 配置 .env 或传入 username/password |
| `必须提供 host 或 hosts 参数` | execute_multi_commands 未提供目标设备 | 二选一提供 host 或 hosts |

---

### 设备类型映射

调用时 `device_type` 使用左列值：

| device_type | 厂商/平台 | netmiko 映射 |
|-------------|----------|-------------|
| `cisco` | Cisco IOS/IOS-XE | cisco_ios |
| `cisco_asa` | Cisco ASA | cisco_asa |
| `cisco_nxos` | Cisco NX-OS | cisco_nxos |
| `huawei` | Huawei VRP | huawei_vrp |
| `h3c` | H3C Comware | hp_comware |
| `fortinet` | Fortinet FortiGate | fortinet |
| `aruba` | Aruba OS | aruba_os |
| `juniper` | Juniper JunOS | juniper_junos |
| `ruijie` | Ruijie OS | ruijie_os |
| `ruckus` | Ruckus FastIron | ruckus_fastiron |

---

## 项目结构

```
network-device-mcp/
├── start.sh                        # 后台启动脚本
├── start-debug.sh                  # 前台 Debug 模式启动
├── stop.sh                         # 停止后台服务
├── config/
│   ├── commands.yaml               # 命令封闭集合（10 平台 332 条命令）
│   └── settings.yaml               # 运行时配置（健康检测阈值等）
├── src/
│   ├── server.py                   # MCP 服务入口（FastMCP + SSE 传输）
│   ├── requirements.txt            # Python 依赖
│   ├── health_check.py             # 设备健康检测（CPU / 在线用户数）
│   ├── core/                       # 基础设施层
│   │   ├── config.py               #   全局配置常量 + settings.yaml 加载
│   │   └── audit.py                #   JSON 行审计日志
│   ├── commands/                   # 命令解析层
│   │   └── registry.py             #   YAML 加载 + 参数校验 + 命令拼装
│   ├── security/                   # 安全校验层
│   │   ├── validator.py            #   注入字符检测
│   │   └── credential.py           #   凭据管理（.env 默认 + 客户端覆盖）
│   ├── executor/                   # SSH 执行层
│   │   └── ssh.py                  #   netmiko 异步执行 + 并发控制 + ssh_session 上下文
│   └── tools/                      # MCP 工具层（对外接口）
│       └── handlers.py             #   4 个 MCP 工具定义（编排层 + 健康检测集成）
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

带参数的命令使用 `{参数名}` 占位符：

```yaml
cisco:
  - id: ping
    name: "Ping 测试"
    description: "从设备 Ping 指定 IP"
    command: "ping {ip_address}"
    params:
      - name: ip_address
        type: ip_address
        description: "目标 IP 地址"
```

修改 YAML 后需要**重启服务**才能生效（命令在启动时一次性加载到内存）。

---

## 技术栈

- Python 3.10+
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)（FastMCP + SSE）
- [netmiko](https://github.com/ktbyers/netmiko)（SSH 多厂商设备连接）
- asyncio.to_thread（同步 SSH 转异步）+ Semaphore（并发控制）
