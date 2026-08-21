# CI 接口测试失败自动修复与补例（ci-interface-test-recovery）

处理「接口测试 CI 失败 → 定位根因 → 修复/补充接口测试」的端到端流程。
当用户提供 moon CI 链接、Jenkins aegis-ci 链接、Apollo 测试计划报告链接（含 shareId 分享链接）、或覆盖率低于目标值并要求补例提升覆盖率时触发。

## 触发场景

- 用户贴 moon CI 链接（`moon.qunhequnhe.com/v2/repository/ci/...`）或 Jenkins aegis-ci 构建链接（`jenkins-ci.qunhequnhe.com/job/aegis-ci/<build>/console`）并要求分析接口测试为什么失败
- 用户贴 Apollo 测试计划报告链接（`track/testPlan/reportList?resourceId=...` 或 `sharePlanReport?shareId=...`）并要求排查失败原因
- 用户要求「修复失败用例」「重新触发 CI 验证」「补接口/补用例提升覆盖率」「覆盖率低于目标」等
- 用户要求「和之前一样」处理 CI 失败（沿用历史 SOP）

不适用于：UI E2E 用例失败分析（走 `ui_case_analysis`）、Kaptain 事项/提测管理（走 kaptain skill）。

## 核心判断框架（先说结论）

接口测试 CI 失败，先分三大类再动手，不要一上来就改用例：

| 类别 | 关键特征 | 处理方向 |
|---|---|---|
| **A. 构建/依赖问题** | `error_reason=JENKINS执行失败`（error_type=3）、任务用例数全 null（未执行任何用例）、Jenkins console 里 `mvn test` 阶段 BUILD FAILURE | 修测试工程 pom / 依赖，不是改用例 |
| **B. 用例问题** | HTTP 200 但业务码错误；断言写死数据；测试数据过期/堆积 | 修断言为数据无关、清理堆积、补数据 |
| **C. 服务异常** | HTTP 500 / 下游 RPC 500 / 调用链显示下游服务异常 | 不改用例，向用户汇报具体异常服务 + traceId |

## 标准流程

### 第 1 步：定位 CI 报告对应的任务

输入可能是四种来源之一，按优先级处理：

1. **moon CI 链接**（`ciId=.../jobId=...`）：
   - 用 automation-query 反查数据库：先查 `auto_task_fact`（蛇形）或 `task` 表（驼峰）中该服务的最近任务，用 commit_id 或 jenkins_job_id 精确匹配；
   - 常用：`task_jenkins_job.ci_git_url` 拿测试工程仓库，`task.branchType/commit_id/status/error_reason` 拿任务状态。
2. **Jenkins aegis-ci 链接**（`/job/aegis-ci/<build>/console`）：
   - 先在数据库 `auto_task_fact.report_url` 里搜 `<build>/allure` 反查 task_id；
   - 再用 `task` 表按 task_id 拿 status/error_reason/commit/env/domain/creator。
3. **Apollo 报告链接**（resourceId）：
   - 直接当 testPlanId 调 `test_plan_analysis` 的工具（search → detail → analyze_failures）。
4. **shareId 分享链接**：
   - `shareId` 是分享令牌，**多数直接解析失败**。若用户同时给了用例 caseId 链接（`#/api/definition?caseId=...`），用 `get_test_case` 反查项目 → 计划；
   - 若只有 shareId，尝试 `GET https://apollo.qunhequnhe.com/share/info/get/<shareId>`（公开接口，可返回 shareType + customData=真实报告 ID），再走 test_plan 工具；
   - 仍失败则请求用户补：测试计划 ID / resourceId 报告链接 / cmdb+项目+计划名 / 失败用例 caseId。

### 第 2 步：判断失败类别（A/B/C）

- **看任务状态**：`error_reason=JENKINS执行失败` + 用例数全 null → **A 类**，直接看第 4 步-A；
- **看失败证据包**（`analyze_failures`）：HTTP 200 + 业务码错误 → B/C 类，看响应体；
  - `c=-1` + 业务提示（如「系统错误」「最多保存20个」「虚体已到期」「创建UGC任务失败…任务在执行中」）→ B 类（数据/断言/幂等）或 C 类（服务）结合调用链判断；
  - HTTP 500 / 调用链显示下游 RPC 失败 → **C 类**，汇报服务方；
- **重跑确认**：单用例重跑通过 → 偶发/环境抖动；稳定失败 → 持续问题。

### 第 3 步：B 类用例问题——按子类修复

| 子类 | 特征 | 修复方式（SIT/测试环境允许改） |
|---|---|---|
| **B1 断言过脆** | 查询接口返回空数组/空数据但服务正常（`c=0`、d 为空）；断言写死「必须有数据/具体 ID」 | 断言改为**数据无关**：HTTP 200 + `$.c=0`（用 `update_test_case`）；参考历史：freetable「查询自定义搜索条件」、PQ「模型专题列表v2」 |
| **B2 数据堆积超限** | 报错含「最多保存 N 个」「上限」；每次巡检新增数据从不清理 | 存量清理（DELETE 接口）+ 用例挂**前置 groovy 清理脚本**实现「先删后存」幂等 |
| **B3 测试数据过期/失效** | 断言期望固定数据（商品 ID/账号/分类）不存在；同一账号同参数重跑成功/失败对比 | 换有效数据账号/数据，或改数据无关断言；**授权/任务型接口注意对同一目标不可复用** |
| **B4 任务锁冲突** | 报错含「是否有任务在执行中」「unique lock」；同账号并发/连续执行互相抢锁 | 用例前置脚本**查锁等待/错峰** + 保留重试 |

