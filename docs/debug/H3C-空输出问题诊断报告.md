# H3C 设备命令执行返回空输出 — 诊断报告

> **报告人**：Debug 与安全审计员  
> **日期**：2026-04-29  
> **状态**：待修复  
> **优先级**：高（影响 H3C 设备全部命令的正常使用）

---

## 环境信息

| 项目 | 值 |
|------|-----|
| 设备 IP | 10.63.4.28 |
| 设备主机名 | CN-SZX03-A-F04M-LACPS-008-MTBF |
| 设备型号 | H3C S5135S-16FP4S-EI |
| 固件版本 | Comware 7.1.070, Release 6810P05 |
| device_type | h3c → netmiko 映射为 `hp_comware` |
| SSH 连接 | 正常 |
| netmiko driver | `netmiko/hp/hp_comware.py` → `HPComwareSSH` |

## 现象

| 命令 | 结果 |
|------|------|
| `display version` | ✅ 有输出 |
| `display interface brief` | ⚠️ 部分输出，且混入了其他命令的残余数据 |
| `display current-configuration` | ❌ success=true 但 output 为空 |
| `display saved-configuration` | ❌ success=true 但 output 为空 |
| `display ip interface brief` | ❌ success=true 但 output 为空 |

设备登录时有 banner：

```
******************************************************************************
* Copyright (c) 2004-2025 New H3C Technologies Co., Ltd. All rights reserved.*
* Without the owner's prior written consent,                                 *
* no decompiling or reverse-engineering shall be allowed.                    *
******************************************************************************

<CN-SZX03-A-F04M-LACPS-008-MTBF>
```

已手动确认 `screen-length disable` 命令权限正常。

---

## 疑似根因（两个问题可能同时存在）

### 问题一：`send_command()` 误判 prompt 导致提前截断

**涉及代码**：`src/executor/ssh.py` 第 140 行

```python
output = conn.send_command(command, read_timeout=SSH_TIMEOUT)
```

**原理**：`send_command()` 通过检测 `base_prompt` 字符串来判断命令输出是否结束。netmiko 的 `hp_comware` 驱动将 `base_prompt` 设置为 `CN-SZX03-A-F04M-LACPS-008-MTBF`（去掉 `<>` 的主机名）。

**问题**：H3C 的 `display current-configuration` 输出前几行就包含：

```
 sysname CN-SZX03-A-F04M-LACPS-008-MTBF
```

`send_command()` 读到这一行时，检测到 `base_prompt` 字符串，**误以为设备已返回 prompt**，立刻停止读取。由于 `sysname` 出现在配置最前面，有效输出几乎为零。

残留在缓冲区的数据会被下一次 `send_command()` 读到，导致**输出串流**（版本信息混入其他命令的输出）。

### 问题二：分页可能未成功关闭

**涉及代码**：netmiko `hp_comware.py` 第 25-26 行

```python
command = "screen-length disable"
self.disable_paging(command=command)
```

netmiko 在 `session_preparation()` 中会自动发送 `screen-length disable`。但如果该命令因某种原因未生效（执行时序、缓冲区残留等），长输出命令会遇到 `---- More ----` 分页。而 `send_command()` **不处理分页提示**，会一直等待 prompt 直到超时，最终返回空。

这可以解释 `display ip interface brief`（输出中不含主机名）也返回空的现象。

---

## 定位方法

在 `src/executor/ssh.py` 的 `device_params` 中临时加入 `session_log`：

```python
device_params = {
    "device_type": netmiko_device_type,
    "host": host,
    "port": port,
    "username": username,
    "password": password,
    "timeout": SSH_TIMEOUT,
    "read_timeout_override": SSH_TIMEOUT,
    "conn_timeout": SSH_TIMEOUT,
    "session_log": f"/tmp/netmiko_{host}.log",  # 临时加这一行
}
```

执行一次 `display ip interface brief`，查看 `/tmp/netmiko_10.63.4.28.log` 确认：

1. `screen-length disable` 是否发送成功、设备是否回复正常
2. `send_command` 读取过程中有没有出现 `---- More ----`
3. `send_command` 是在哪一行停止读取的

---

## 修复建议

### 方案 A（推荐）：针对 `hp_comware` 使用 `send_command_timing`

`send_command_timing` 不依赖 prompt 匹配，通过"一段时间内无新数据"来判断输出结束，同时也能处理分页，**一次性解决两个问题**。

修改 `src/executor/ssh.py`：

```python
def _execute_blocking(device_params: dict, command: str) -> str:
    """同步执行单条 SSH 命令（在线程中运行）。"""
    with ConnectHandler(**device_params) as conn:
        if device_params["device_type"] == "hp_comware":
            output = conn.send_command_timing(command, delay_factor=2)
        else:
            output = conn.send_command(command, read_timeout=SSH_TIMEOUT)
    return output
```

`_execute_multi_blocking` 第 153 行同样需要修改：

```python
def _execute_multi_blocking(device_params: dict, commands: list[str]) -> list[dict]:
    results = []
    with ConnectHandler(**device_params) as conn:
        for cmd in commands:
            try:
                if device_params["device_type"] == "hp_comware":
                    output = conn.send_command_timing(cmd, delay_factor=2)
                else:
                    output = conn.send_command(cmd, read_timeout=SSH_TIMEOUT)
                results.append({
                    "command": cmd,
                    "success": True,
                    "output": output,
                    "error": "",
                })
            except Exception as e:
                results.append({
                    "command": cmd,
                    "success": False,
                    "output": "",
                    "error": f"{type(e).__name__}: {e}",
                })
    return results
```

### 方案 B：修改 prompt 匹配模式使其更严格

在 `send_command` 中指定 `expect_string` 参数，要求完整匹配 `<hostname>` 而不是裸主机名：

```python
output = conn.send_command(
    command,
    read_timeout=SSH_TIMEOUT,
    expect_string=r"<CN-SZX03-A-F04M-LACPS-008-MTBF>",
)
```

需要动态拼接每台设备的 prompt，通用性差，**不推荐**。

### 方案 C：连接后显式补发 `screen-length disable`

作为防御性编程，在执行命令前手动补发一次分页禁用：

```python
def _execute_blocking(device_params: dict, command: str) -> str:
    with ConnectHandler(**device_params) as conn:
        if device_params["device_type"] in ("hp_comware", "huawei_vrp"):
            conn.send_command_timing("screen-length disable")
        output = conn.send_command(command, read_timeout=SSH_TIMEOUT)
    return output
```

**注意**：此方案仅解决分页问题，不解决 prompt 误判问题。

---

## 建议优先级

1. **先加 `session_log` 确认根因**（5 分钟内可完成）
2. **采用方案 A 修复**（改动最小，覆盖面最广）
3. 如后续其他设备类型也出现类似问题，考虑在 `ssh.py` 中做统一的 device_type → 执行策略映射

---

## 影响范围

- 所有 H3C (hp_comware) 设备的长输出命令
- 所有包含 `sysname` 的配置查看命令
- 批量执行时可能导致输出串流到其他命令
- Huawei (huawei_vrp) 设备可能存在同类问题（待验证）
