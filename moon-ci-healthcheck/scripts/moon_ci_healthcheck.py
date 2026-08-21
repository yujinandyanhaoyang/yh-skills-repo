#!/usr/bin/env python3
"""Moon 批量 CI 体检与失败分诊。

用法:
    python3 moon_ci_healthcheck.py services.txt --days 30

services.txt 一行一个服务名(name/uuid/tag 均可)。脚本会:
  1) /moon/openApi/allApp 解析 UUID
  2) /moon/pipelineTemplate/query 拉模板
  3) /moon/pipelineTemplate/history 拉近 N 天执行
  4) /moon/pipeline/detail 对 FAILED 下钻失败 jobType
  5) 输出每服务计数、失败分类、最新一次 CI 状态、瞬时/持续判定

只读,不触发部署/kill。依赖已登录的 moon-cli。
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import subprocess
import sys
from collections import defaultdict

NPX = ["npx", "-y", "@qunhe/moon-cli@latest", "api"]

JOBTYPE_LABEL = {
    "GIT_MERGE": "代码合并",
    "COMMON_DOCKER_BUILD": "镜像构建",
    "KUBERNETES_DEPLOY": "K8S部署",
}


def moon_api(endpoint, timeout=120):
    """调用 moon api,返回解析后的 JSON;失败返回 None。"""
    try:
        out = subprocess.run(
            NPX + [endpoint],
            capture_output=True, text=True, timeout=timeout,
        )
        if out.returncode != 0:
            return None
        return json.loads(out.stdout)
    except Exception:
        return None


def load_apps():
    data = moon_api("/moon/openApi/allApp", timeout=180)
    if not isinstance(data, list):
        sys.exit("拉取 /moon/openApi/allApp 失败,请确认 moon-cli 已登录(moon get user)。")
    by_name, by_uuid, by_tag = {}, {}, {}
    for a in data:
        by_name.setdefault(a.get("name"), []).append(a)
        by_uuid[a.get("uuid")] = a
        by_tag[a.get("tag")] = a
    return by_name, by_uuid, by_tag


def resolve(svc, by_name, by_uuid, by_tag):
    if svc in by_uuid:
        return by_uuid[svc]
    if svc in by_tag:
        return by_tag[svc]
    cand = by_name.get(svc, [])
    if len(cand) == 1:
        return cand[0]
    if len(cand) > 1:
        print(f"  [!] 服务 {svc} 存在多个同名应用,请用 uuid/tag 指定: "
              f"{[c.get('tag') for c in cand]}", file=sys.stderr)
    return None


def recent_templates(tpls, cutoff):
    out = []
    for t in tpls or []:
        if t.get("isDeleted"):
            continue
        lr = t.get("lastRelease") or {}
        if (lr.get("endTime") or "") >= cutoff:
            out.append((t["id"], t.get("name", ""), lr))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("services", help="服务清单文件,一行一个")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--page-size", type=int, default=20)
    args = ap.parse_args()

    cutoff = (dt.datetime.now() - dt.timedelta(days=args.days)).strftime("%Y-%m-%d")
    names = [l.strip() for l in open(args.services) if l.strip() and not l.startswith("#")]
    print(f"统计窗口: 近{args.days}天 (>= {cutoff}),服务数 {len(names)}\n")

    by_name, by_uuid, by_tag = load_apps()

    svc_pipes = defaultdict(list)   # svc -> [pipeline]
    unresolved = []
    inactive = []

    def fetch_hist(svc, tid):
        data = moon_api(f"/moon/pipelineTemplate/history?templateId={tid}"
                        f"&pageNum=1&pageSize={args.page_size}")
        items = data.get("result") if isinstance(data, dict) else data
        return svc, items if isinstance(items, list) else []

    hist_jobs = []
    for svc in names:
        app = resolve(svc, by_name, by_uuid, by_tag)
        if not app:
            unresolved.append(svc)
            continue
        tpls = moon_api(f"/moon/pipelineTemplate/query?serviceUuid={app['uuid']}")
        act = recent_templates(tpls, cutoff)
        if not act:
            inactive.append(svc)
            continue
        for tid, _name, _lr in act:
            hist_jobs.append((svc, tid))

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for svc, items in ex.map(lambda j: fetch_hist(*j), hist_jobs):
            for p in items:
                st = p.get("startTime") or p.get("created") or ""
                if st >= cutoff:
                    svc_pipes[svc].append(p)

    # 失败下钻
    failed_pids = {}
    for svc, pipes in svc_pipes.items():
        for p in pipes:
            if p.get("status") == "FAILED":
                failed_pids[p["id"]] = svc

    fail_cat = defaultdict(lambda: defaultdict(int))  # svc -> jobtype -> n

    def fetch_detail(pid):
        return pid, moon_api(f"/moon/pipeline/detail?pipelineId={pid}")

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for pid, d in ex.map(fetch_detail, list(failed_pids)):
            svc = failed_pids[pid]
            if not isinstance(d, dict):
                fail_cat[svc]["UNKNOWN"] += 1
                continue
            for s in d.get("stages", []):
                if s.get("status") in ("FAILED", "FAILURE"):
                    hit = False
                    for j in s.get("jobs", []):
                        if j.get("concludeStatus") in ("FAILED", "FAILURE") \
                                or j.get("status") in ("FAILED", "FAILURE"):
                            fail_cat[svc][j.get("jobType", "UNKNOWN")] += 1
                            hit = True
                    if not hit:
                        fail_cat[svc]["UNKNOWN"] += 1
                    break

    # 汇总输出
    print(f"{'服务':32s} {'总':>3s} {'成功':>4s} {'失败':>4s} {'中断':>4s}  "
          f"最新一次CI            失败原因        判定")
    need_fix = []
    for svc in names:
        if svc in unresolved:
            print(f"{svc:32s}  -- 未解析到 Moon 应用(可能为 Aegis 工程名,请映射基础服务)")
            continue
        if svc in inactive:
            print(f"{svc:32s}   近{args.days}天无执行")
            continue
        pipes = sorted(svc_pipes[svc], key=lambda x: x.get("startTime", ""), reverse=True)
        total = len(pipes)
        ns = sum(1 for p in pipes if p.get("status") == "SUCCESS")
        nf = sum(1 for p in pipes if p.get("status") == "FAILED")
        nk = sum(1 for p in pipes if p.get("status") == "KILLED")
        latest = pipes[0]
        ls = latest.get("status")
        cats = ";".join(f"{JOBTYPE_LABEL.get(k,k)}x{v}" for k, v in fail_cat[svc].items()) or "-"
        if nf == 0:
            verdict = "无失败"
        elif ls == "SUCCESS":
            verdict = "瞬时·已自愈(可忽略)"
        elif ls == "FAILED":
            verdict = "持续·需跟进"
            need_fix.append(svc)
        else:
            verdict = f"最新为{ls}·人工确认"
        print(f"{svc:32s} {total:>3d} {ns:>4d} {nf:>4d} {nk:>4d}  "
              f"{latest.get('startTime','')} {ls:8s} {cats:14s} {verdict}")

    print("\n== 结论 ==")
    if need_fix:
        print("最近一次 CI 仍失败、真正需跟进的服务:")
        for s in need_fix:
            cats = ";".join(f"{JOBTYPE_LABEL.get(k,k)}x{v}" for k, v in fail_cat[s].items())
            print(f"  - {s}  ({cats})")
        print("注:以上失败均为合并/构建/部署阶段,Moon 流水线不跑接口测试;"
              "接口自动化失败请另查 Aegis。")
    else:
        print("没有最近一次 CI 仍失败的服务;历史失败均已自愈(瞬时,可忽略)。")


if __name__ == "__main__":
    main()