### 第 4 步-A：A 类构建问题——修测试工程

- 从 `task_jenkins_job.ci_git_url` 拿**测试工程仓库**（如 `test/site/interface_xxx.git`），不是被测服务仓库；
- 看 Jenkins console 的 `mvn test` 阶段报错：
  - 依赖缺失（`Could not resolve dependencies ... Failure to find xxx in nexus`）→ 改 pom：
    - 先确认是**直接依赖还是传递依赖**（传递依赖需在引入方 `<exclusions>` 排除 + 显式声明可用版本）；
    - 到 nexus 验证缺失版本 vs 可用版本（`1.7-SNAPSHOT` 404 / `1.7` 200）；
  - 测试用例「未找到名称为 XXXX 的测试文件」+ `api is []` → 是 litmus 增量筛选，本身不是失败点，看后续 `mvn test`；
- 修复后 commit 推送，**注意 push 触发 MR**（`merge_request.create` 需要新提交 + push options 或 API 权限）；
- **影响范围判断**：共享测试框架（如 `com.qunhe.test:apollo`）的缺陷会波及所有依赖它的服务测试工程——单仓库修复只救本服务，框架级修复才根治。

### 第 5 步：补充接口测试提升覆盖率（覆盖率低于目标时）

流程：**定位缺口 → 分析变更 → 补接口定义 → 生成用例（正常+异常）→ 执行验证 → 绑定计划**。

1. **反查任务**：moon CI → `task` 表拿 task_id + commit_id + 覆盖率（coverage/delta_coverage）；
2. **拿覆盖率缺口**：有 taskId 时调 `coverage-analysis`（skill_api_task_coverage_analysis）→ 读 JaCoCo 增量报告（`/dc/index.html`）→ 定位**未覆盖类与方法**；变更集中在某个 ServiceImpl → 该方法就是缺口；
3. **分析 commit**：拿被测服务仓库 git 权限（用户提供 token 或有 API 权限）读 commit diff，确认新增功能及对应 HTTP 接口（Controller → 路径常量 → 完整 URL + 请求 DTO）；
4. **补接口定义**：`create_api_definition`（method+path，注意同项目同 method+path 已存在会失败）；
5. **生成用例**：正常场景 + 异常场景各 1 条；异常场景覆盖服务端错误分支（如账号不存在 → `c=-1` + subCode）；参考现有同模块用例的身份头与断言风格；
6. **执行验证**：`run_test_case` + `get_exec_result` 确认实际响应，再按实测更新断言；
7. **绑定计划**：`test_plan_bind_cases`（apiCaseIds + environmentId），确认计划用例数增加；
8. **验证**：单用例复跑通过；提示用户下次环境部署触发巡检（BY_ENVIRONMENT_DEPLOY）会自动包含新用例。

### 第 6 步：汇报与收尾

按输出要求（见下）给出结论，并明确：
- 命中哪个 skill、用哪些工具、关键过滤条件与口径；
- 已修复项 + 验证证据；
- **服务异常**必须点名具体服务（CMDB）+ 接口 + traceId + 建议反馈对象；
- 不能执行/验证的边界如实说明（如无法触发 Jenkins、无 gitlab 权限、无法读 moon SPA 页面）。

## 常见坑与经验

- **moon 页面卡「构建MOON环境」**：先查 `task` 表有没有新任务（status=40 卡环境准备）→ 查环境 `aegis2_xxx` 是否有 pod（queryIns）/LastRelease 是否为空；moon 页面 Loading 常是前端同步问题，看数据库 task 实际状态（status=90 即成功），`noticeComplete` 回调 111 连接错误是平台老毛病。
- **Jenkins console `Finished: SUCCESS` 是假象**：真正判定在 callback `errorType`（0 成功 / 3 JENKINS执行失败），要看数据库 `error_reason`。
- **分享链接**：shareId 当 testPlanId/reportId 直接传大多失败，用 `/share/info/get/<shareId>` 解析或要 resourceId/caseId。
- **gitlab 访问**：环境默认无 gitlab 凭据（qunhe-token 非 gitlab PAT）；需要用户提供 `write_repository`（克隆/推送）或 +`api` scope（创建 MR）的 token；token 会过期。
- **二方包检测通知**（捕将/思行/火山规则）针对**被测服务业务仓库**，与接口测试工程仓库无关，别混改。
- **代理/测试环境**：用例绑定环境用 `runWithPlanEnv=true` 跟随计划；单条重跑可能因环境绑定不同出现差异。
