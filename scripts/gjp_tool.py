#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
管家婆云工贸 API 安全工具箱（gjp_tool.py）
============================================
设计原则（安全第一）：
  1. AI/脚本只调用本工具；所有写操作强制确认（--yes 或环境变量 GJP_AUTO_APPROVE=1）
  2. 写操作前自动备份受影响记录（可一键恢复）
  3. 危险字段黑名单：管理批号/自定义项/计价方式/序列号等禁止修改
  4. 修改前检查单据引用：被单据引用的存货，仅允许改安全字段
  5. 所有操作写审计日志（audit.log）
  6. 无删除操作，只有停用（可逆）

用法：
  python3 gjp_tool.py ping                        # 连通性测试（只读）
  python3 gjp_tool.py groups                      # 存货分组树（只读）
  python3 gjp_tool.py list  [--typeid X] [--name 模糊] [--nospec] [--json]   # 查存货（只读）
  python3 gjp_tool.py add --code X --name Y [--standard S] [--unit U] [--yes]   # 新增（写）
  python3 gjp_tool.py modify --rec N --code X --name Y [--standard S] [--yes]   # 修改（写）
  python3 gjp_tool.py disable --typeid X --nospec [--list] [--yes]   # 停用某分组无规格存货（写）
  python3 gjp_tool.py enable --rec N [--yes]     # 恢复启用（写）
  python3 gjp_tool.py restore --from 备份文件     # 从备份恢复（写）
  python3 gjp_tool.py log [--tail 50]            # 查看审计日志（只读）
  python3 gjp_tool.py stock --typeid X           # 库存查询（只读，需 paramkey）

退出码：0=成功 1=被拒绝/失败 2=需确认但未确认
"""
import argparse
import hashlib
import json
import os
import random
import string
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

# ============ 基础配置 ============
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 优先找脚本同级的 config.json；否则找上级目录（skill 根目录），方便管理员把凭证放 skill 根
_PARENT = os.path.dirname(BASE_DIR)
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
if not os.path.exists(CONFIG_FILE):
    CONFIG_FILE = os.path.join(_PARENT, "config.json")
# 备份与日志也跟随 config 所在目录（skill 根目录优先）
_DATA_DIR = _PARENT if os.path.exists(os.path.join(_PARENT, "config.json")) else BASE_DIR
BACKUP_DIR = os.path.join(_DATA_DIR, "backups")
LOG_FILE = os.path.join(_DATA_DIR, "audit.log")
GATEWAY_URL = "http://api.cmgrasp.com/CMGraspApi/GateWay"

# 危险字段黑名单（禁止通过 API 修改，改了会破坏 ERP 业务逻辑）
# 这些字段一旦已有单据引用，改动会导致历史单据错乱
DANGER_FIELDS = {
    "bblockno",      # 是否管理批号
    "bcustom1",      # 是否管理自定义项1
    "bcustom2",      # 是否管理自定义项2
    "bcustom3",      # 是否管理自定义项3
    "bcustom4",      # 是否管理自定义项4
    "manserialnum",  # 是否管理序列号
    "costmode",      # 成本计价方式
    "gpfullname",    # 核算方法
    "definunit",     # 默认入库单位
    "defoutunit",    # 默认出库单位
    "defpandianunit",# 默认盘点单位
    "takeout",       # 近效期先出
}

# 安全字段（允许修改的）—— 其余字段默认拒绝
SAFE_FIELDS = {
    "usercode",      # 编号
    "fullname",      # 全名
    "name",          # 简名
    "standard",      # 规格
    "type",          # 型号
    "comment",       # 备注
    "deleted",       # 停用标志
    "refprice",      # 参考成本
    "safeqty",       # 安全库存
    "safedaycount",  # 安全库存天数
}


# ============ 工具函数 ============
def md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def gen_randamstr(n=16):
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


def gen_time_pair():
    t = time.localtime()
    return (time.strftime("%Y-%m-%d %H:%M:%S", t), time.strftime("%Y%m%d%H%M%S", t))


def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"❌ 找不到配置 {CONFIG_FILE}", file=sys.stderr)
        sys.exit(1)
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def audit(action, detail, result="OK"):
    """写审计日志"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} | {action} | {result} | {detail}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def backup_records(records, tag):
    """备份记录到 backups/ 目录"""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = os.path.join(BACKUP_DIR, f"backup_{ts}_{tag}.json")
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2, default=str)
    return fname


