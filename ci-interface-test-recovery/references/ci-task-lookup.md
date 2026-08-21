# CI 报告 → Aegis 任务反查（automation-query 脚本）

本 reference 沉淀「moon / Jenkins / Apollo 报告 → Aegis task」的反查路径与关键表结构。

## 脚本调用方式

automation-query skill 通过 `execute_script` 执行 `scripts/automation_query.sh`，参数按 `source / sql` 传递：

```text
source: api   # 接口自动化数据源
sql: SELECT ... LIMIT n   # 只能单条 SELECT
```

之前成功调用方式（参数多段拆分）：

```
execute_script(skillId="automation-query", script="scripts/automation_query.sh",
  args=["api", "sql", "<SELECT 语句>"])
```

若工具要求其他形态，先读该 skill 的 reference（`references/api-data.md`）确认。

## 关键表与字段

### `application`（服务）
- `id`：服务 ID（接口自动化）
- `name`：服务名（如 `uic-passport`）
- `test_name`：测试组
- `project_id`：敏捷组/项目组 ID
- `git_repo`：被测服务代码仓库（如 `git@gitlab.qunhequnhe.com:growth/uic-passport.git`）
- `is_delete`：0 为有效

### `auto_task_fact`（蛇形，覆盖率/趋势事实表）
- `task_id`、`application_id`
- `passed_cases / total_cases / skipped_cases / failed_cases`
- `coverage`、`delta_coverage`（增量覆盖率）
- `start_time`、`report_url`（含 `/allure`，可反查 Jenkins build 号）
- `branch_type`：`dailyBuild` / NIGHTLY 等
- `status`

### `task`（驼峰，任务主表）
- `id`（主键，即 task_id）
- `taskId`（业务任务 ID，查询时注意主键是 `id`）
- `status`：90=成功，91=失败，40=进行中（卡环境/部署）
- `errorReason` / `error_reason`：失败原因（如 `JENKINS执行失败`）
- `errorType` / `error_type`：3=JENKINS执行失败
- `branchType` / `branch_type`
- `commitId` / `commit_id`：被测代码 commit
- `env` / `domain`：如 env=fe / domain=aegis2_atdrn
- `creator`：触发来源（`CI_RUN_OLD_ENV`=旧环境 CI，`auto`）
- `coverage` / `deltaCoverage` / `coreCoverage`
- `totalCases / passedCases / failedCases`：**全 null = 未执行任何用例（构建阶段失败）**
- `imageName` / `image_name`：部署镜像（含 commit+时间戳）

### `task_jenkins_job`（Jenkins 关联）
- `task_id` / `taskId`
- `jenkins_job_id` / `job_id`（Jenkins build 号）
- `ci_git_url`：**测试工程代码仓库**（如 `git@gitlab.qunhequnhe.com:test/site/interface_uicpassport.git`）——注意与 `application.git_repo`（被测服务仓库）不同！
- `branch` / `ci_branch`：测试工程分支

## 反查模板

### Jenkins build → task（先搜 report_url）
```sql
SELECT task_id, application_id, status, start_time, report_url
FROM auto_task_fact
WHERE report_url LIKE '%aegis-ci/320272/allure%'
LIMIT 5
```

### 服务最近任务（含状态与错误）
```sql
SELECT id, taskId, status, errorReason, errorType, branchType, commitId,
       env, domain, creator, coverage, deltaCoverage,
       totalCases, passedCases, failedCases, startTime, imageName
FROM task
WHERE applicationId = (SELECT id FROM application WHERE name = '{{服务名}}' AND is_delete = 0)
ORDER BY id DESC
LIMIT 30
```

### 测试工程仓库
```sql
SELECT task_id, ci_git_url, branch
FROM task_jenkins_job
WHERE task_id = {{task_id}}
LIMIT 5
```

### 判定要点
- `status=91 + errorReason='JENKINS执行失败' + 用例数全 null` → **构建阶段失败**（A 类），看 Jenkins console 的 `mvn test` 报错；
- `status=90` → 任务成功（即使 moon 页面 Loading）；
- 同一 commit + 同一镜像在不同 env 一成一败 → 排除代码/镜像问题，指向环境部署链路。

## 环境生命周期（moon 每次 CI 建新环境）

- moon CI 每次创建随机名环境（`aegis2_xxx`），测试完删除；
- 环境卡住特征：环境 Status=RUNNING 但 `LastReleaseBranchName/Commit/Date 为空`、`queryIns 无实例` → 环境创建后未发布代码 → 接口测试 task status=40 卡等待；
- moon 页面 Loading 常是 `noticeComplete` 回调 111 连接错误，后端 task 可能已 status=90。
