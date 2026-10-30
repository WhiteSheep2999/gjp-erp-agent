#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
管家婆云工贸 API 对接客户端
文档: download/管家婆API/基础资料新增接口.md
流程:
  1. 通用接口 -> 获取 SignKey + ApiServerAddress(ApiParam)
  2. 业务接口 -> 基础资料新增 / 单据新增
签名算法: 参数按 Key 字母排序, Key+Value 拼接, 尾部加 SecretKey/SignKey, MD5 32位小写
"""
import hashlib
import json
import os
import random
import string
import time
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
GATEWAY_URL = "http://api.cmgrasp.com/CMGraspApi/GateWay"

# 测试环境默认 API 地址（可从通用接口返回 ApiServerAddress 覆盖）
TEST_API_ADDRESS = None


def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def md5_hex(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def gen_randamstr(n=16):
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


def now_str():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def now_compact():
    return time.strftime("%Y%m%d%H%M%S")


def gen_time_pair():
    """同一时刻生成 (标准格式, 紧凑格式)，保证签名与请求体时间一致"""
    t = time.localtime()
    return (time.strftime("%Y-%m-%d %H:%M:%S", t), time.strftime("%Y%m%d%H%M%S", t))


def sign_params(params: dict, secret: str) -> str:
    """通用接口签名：参数按 Key 字母排序, Key+Value 拼接, 尾部+Secret, MD5 小写"""
    sorted_keys = sorted(params.keys())
    raw = "".join(f"{k}{params[k]}" for k in sorted_keys)
    raw += secret
    return md5_hex(raw)


def call_gateway(method_name: str, params: dict, cfg: dict) -> dict:
    """调用管家婆总服务器通用接口"""
    appkey = cfg["AppKey"]
    secret = cfg["SecretKey"]
    # 签名与请求体必须用同一个时间（紧凑格式参与签名，请求体用标准格式）
    std_time, compact_time = gen_time_pair()
    body = {
        "MethodName": method_name,
        "AppKey": appkey,
        "InvalidTime": std_time,
        "RandamStr": gen_randamstr(),
    }
    # 按接口要求补充参数
    if method_name == "graspcm.cmapi.getcustomerapiurl":
        body["UserId"] = cfg["UserId"]
        body["DbName"] = cfg["DbName"]
    # 签名参数：getsignstr 只排 AppKey/InvalidTime/RandamStr；getcustomerapiurl 排 AppKey/InvalidTime/RandamStr/UserId（DbName 不参与签名，只在请求体）
    sign_body = {"AppKey": appkey, "InvalidTime": compact_time, "RandamStr": body["RandamStr"]}
    if method_name == "graspcm.cmapi.getcustomerapiurl":
        sign_body["UserId"] = cfg["UserId"]
        # DbName 不参与签名
    sign_body["SignStr"] = sign_params(sign_body, secret)
    body["SignStr"] = sign_body["SignStr"]

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(GATEWAY_URL, data=data, headers={
        "Content-Type": "application/json;Charset=UTF-8",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp_data = json.loads(resp.read().decode("utf-8"))
    if resp_data.get("RetCode") != 0:
        raise RuntimeError(f"通用接口失败: {resp_data}")
    retmsg = resp_data.get("RetMsg", "")
    # RetMsg 是字符串, 手动转 json
    if isinstance(retmsg, str):
        retmsg = json.loads(retmsg)
    return retmsg


def get_signkey(cfg: dict) -> str:
    """获取 SignKey（业务接口签名用）"""
    res = call_gateway("graspcm.cmapi.getsignstr", {}, cfg)
    return res.get("SignKey")


def get_api_address(cfg: dict) -> dict:
    """获取程序 Api 地址 + ApiParam"""
    res = call_gateway("graspcm.cmapi.getcustomerapiurl", {}, cfg)
    return res


def sign_biz(params: dict, signkey: str) -> str:
    """业务接口签名：参数(除sign)按 Key 字母排序, Key+Value 拼接, 尾部+SignKey, MD5 小写"""
    sorted_keys = sorted(params.keys())
    raw = "".join(f"{k}{params[k]}" for k in sorted_keys)
    raw += signkey
    return md5_hex(raw)


def call_biz(api_address: str, params: dict, signkey: str) -> dict:
    """调用业务接口（x-www-form-urlencoded）"""
    # 签名用原始值（不 URLEncode）
    sign = sign_biz(params, signkey)
    post_params = dict(params)
    post_params["sign"] = sign
    # 传参时 value 全部 URLEncode
    encoded = urllib.parse.urlencode(post_params)
    req = urllib.request.Request(api_address, data=encoded.encode("utf-8"), headers={
        "Content-Type": "application/x-www-form-urlencoded;Charset=UTF-8",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_baseinfo_params(cfg: dict, api_info: dict, basetype: str, baseinfodata: dict,
                          actiontype: str = "add", rec: str = "0") -> dict:
    """构造基础资料新增接口参数"""
    return {
        "managename": "GraspCMServerApi.dll",
        "dbname": cfg["DbName"],
        "actiontype": actiontype,
        "rec": rec,
        "basetype": basetype,
        "baseinfodata": json.dumps(baseinfodata, ensure_ascii=False),
        "apiparam": api_info.get("ApiParam", ""),
        "apitype": "baseinfo",
        "mobile": api_info.get("GraspCloudMobile", "") or "0",
        "serviceid": api_info.get("GraspCloudServerId", "") or "0",
        "interiorapi": 1,
    }


def add_ptype(cfg: dict, api_info: dict, signkey: str, ptype_data: dict) -> dict:
    """新增存货档案（基础资料类型 ptype）"""
    params = build_baseinfo_params(cfg, api_info, "ptype", ptype_data)
    api_address = api_info.get("ApiServerAddress") or TEST_API_ADDRESS
    return call_biz(api_address, params, signkey)


def main():
    cfg = load_config()
    print(f"环境: {cfg['环境']}  账套: {cfg['DbName']}  用户: {cfg['UserId']}")
    print("1. 获取 SignKey...")
    signkey = get_signkey(cfg)
    print(f"   SignKey: {signkey}")
    print("2. 获取 API 地址...")
    api_info = get_api_address(cfg)
    addr = api_info.get("ApiServerAddress")
    print(f"   ApiServerAddress: {addr}")
    print(f"   GraspCloud: {api_info.get('GraspCloud')}  Mobile: {api_info.get('GraspCloudMobile')}  ServerId: {api_info.get('GraspCloudServerId')}")
    print("   ApiParam 长度:", len(api_info.get("ApiParam", "")))
    return signkey, api_info


if __name__ == "__main__":
    signkey, api_info = main()
