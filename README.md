# gjp-erp-agent Skill — 管家婆 ERP 增查改

给 AI Agent 使用的管家婆云工贸 ERP 数据操作技能包。Agent 通过安全工具箱脚本完成存货档案的增、查、改、停用、恢复等操作，内置写保护（强制确认、自动备份、危险字段拦截、审计日志），防止误删误改。

## 安装（给管理员/人类）

1. 把整个 `gjp-erp-agent/` 目录放到目标 agent 的 skills 目录（如 OpenClaw 的 `~/.agents/skills/` 或 `~/.openclaw/skills/`）
2. **配置凭证**：复制 `config.example.json` 为 `config.json`，填入真实值：

```json
{
  "环境": "测试",
  "AppKey": "从管家婆厂家申请",
  "SecretKey": "从管家婆厂家申请",
  "UserId": "公司账号（云版=注册手机号）",
  "DbName": "账套数据库名（云版找代理商/管理员查）"
}
```

3. 建议把 `config.json` 权限设为 600：`chmod 600 config.json`
4. 授权到期前联系管家婆厂家续期（到期接口失效）

## 结构

```
gjp-erp-agent/
├── SKILL.md              # agent 指令（触发词/流程/安全规则/命令表/踩坑）
├── config.example.json   # 凭证模板（不含真实密钥）
├── README.md             # 本文件
└── scripts/
    ├── gjp_tool.py       # 安全工具箱（唯一入口，纯标准库无依赖）
    └── gjp_api_client.py # 底层 API 客户端
```

## 使用

- agent 加载 skill 后，读操作直接执行；写操作必须先展示计划、经用户确认、加 `--yes` 执行
- 测试/正式环境切换：只改 config.json 的 UserId/DbName
- 误操作恢复：`python3 scripts/gjp_tool.py restore --from backups/备份文件 --yes`

## 安全说明

- 写操作强制 `--yes` 确认（或环境变量 GJP_AUTO_APPROVE=1）
- 危险字段黑名单：管理批号/自定义项/序列号/计价方式/核算方法等禁止修改
- 写前自动备份到 `backups/`，审计日志 `audit.log`
- 无删除操作，只有停用（可逆）

## 测试

```bash
cd gjp-erp-agent
python3 scripts/gjp_tool.py ping        # 连通性测试
python3 scripts/gjp_tool.py groups      # 分组树
python3 scripts/gjp_tool.py list        # 查存货
```

## 版本记录

- 2026-10-30 v1.0：初版，基于安徽颍盛管家婆 M7 22.0 测试环境验证（签名/查询/新增/修改/停用全部实测通过）