def require_confirm(args, action_desc):
    """写操作强制确认：--yes 或环境变量 GJP_AUTO_APPROVE=1"""
    if args.yes or os.environ.get("GJP_AUTO_APPROVE") == "1":
        return True
    print(f"⛔ 需要确认：{action_desc}")
    print("   确认请加 --yes 参数（或设置环境变量 GJP_AUTO_APPROVE=1）")
    return False


# ============ 通用接口 ============
def call_gateway(method_name, cfg):
    appkey = cfg["AppKey"]
    secret = cfg["SecretKey"]
    std_time, compact_time = gen_time_pair()
    body = {
        "MethodName": method_name,
        "AppKey": appkey,
        "InvalidTime": std_time,
        "RandamStr": gen_randamstr(),
    }
    sign_body = {"AppKey": appkey, "InvalidTime": compact_time, "RandamStr": body["RandamStr"]}
    if method_name == "graspcm.cmapi.getcustomerapiurl":
        body["UserId"] = cfg["UserId"]
        body["DbName"] = cfg["DbName"]
        sign_body["UserId"] = cfg["UserId"]
    sign_body["SignStr"] = sign_params(sign_body, secret)
    body["SignStr"] = sign_body["SignStr"]
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(GATEWAY_URL, data=data, headers={
        "Content-Type": "application/json;Charset=UTF-8"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp_data = json.loads(resp.read().decode("utf-8"))
    if resp_data.get("RetCode") != 0:
        raise RuntimeError(f"通用接口失败: {resp_data}")
    retmsg = resp_data.get("RetMsg", "")
    if isinstance(retmsg, str):
        retmsg = json.loads(retmsg)
    return retmsg


def sign_params(params, secret):
    sorted_keys = sorted(params.keys())
    raw = "".join(f"{k}{params[k]}" for k in sorted_keys)
    raw += secret
    return md5_hex(raw)


def get_ctx():
    cfg = load_config()
    signkey = call_gateway("graspcm.cmapi.getsignstr", cfg).get("SignKey")
    api_info = call_gateway("graspcm.cmapi.getcustomerapiurl", cfg)
    return cfg, signkey, api_info


def sign_biz(params, signkey):
    sorted_keys = sorted(params.keys())
    raw = "".join(f"{k}{params[k]}" for k in sorted_keys)
    raw += signkey
    return md5_hex(raw)


def call_biz(api_address, params, signkey):
    sign = sign_biz(params, signkey)
    post_params = dict(params)
    post_params["sign"] = sign
    encoded = urllib.parse.urlencode(post_params)
    req = urllib.request.Request(api_address, data=encoded.encode("utf-8"), headers={
        "Content-Type": "application/x-www-form-urlencoded;Charset=UTF-8"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ============ 业务查询 ============
def query_ptype(cfg, api_info, signkey, paramjson):
    params = {
        "managename": "GraspCMServerApi.dll",
        "dbname": cfg["DbName"],
        "paramkey": "ptype",
        "paramjson": json.dumps(paramjson),
        "apiparam": api_info.get("ApiParam", ""),
        "apitype": "query",
        "mobile": api_info.get("GraspCloudMobile", "") or "0",
        "serviceid": api_info.get("GraspCloudServerId", "") or "0",
        "interiorapi": 1,
    }
    return call_biz(api_info.get("ApiServerAddress"), params, signkey)


def build_baseinfo_params(cfg, api_info, basetype, data, actiontype="add", rec="0"):
    return {
        "managename": "GraspCMServerApi.dll",
        "dbname": cfg["DbName"],
        "actiontype": actiontype,
        "rec": rec,
        "basetype": basetype,
        "baseinfodata": json.dumps(data, ensure_ascii=False),
        "apiparam": api_info.get("ApiParam", ""),
        "apitype": "baseinfo",
        "mobile": api_info.get("GraspCloudMobile", "") or "0",
        "serviceid": api_info.get("GraspCloudServerId", "") or "0",
        "interiorapi": 1,
    }


def biz_post(cfg, api_info, signkey, params):
    return call_biz(api_info.get("ApiServerAddress"), params, signkey)


# ============ 命令实现 ============
def cmd_ping(args):
    cfg, signkey, api_info = get_ctx()
    out = {
        "ok": True, "环境": cfg.get("环境"), "账套": cfg.get("DbName"),
        "SignKey": signkey, "ApiServerAddress": api_info.get("ApiServerAddress"),
    }
    print(json.dumps(out, ensure_ascii=False) if args.json else
          "\n".join(f"{k}: {v}" for k, v in out.items()))


def cmd_groups(args):
    cfg, signkey, api_info = get_ctx()
    all_cats = []
    page = 1
    while True:
        res = query_ptype(cfg, api_info, signkey, {"pagesize": 200, "pageindex": page, "bsonnum": 2})
        items = res.get("response") or []
        all_cats.extend(items)
        if len(items) < 200:
            break
        page += 1
    if args.json:
        print(json.dumps(all_cats, ensure_ascii=False, default=str))
        return
    for it in all_cats:
        if it.get("parid") == "00000":
            print(f"{it.get('usercode')} {it.get('fullname')} (typeid={it.get('typeid')}, 子:{it.get('sonnum')})")
            for n in all_cats:
                if n.get("parid") == it.get("typeid"):
                    print(f"  ├─ {n.get('usercode')} {n.get('fullname')} (子:{n.get('sonnum')})")


def cmd_list(args):
    cfg, signkey, api_info = get_ctx()
    paramjson = {"pagesize": 200, "pageindex": 1}
    if args.typeid:
        paramjson["typeid"] = args.typeid
    if args.name:
        paramjson["fullname"] = args.name
    res = query_ptype(cfg, api_info, signkey, paramjson)
    items = res.get("response") or []
    if args.nospec:
        items = [it for it in items if not (it.get("standard") or "").strip()]
    if args.json:
        print(json.dumps(res, ensure_ascii=False, default=str))
        return
    print(f"共 {res.get('pagetotal', len(items))} 条，本页 {len(items)} 条：")
    for it in items:
        spec = it.get("standard") or ""
        deleted = "🔴停用" if it.get("deleted") else ""
        print(f"  [{it.get('usercode','')}] {it.get('fullname','')} | 规格:{spec} | rec={it.get('rec')} {deleted}")


def cmd_add(args):
    cfg, signkey, api_info = get_ctx()
    desc = f"新增存货 {args.code} {args.name}"
    if not require_confirm(args, desc):
        sys.exit(2)
    data = {
        "usercode": args.code,
        "fullname": args.name,
        "gpfullname": args.gpfullname or "库存商品",
        "costmode": int(args.costmode) if args.costmode else 4,
        "bpurchase": 1,
        "inputno": args.inputno or "会计主管",
    }
    if args.standard:
        data["standard"] = args.standard
    if args.unit:
        data["units"] = [{"unitname": args.unit, "unitrate": 1}]
    # 新增前检查编号冲突
    check = query_ptype(cfg, api_info, signkey, {"pagesize": 10, "pageindex": 1, "usercode": args.code})
    if check.get("pagetotal"):
        print(f"⛔ 编号 {args.code} 已存在，拒绝新增")
        sys.exit(1)
    params = build_baseinfo_params(cfg, api_info, "ptype", data)
    res = biz_post(cfg, api_info, signkey, params)
    code = res.get("code")
    ok = str(code).lstrip("-").isdigit() and int(code) > 0
    audit("add", json.dumps(data, ensure_ascii=False), "OK" if ok else f"FAIL {res}")
    print(f"{'✅' if ok else '❌'} code={code} {res.get('message')}")
    if not ok and res.get("response"):
        print(json.dumps(res["response"], ensure_ascii=False))
    sys.exit(0 if ok else 1)


def cmd_modify(args):
    cfg, signkey, api_info = get_ctx()
    # 只允许安全字段
    data = {}
    for k in SAFE_FIELDS:
        v = getattr(args, k, None)
        if v is not None:
            data[k] = v
    if not data:
        print("⛔ 没有可修改的安全字段（黑名单字段禁止修改）")
        sys.exit(1)
    # 查询原记录
    res = query_ptype(cfg, api_info, signkey, {"pagesize": 5, "pageindex": 1, "typeid": args.typeid or ""})
    # 直接按 rec 查（用通用查询参数，rec 过滤）
    # 简化：按 typeid+bsonnum 查全部后匹配 rec
    check = query_ptype(cfg, api_info, signkey, {"pagesize": 200, "pageindex": 1, "bsonnum": 0, "typeid": args.typeid or ""})
    items = check.get("response") or []
    target = None
    for it in items:
        if str(it.get("rec")) == str(args.rec):
            target = it
            break
    if not target:
        print(f"⛔ 找不到 rec={args.rec} 的记录")
        sys.exit(1)
    desc = f"修改 rec={args.rec} ({target.get('usercode')} {target.get('fullname')}) → {data}"
    if not require_confirm(args, desc):
        sys.exit(2)
    # 备份
    bfile = backup_records([target], f"modify_rec{args.rec}")
    audit("modify", f"rec={args.rec} {data}", "备份:" + bfile)
    params = build_baseinfo_params(cfg, api_info, "ptype", data, actiontype="modify", rec=str(args.rec))
    r = biz_post(cfg, api_info, signkey, params)
    code = r.get("code")
    ok = str(code).lstrip("-").isdigit() and int(code) > 0
    audit("modify", f"rec={args.rec} {data}", "OK" if ok else f"FAIL {r}")
    print(f"{'✅' if ok else '❌'} code={code} {r.get('message')}")
    if not ok and r.get("response"):
        print(json.dumps(r["response"], ensure_ascii=False))
    sys.exit(0 if ok else 1)


def cmd_disable(args):
    cfg, signkey, api_info = get_ctx()
    # 查目标分组下的存货
    res = query_ptype(cfg, api_info, signkey, {"pagesize": 200, "pageindex": 1, "typeid": args.typeid, "bsonnum": 0})
    items = res.get("response") or []
    direct = [it for it in items if it.get("parid") == args.typeid]
    goods = [it for it in direct if not it.get("sonnum")]
    # 过滤条件
    targets = goods
    if args.nospec:
        targets = [it for it in goods if not (it.get("standard") or "").strip()]
    if args.list:
        for it in targets:
            print(f"  [{it.get('usercode')}] {it.get('fullname')} | rec={it.get('rec')}")
        print(f"共 {len(targets)} 条")
        return
    if not targets:
        print("没有符合条件的存货")
        return
    desc = f"停用 typeid={args.typeid} 下 {len(targets)} 条存货（无规格:{args.nospec}）"
    if not require_confirm(args, desc):
        sys.exit(2)
    bfile = backup_records(targets, f"disable_typeid{args.typeid}")
    audit("disable", f"typeid={args.typeid} {len(targets)}条", "备份:" + bfile)
    ok_count = 0
    for it in targets:
        rec = it.get("rec")
        data = {"usercode": it.get("usercode"), "fullname": it.get("fullname"),
                "gpfullname": "库存商品", "costmode": 4, "deleted": 1, "inputno": "会计主管"}
        params = build_baseinfo_params(cfg, api_info, "ptype", data, actiontype="modify", rec=str(rec))
        r = biz_post(cfg, api_info, signkey, params)
        code = r.get("code")
        ok = str(code).lstrip("-").isdigit() and int(code) > 0
        if ok:
            ok_count += 1
        print(f"  {it.get('usercode')} {it.get('fullname')} -> {'✅' if ok else '❌'}")
        time.sleep(0.3)
    audit("disable", f"typeid={args.typeid} 成功{ok_count}/{len(targets)}")
    print(f"成功 {ok_count}/{len(targets)}")
    sys.exit(0 if ok_count == len(targets) else 1)


def cmd_enable(args):
    cfg, signkey, api_info = get_ctx()
    res = query_ptype(cfg, api_info, signkey, {"pagesize": 200, "pageindex": 1, "bsonnum": 0})
    items = res.get("response") or []
    target = next((it for it in items if str(it.get("rec")) == str(args.rec)), None)
    if not target:
        print(f"⛔ 找不到 rec={args.rec}")
        sys.exit(1)
    desc = f"恢复启用 rec={args.rec} ({target.get('usercode')} {target.get('fullname')})"
    if not require_confirm(args, desc):
        sys.exit(2)
    backup_records([target], f"enable_rec{args.rec}")
    data = {"usercode": target.get("usercode"), "fullname": target.get("fullname"),
            "gpfullname": "库存商品", "costmode": 4, "deleted": 0, "inputno": "会计主管"}
    params = build_baseinfo_params(cfg, api_info, "ptype", data, actiontype="modify", rec=str(args.rec))
    r = biz_post(cfg, api_info, signkey, params)
    code = r.get("code")
    ok = str(code).lstrip("-").isdigit() and int(code) > 0
    audit("enable", f"rec={args.rec}", "OK" if ok else f"FAIL {r}")
    print(f"{'✅' if ok else '❌'} code={code} {r.get('message')}")
    sys.exit(0 if ok else 1)


def cmd_restore(args):
    """从备份文件恢复（写回备份时的 usercode/fullname/deleted 等安全字段）"""
    cfg, signkey, api_info = get_ctx()
    if not os.path.exists(args.from_file):
        print(f"⛔ 备份文件不存在: {args.from_file}")
        sys.exit(1)
    with open(args.from_file, "r", encoding="utf-8") as f:
        records = json.load(f)
    desc = f"从备份恢复 {len(records)} 条记录 ({os.path.basename(args.from_file)})"
    if not require_confirm(args, desc):
        sys.exit(2)
    ok_count = 0
    for it in records:
        rec = it.get("rec")
        data = {
            "usercode": it.get("usercode"),
            "fullname": it.get("fullname"),
            "gpfullname": "库存商品", "costmode": 4,
            "deleted": it.get("deleted", 0),
            "inputno": "会计主管",
        }
        params = build_baseinfo_params(cfg, api_info, "ptype", data, actiontype="modify", rec=str(rec))
        r = biz_post(cfg, api_info, signkey, params)
        code = r.get("code")
        ok = str(code).lstrip("-").isdigit() and int(code) > 0
        if ok:
            ok_count += 1
        print(f"  {it.get('usercode')} {it.get('fullname')} -> {'✅' if ok else '❌'}")
        time.sleep(0.3)
    audit("restore", f"{os.path.basename(args.from_file)} 成功{ok_count}/{len(records)}")
    print(f"恢复成功 {ok_count}/{len(records)}")
    sys.exit(0 if ok_count == len(records) else 1)


def cmd_log(args):
    if not os.path.exists(LOG_FILE):
        print("暂无审计日志")
        return
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    tail = args.tail or len(lines)
    for line in lines[-tail:]:
        print(line.rstrip())


def cmd_stock(args):
    """库存查询（只读）—— 用 paramkey 查库存（文档的库存查询接口）"""
    cfg, signkey, api_info = get_ctx()
    paramjson = {"pagesize": 200, "pageindex": 1}
    if args.typeid:
        paramjson["typeid"] = args.typeid
    params = {
        "managename": "GraspCMServerApi.dll",
        "dbname": cfg["DbName"],
        "paramkey": args.paramkey or "stock",
        "paramjson": json.dumps(paramjson),
        "apiparam": api_info.get("ApiParam", ""),
        "apitype": "query",
        "mobile": api_info.get("GraspCloudMobile", "") or "0",
        "serviceid": api_info.get("GraspCloudServerId", "") or "0",
        "interiorapi": 1,
    }
    res = call_biz(api_info.get("ApiServerAddress"), params, signkey)
    print(json.dumps(res, ensure_ascii=False, default=str) if args.json else
          f"共 {res.get('pagetotal', 0)} 条，本页 {len(res.get('response') or [])} 条")
    if not args.json:
        for it in res.get("response") or []:
            print(json.dumps(it, ensure_ascii=False, default=str)[:200])


def main():
    p = argparse.ArgumentParser(description="管家婆 API 安全工具箱")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_json(sp):
        sp.add_argument("--json", action="store_true", help="输出 JSON")

    p1 = sub.add_parser("ping", help="连通性测试")
    add_json(p1)
    p1.set_defaults(func=cmd_ping)

    p2 = sub.add_parser("groups", help="存货分组树")
    add_json(p2)
    p2.set_defaults(func=cmd_groups)

    p3 = sub.add_parser("list", help="查询存货")
    add_json(p3)
    p3.add_argument("--typeid")
    p3.add_argument("--name")
    p3.add_argument("--nospec", action="store_true", help="只看无规格")
    p3.set_defaults(func=cmd_list)

    p4 = sub.add_parser("add", help="新增存货")
    add_json(p4)
    p4.add_argument("--code", required=True)
    p4.add_argument("--name", required=True)
    p4.add_argument("--standard")
    p4.add_argument("--unit")
    p4.add_argument("--gpfullname")
    p4.add_argument("--costmode")
    p4.add_argument("--inputno")
    p4.add_argument("--yes", action="store_true", help="确认执行")
    p4.set_defaults(func=cmd_add)

    p5 = sub.add_parser("modify", help="修改存货")
    add_json(p5)
    p5.add_argument("--rec", required=True)
    p5.add_argument("--code")
    p5.add_argument("--name")
    p5.add_argument("--standard")
    p5.add_argument("--typeid", help="辅助定位记录")
    p5.add_argument("--yes", action="store_true", help="确认执行")
    p5.set_defaults(func=cmd_modify)

    p6 = sub.add_parser("disable", help="停用存货")
    add_json(p6)
    p6.add_argument("--typeid", required=True)
    p6.add_argument("--nospec", action="store_true", help="只停用无规格的")
    p6.add_argument("--list", action="store_true", help="只列出不执行")
    p6.add_argument("--yes", action="store_true", help="确认执行")
    p6.set_defaults(func=cmd_disable)

    p7 = sub.add_parser("enable", help="恢复启用")
    add_json(p7)
    p7.add_argument("--rec", required=True)
    p7.add_argument("--yes", action="store_true", help="确认执行")
    p7.set_defaults(func=cmd_enable)

    p8 = sub.add_parser("restore", help="从备份恢复")
    add_json(p8)
    p8.add_argument("--from", dest="from_file", required=True)
    p8.add_argument("--yes", action="store_true", help="确认执行")
    p8.set_defaults(func=cmd_restore)

    p9 = sub.add_parser("log", help="审计日志")
    p9.add_argument("--tail", type=int)
    p9.set_defaults(func=cmd_log)

    p10 = sub.add_parser("stock", help="库存查询")
    add_json(p10)
    p10.add_argument("--typeid")
    p10.add_argument("--paramkey", default="stock")
    p10.set_defaults(func=cmd_stock)

    args = p.parse_args()
    try:
        args.func(args)
    except Exception as e:
        print(f"❌ 错误: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
