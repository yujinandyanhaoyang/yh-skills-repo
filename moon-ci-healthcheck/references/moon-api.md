# Moon API 字段参考(moon api 调用)

所有端点通过 `npx -y @qunhe/moon-cli@latest api "<endpoint>"` 调用,返回 JSON。
`moon api` 支持 `-X`、`--input`、`--jq`(同 `gh api`)。

## 1. 全量应用列表

```
GET /moon/openApi/allApp
```

返回数组,单元素:

```json
{
  "name": "appinfo",
  "pdlName": "devops",
  "sshRepo": "git@gitlab.qunhequnhe.com:<group>/<repo>.git",
  "tag": "cop.kujiale|owt.ep|pdl.devops|service.appInfo",
  "type": "JAVA",
  "uuid": "d80a1a3d-e3f7-11e8-9d74-525400428d91"
}
```

- 服务解析:按 `name` / `uuid` / `tag` 精确匹配;同名多应用需人工确认。
- 体积约 1.4MB,先写文件再用 python 解析。
- 带 `-auto` 后缀的"服务"(如 `saas-buy-portal-auto`)通常是 Aegis 接口自动化工程名,不是 Moon 应用,需映射到基础服务名。

## 2. 流水线模板

```
GET /moon/pipelineTemplate/query?serviceUuid=<uuid>
```

返回数组,单元素关键字段:

```json
{
  "id": 27998,
  "name": "dev部署",
  "env": "dev",
  "isDeleted": false,
  "lastRelease": {
    "id": 5784312,
    "name": "dev部署",
    "status": "SUCCESS",
    "created": "2026-07-17 14:52:15",
    "endTime": "2026-07-17 14:54:44",
    "creator": "<ldap>",
    "operationType": "DEPLOY"
  }
}
```

- 过滤 `isDeleted=true` 的模板。
- `lastRelease.endTime` 是判断"近 N 天是否活跃"的第一道筛选,可大幅减少历史调用。

## 3. 模板执行历史

```
GET /moon/pipelineTemplate/history?templateId=<id>&pageNum=1&pageSize=20
```

返回对象,流水线在 `result` 键:

```json
{ "result": [
  { "id": 5936271, "name": "dev和sit部署", "status": "FAILED",
    "startTime": "2026-08-19 18:04:12", "endTime": "...",
    "creator": "<ldap>", "operationType": "DEPLOY" }
] }
```

- `status` 取值:`SUCCESS` / `FAILED` / `KILLED`。
- 按 `startTime` 过滤统计窗口。

## 4. 流水线详情(失败下钻)

```
GET /moon/pipeline/detail?pipelineId=<id>
```

结构(顶层键):`stages`(注意:**不是** `stageOverviews`)

```json
{
  "id": 5822260, "name": "dev部署", "status": "FAILED",
  "stages": [
    {
      "name": "代码合并", "status": "FAILED",
      "jobs": [
        {
          "id": 304139, "name": "代码合并",
          "jobType": "GIT_MERGE",
          "concludeStatus": "FAILED",
          "message": "FAILED(执行脚本信息出错，详细信息查看日志！)",
          "logFileUrl": "https://moon.qunhequnhe.com/moon/object-storage/.../worker-log/..."
        }
      ]
    }
  ]
}
```

- job 状态看 **`concludeStatus`**(部分 job 的 `status` 为空)。
- 第一个非 `SUCCESS/SKIPPED` 的 stage 即失败点。
- 深挖单 job 日志:`moon logs jobs <jobType>/<jobId>`(来自 moon-ops)。

## 5. jobType 分诊表

| jobType | 阶段 | 典型 message | 性质 |
|---------|------|--------------|------|
| `GIT_MERGE` | 代码合并 | 执行脚本信息出错 | 合并冲突,多为人为/瞬时 |
| `COMMON_DOCKER_BUILD` | 构建镜像 | CLONE_BRANCH_FAILED / BUILD_PUSH_FAILED | 基础设施抖动,多为瞬时 |
| `KUBERNETES_DEPLOY` | K8S部署 | timeout | 环境不稳定,多为瞬时 |

部署流水线没有接口测试阶段;接口自动化在 Aegis 平台执行,不在 Moon CI 里。
