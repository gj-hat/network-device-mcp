# 网络设备只读查询 MCP 服务

通过 MCP 协议为 AI 助手提供安全的网络设备只读查询能力。支持 10 个平台共 318 条只读命令，覆盖 Cisco IOS/ASA/NX-OS、Huawei VRP、H3C Comware、Fortinet、Aruba、Juniper JunOS、Ruijie、Ruckus 等主流网络设备。

**核心原则：安全第一。系统绝不允许执行任何配置变更命令。**

---

## 快速启动

```bash
# 1. 配置凭据
cp .env.example .env
# 编辑 .env，填入 SSH 默认用户名和密码

# 2. 启动服务（首次自动创建 venv 并安装依赖）
./start.sh
```

服务启动后监听 `http://0.0.0.0:8081/sse`，AI 助手通过该 URL 连接。

---

## 项目结构

```
network-readOnly-api/
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
│   └── audit.log               # 审计日志输出
├── .env                        # SSH 默认凭据（不入版本控制）
├── .env.example                # 凭据格式示例
└── docs/                       # 产品与架构设计文档
```

---

## 4 个 MCP 工具

| 工具 | 用途 | 适用场景 |
|------|------|---------|
| `list_available_commands` | 查看指定设备类型的可用命令菜单 | 了解可用命令 |
| `execute_readonly_command` | 对单台设备执行一条只读命令 | 简单查询 |
| `batch_execute_readonly_command` | 对多台设备并发执行同一条只读命令 | 批量查询 |
| `execute_multi_commands` | 对单/多台设备执行多条只读命令（单连接） | 巡检 |

AI 助手应先调用 `list_available_commands` 获取命令菜单，再选择 `command_id` 执行查询。

### 工具四：多命令单连接执行（巡检场景）

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

## 安全机制

采用封闭集合模型，AI **不能**自由输入命令字符串，只能从 `config/commands.yaml` 中选择 `command_id`：

1. **command_id 校验** — 不在配置中的命令直接拒绝
2. **参数类型校验** — ip_address / string（正则）/ integer（范围）
3. **注入字符拦截** — 参数值禁止 `; | & ` $ \n \r \` 等特殊字符
4. **服务端拼装命令** — 主命令锁死在配置中，AI 只能补充参数值
5. **兜底黑名单** — 拼装后命令仍检查 config/delete/reboot 等危险关键词

所有校验在 SSH 连接建立**之前**完成。被拦截的操作会记录到审计日志。

---

## 配置说明

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SSH_USERNAME` | — | SSH 默认用户名（必填） |
| `SSH_PASSWORD` | — | SSH 默认密码（必填） |
| `SSH_TIMEOUT` | 30 | SSH 超时秒数 |
| `MCP_HOST` | 0.0.0.0 | 服务监听地址 |
| `MCP_PORT` | 8081 | 服务监听端口 |
| `MAX_CONCURRENCY` | 50 | 批量查询最大并发数 |

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

| 本系统 | netmiko device_type | 命令数 | 说明 |
|--------|---------------------|--------|------|
| cisco | cisco_ios | 70 | Cisco IOS / IOS-XE 交换机/路由器 |
| cisco_asa | cisco_asa | 28 | Cisco ASA 防火墙 |
| cisco_nxos | cisco_nxos | 31 | Cisco NX-OS 数据中心交换机 |
| huawei | huawei_vrp | 44 | 华为 VRP 交换机/路由器/无线 AC |
| h3c | hp_comware | 33 | 新华三 Comware 交换机/无线 AC |
| fortinet | fortinet | 20 | 飞塔 FortiGate 防火墙 |
| aruba | aruba_os | 19 | Aruba 无线控制器 |
| juniper | juniper_junos | 30 | Juniper JunOS 路由器/SRX 防火墙 |
| ruijie | ruijie_os | 22 | 锐捷交换机/路由器 |
| ruckus | ruckus_fastiron | 21 | Ruckus FastIron/ICX 交换机 |

---

## 技术栈

- Python 3.10+
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)（FastMCP + SSE）
- [netmiko](https://github.com/ktbyers/netmiko)（SSH 多厂商设备连接）
- asyncio.to_thread（同步 SSH 转异步）+ Semaphore（并发控制）
