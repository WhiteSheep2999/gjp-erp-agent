# gjp-erp-agent

管家婆云工贸 ERP 数据操作 Skill —— 让 AI Agent 安全地完成存货档案的增、查、改、停用、恢复等操作。

## 特性

- **安全第一**：写操作强制确认（`--yes`）、危险字段黑名单（管理批号/自定义项/计价方式/序列号等禁止修改）、写前自动备份、审计日志、无删除只有停用
- **自包含**：纯 Python 标准库，无第三方依赖，拷贝即用
- **可分发**：适合作为 Skill 打包给任何 AI Agent（OpenClaw / Claude / 自研 Agent）使用

## 结构

```
gjp-erp-agent/
├── SKILL.md              # agent 指令（触发词/流程/安全规则/命令表/踩坑记录）
├── README.md             # 使用说明
├── config.example.json   # 凭证配置模板（不含真实密钥）
└── scripts/
    ├── gjp_tool.py       # 安全工具箱（唯一入口）
    └── gjp_api_client.py # 底层 API 客户端
```

## 快速开始

### 1. 安装

```bash
# 放到目标 agent 的 skills 目录（如 OpenClaw 的 ~/.agents/skills/）
cp -r gjp-erp-agent ~/.agents/skills/
```

### 2. 配置凭证

```bash
cd gjp-erp-agent
cp config.example.json config.json
chmod 600 config.json
# 编辑 config.json 填入真实值
```

配置项：
- `AppKey` / `SecretKey`：向管家婆厂家申请
- `UserId`：公司账号（云版=注册手机号）
- `DbName`：账套数据库名（云版找代理商/管理员查询）

### 3. 测试连通

```bash
python3 scripts/gjp_tool.py ping
```

## 使用

### 读操作（Agent 可直接调用）

```bash
python3 scripts/gjp_tool.py groups                        # 存货分组树
python3 scripts/gjp_tool.py list --typeid 00206           # 按分组查存货
python3 scripts/gjp_tool.py list --name "糖醋"            # 按名称模糊查
python3 scripts/gjp_tool.py list --nospec                 # 只看无规格
python3 scripts/gjp_tool.py log --tail 50                 # 审计日志
```

### 写操作（必须 --yes，且先经用户确认）

```bash
python3 scripts/gjp_tool.py add --code CP-100 --name "新产品" --standard "400g" --unit "瓶" --yes
python3 scripts/gjp_tool.py modify --rec 123 --code CP-101 --name "新产品" --yes
python3 scripts/gjp_tool.py disable --typeid 00206 --nospec --list   # 预览
python3 scripts/gjp_tool.py disable --typeid 00206 --nospec --yes    # 执行
python3 scripts/gjp_tool.py enable --rec 123 --yes
python3 scripts/gjp_tool.py restore --from backups/backup_xxx.json --yes  # 从备份恢复
```

## 安全设计

| 机制 | 说明 |
|---|---|
| 写操作强制确认 | 必须加 `--yes`（或环境变量 `GJP_AUTO_APPROVE=1`），否则拒绝执行 |
| 危险字段黑名单 | 管理批号/自定义项/序列号/计价方式/核算方法等禁止修改（不暴露参数，天然拦截） |
| 安全字段白名单 | 只允许修改编号/名称/规格/备注/停用标志/参考成本/安全库存 |
| 写前自动备份 | 每次写操作快照到 `backups/`，`restore` 一键恢复 |
| 审计日志 | 所有写操作记录到 `audit.log`，可追溯 |
| 无删除 | 只有停用（deleted=1），可逆 |

## API 对接说明

管家婆 API 对接要点（详见 `SKILL.md`）：
- 通用接口获取 SignKey + ApiServerAddress（24 小时有效，脚本自动续期）
- 签名算法：MD5 32 位小写；getsignstr 不排 MethodName，getcustomerapiurl 不排 DbName
- 查询响应字段是小写（usercode/fullname 等），文档示例大写是笔误

## 版本

- v1.0（2026-10-30）：初版，基于管家婆 M7 22.0 测试环境验证

## License

MIT
