---
name: "gjp-erp-agent"
description: "管家婆云工贸ERP增查改：查存货/新增存货/修改存货/停用/恢复/库存查询时用安全工具箱脚本操作，写操作强制确认、自动备份、审计日志。"
---

# 管家婆 ERP 增查改（gjp-erp-agent）

## 触发
用户要求操作管家婆 ERP 数据时：查存货、新增存货、修改存货、停用存货、恢复存货、查分组、查库存、改编号、批量录入等。

## 前置条件（必须先满足）
1. **凭证**：本 skill 目录下必须有 `config.json`（由管理员从 `config.example.json` 模板填写真实值：AppKey/SecretKey/UserId/DbName）。**没有 config.json 时拒绝一切操作**，提示管理员先配置。
2. **脚本**：`scripts/gjp_tool.py`（安全工具箱，唯一入口）。用 `python3` 运行。
3. 授权有效期内（到期需厂家续期）。

## 核心原则（安全第一，不可违反）
1. **只调用脚本，不直接调 API**——脚本内部处理签名/校验/备份/审计
2. **写操作强制确认**：新增/修改/停用/恢复/批量操作，必须加 `--yes` 才执行；**执行前必须向用户展示计划**（改什么/影响几条/影响范围），用户批准后才加 `--yes`
3. **读操作可直接执行**：ping/groups/list/log 等查询命令无需确认
4. **无删除**：只能停用（可逆），绝不删除
5. **危险字段禁止修改**：管理批号/自定义项/序列号/计价方式/核算方法等（脚本已内置黑名单拦截）

## 命令表

### 读操作（直接调用，无风险）
```bash
# 连通性测试
python3 scripts/gjp_tool.py ping

# 存货分组树（一级/二级）
python3 scripts/gjp_tool.py groups

# 查存货（可按分组/名称/无规格筛选）
python3 scripts/gjp_tool.py list
python3 scripts/gjp_tool.py list --typeid 00206          # 按分组
python3 scripts/gjp_tool.py list --name "糖醋"           # 按名称模糊（本地匹配 fullname/name/namepy/usercode）
python3 scripts/gjp_tool.py list --nospec                # 只看无规格
python3 scripts/gjp_tool.py list --json                  # JSON 输出

# 审计日志
python3 scripts/gjp_tool.py log --tail 50

# 库存查询（只读）
python3 scripts/gjp_tool.py stock --typeid 00206
```

### 写操作（必须 --yes，且先经用户确认）
```bash
# 新增存货
python3 scripts/gjp_tool.py add --code CP-100 --name "新产品" --standard "400g" --unit "瓶" --yes

# 修改存货（只能改安全字段：编号/名称/规格/备注/停用等）
python3 scripts/gjp_tool.py modify --rec 123 --code CP-101 --name "新产品" --yes
#   --code 改编号(usercode) / --name 改全名(fullname) / --shortname 改简名(name)
#   其他安全字段：--standard --comment --refprice --safeqty --safedaycount

# 停用某分组下无规格的存货（先 --list 预览，再执行）
python3 scripts/gjp_tool.py disable --typeid 00206 --nospec --list   # 预览（不执行）
python3 scripts/gjp_tool.py disable --typeid 00206 --nospec --yes    # 执行

# 恢复启用
python3 scripts/gjp_tool.py enable --rec 123 --yes

# 从备份恢复（改错时）
python3 scripts/gjp_tool.py restore --from backups/backup_xxx.json --yes
```

## 标准操作流程（写操作）

```
1. 读：查目标数据（list/groups），确认操作对象
2. 计划：向用户展示——改什么、影响多少条、影响范围、理由
3. 确认：用户明确同意后
4. 执行：加 --yes 调用脚本（脚本自动备份 → 执行 → 审计）
5. 验证：回读确认结果（list 复查）
6. 汇报：操作结果 + 备份文件位置
```

## 踩坑记录（务必遵守）

### 签名（脚本已处理，了解即可）
- getsignstr 签名只排 AppKey/InvalidTime(紧凑格式)/RandamStr，**MethodName 不参与**
- getcustomerapiurl 签名只排 AppKey/InvalidTime/RandamStr/UserId，**DbName 不参与**（只在请求体）
- 业务接口签名用原始值不 URLEncode；签名与请求体时间必须同一时刻
- 通用接口返回 24 小时有效，脚本自动重取

### 查询响应字段是小写（文档是大写，是笔误）
- 用 `usercode/fullname/standard/unit1/deleted/leveal/parid/typeid/rec/sonnum`，**不要**用文档示例的 `UserCode/FullName`（会取到空）
- `sonnum=0` 表示末级存货；`parid=00000` 是一级分组；`leveal` 是级次

### 修改必带字段
- modify 时 baseinfodata 必须含 usercode/fullname/gpfullname/costmode/inputno，缺 gpfullname 报「存货核算方法不能为空」，缺 fullname 报「存货全名不能为空」

### 编号冲突
- 目标编号已占用报「编号与其它记录相同」；先查重（list 按编号查），或先改走占用者，或用时间戳生成唯一号

### 分页
- pagesize 最大 200；循环 pageindex 递增直到 len(response)<pagesize 或累计>=pagetotal；全量拉取每页增量落盘防中断

## 环境切换（测试/正式）
- 只改 `config.json` 里的 UserId 和 DbName，脚本代码不用动
- 测试环境数据是演示数据（A001/信诺得/服装厂等），勿当真实数据

## 参考
- 脚本：`scripts/gjp_tool.py`（安全工具箱，唯一入口）；`scripts/gjp_api_client.py`（底层库）
- 备份目录：`backups/`（写操作自动生成）；审计日志：`audit.log`
- 配置模板：`config.example.json`（复制为 config.json 后填写）
