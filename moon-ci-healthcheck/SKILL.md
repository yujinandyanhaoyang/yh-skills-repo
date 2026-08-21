---
name: moon-ci-healthcheck
description: "Moon 批量 CI 体检与失败分诊。当用户需要批量查询多个服务最近在 Moon 上的流水线/CI 执行情况、统计失败次数、找出最近一次 CI 仍然失败的服务、或判断失败是环境不稳定还是真实问题(接口测试/构建/合并)时使用。触发词:Moon CI 体检、批量查流水线、CI 执行情况、接口测试失败、筛选仍然失败的服务、流水线失败分诊、瞬时失败还是持续失败、moon-ci、CI 失败是环境问题吗。"
display_name: Moon 批量 CI 体检与失败分诊
category: common
owner: yanhao
maintainers:
  - yanhao
team: quality
version: "0.1.0"
status: draft
visibility: team
created_at: '2026-08-21'
updated_at: '2026-08-21'
tags:
  - moon
  - ci
  - pipeline
  - healthcheck
  - triage
permissions:
  - moon-cli(api 只读)
---

# Moon 批量 CI 体检与失败分诊(moon-ci-healthcheck)

对**一批服务**批量查询 Moon 流水线执行情况,统计成功/失败,定位失败 job 的真实原因,并区分"瞬时失败(已自愈,可忽略)"与"最近一次仍失败(需跟进)"。

与 `moon-ops` 的区别:`moon-ops` 面向**单仓库**的部署/环境/排障;本 skill 面向**多服务批量体检 + 失败分诊**,不要求当前在某个 git 仓库内。

下文 `moon` 均指 `npx -y @qunhe/moon-cli@latest`。核心是 `moon api <endpoint>`(类似 `gh api`),因为批量查询没有现成 CLI 子命令。

---

## 一、标准流程(五步)

```
服务清单 → 解析 UUID → 拉流水线模板 → 拉近30天历史 → 失败下钻详情 → 分诊
```

1. **拿到服务清单**:来自用户、CF 页面(用 `confluence` skill 读)或文件。
2. **解析 UUID**:`/moon/openApi/allApp` 全量应用列表,按 `name`/`uuid`/`tag` 精确匹配。
3. **拉流水线模板**:`/moon/pipelineTemplate/query?serviceUuid=<uuid>`,过滤 `isDeleted`,用 `lastRelease.endTime` 判断近期是否活跃。
4. **拉执行历史**:仅对近 N 天有执行的模板调 `/moon/pipelineTemplate/history?templateId=<id>&pageNum=1&pageSize=20`,统计 `SUCCESS/FAILED/KILLED`。
5. **失败下钻**:对每条 `FAILED` 调 `/moon/pipeline/detail?pipelineId=<id>`,定位失败 job 的 `jobType`,按类型分诊。

一键脚本见 [scripts/moon_ci_healthcheck.py](scripts/moon_ci_healthcheck.py),用法见下。

---

## 二、关键 API(`moon api` 调用)

| 用途 | 端点 |
|------|------|
| 全量应用(name→uuid/tag) | `GET /moon/openApi/allApp` |
| 服务的流水线模板 | `GET /moon/pipelineTemplate/query?serviceUuid=<uuid>` |
| 模板执行历史 | `GET /moon/pipelineTemplate/history?templateId=<id>&pageNum=1&pageSize=20` |
| 单条流水线详情 | `GET /moon/pipeline/detail?pipelineId=<id>` |
| 模板最近一次发布 | 模板对象里的 `lastRelease` 字段 |

**字段坑(重要,踩过的)**:
- `pipeline/detail` 的阶段在 **`stages`** 字段(不是 `stageOverviews`);每个 stage 的 job 在 **`jobs`** 字段(不是 `jobOverviews`)。
- job 的最终状态看 **`concludeStatus`**(`FAILED`/`SUCCESS`),`status` 字段在部分 job 上为空。
- 历史接口返回 `{result:[...]}`,流水线状态字段为 `status`、开始时间 `startTime`。
- `allApp` 返回约 1.4MB,先落盘再解析,勿直接全文打印。

详细字段与样例见 [references/moon-api.md](references/moon-api.md)。

---

## 三、失败分诊(按 jobType)

流水线阶段固定为「代码合并 → 构建镜像 → K8S部署」,失败 job 的 `jobType` 决定性质:

| jobType | 阶段 | 性质 | 是否接口测试 |
|---------|------|------|--------------|
| `GIT_MERGE` | 代码合并 | 多为合并冲突/脚本报错 | 否 |
| `COMMON_DOCKER_BUILD` | 构建镜像 | `CLONE_BRANCH_FAILED`/`BUILD_PUSH_FAILED`,多为瞬时 | 否 |
| `KUBERNETES_DEPLOY` | K8S部署 | `timeout`,多为环境不稳定 | 否 |

> **结论范式**:Moon 部署流水线**不跑接口测试**,接口自动化在 **Aegis 平台**独立运行。所以"CI 失败"基本都是合并/构建/部署问题,而非接口测试失败。若用户问"接口测试失败",需明确这一口径差异;接口测试失败的真实修复与补例,请配合本仓库的 [`ci-interface-test-recovery`](../ci-interface-test-recovery/SKILL.md) skill;接口通过率要另查 Aegis。

`job.message` 常见取值:`timeout`、`CLONE_BRANCH_FAILED`、`BUILD_PUSH_FAILED`、`执行脚本信息出错`。

---

## 四、瞬时 vs 持续(是否可忽略)

按用户规则:**失败后最近一次执行已 SUCCESS → 已自愈,可忽略;最近一次仍 FAILED → 需跟进。**

判定口径:对每个服务,取**全部模板合并后按 `startTime` 倒序的第一条**作为"最新一次 CI":
- `SUCCESS` → 已恢复,忽略历史失败;
- `FAILED` → 列入"真正需修复"清单,并附失败 jobType;
- `KILLED` → 人工中断,单独标注,不算失败。

交叉验证:用模板 `lastRelease.endTime/status` 与"历史合并后的最新一条"互相印证,避免漏模板。

---

## 五、一键脚本

```bash
# 服务清单一行一个(服务名即可,脚本自动解析 uuid)
python3 scripts/moon_ci_healthcheck.py services.txt --days 30
```

- `--days N`:统计窗口(默认 30)。
- 输出:每服务 `SUCCESS/FAILED/KILLED` 计数、失败 jobType 分类、最新一次 CI 状态、瞬时/持续判定。
- 依赖:已登录 moon-cli(`moon get user` 能返回身份);内网 npm registry 已配置。

---

## 六、注意事项

- 需要 `moon-cli` 已认证;未认证时先 `moon get user` 验证,失败则引导登录。
- 模板/历史接口分页默认 `pageSize=20`;窗口内执行很多的服务可调大。
- 服务名解析不到时,先用 `tag` 或模糊名称二次确认(可能存在同名多应用,需用 `--app`/uuid 指定)。
- 本 skill 只读,不触发任何部署/ kill 操作。
