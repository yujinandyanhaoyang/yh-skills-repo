# 覆盖率缺口定位与补例（coverage-analysis + api_case_generation）

本 reference 沉淀「覆盖率低于目标 → 定位未覆盖代码 → 补接口定义与用例 → 绑定计划」的完整 SOP。

## 覆盖率数据来源

- **task 表字段**：`coverage`（全量覆盖率）、`delta_coverage`（增量覆盖率）、`core_coverage`（核心覆盖率）。
- **有 taskId 时**：调 `coverage-analysis` skill 的 `skill_api_task_coverage_analysis`（arguments 传 `{"taskId": <id>}`），拿到 taskDetail 原始 envelope，含：
  - `JaCoCo 全量报告链接`：`https://aegis2-prod.qunhequnhe.com/<appId>/<taskId>/fc/index.html`
  - `增量报告链接`：`https://aegis2-prod.qunhequnhe.com/<appId>/<taskId>/dc/index.html`
- 这两个链接是公开可下载的（WebFetch/curl 可访问）。

## JaCoCo 报告解析要点

- **fc = 全量**，**dc = 增量**（本次 commit 相对基线的真实新增代码覆盖）。
- 增量报告关键字段：
  - `指令覆盖（Instruction）/ 分支覆盖（Branch）`
  - `real Missed Lines 6/6`：**本次变更真实新增行全部未覆盖** → 覆盖率下降的直接根因。
- 逐层下钻：包 → 类 → 方法级页面。类页（`xxx.html`）含每个方法的行覆盖；源码页（`xxx.java.html`）用 `<span class="fc|nc|pc" id="Lxx">` 标记已覆盖/未覆盖行。
- **覆盖率不足接口的判定**：先全量列覆盖率不足接口，再列完全未覆盖接口；对每个 API 说明哪些代码分支/行/参数/异常路径未覆盖及补测建议。禁止用包/类/模块 Top 替代全量清单。

## 代码变更分析（git）

- **测试工程仓库** ≠ **被测服务仓库**：
  - 被测服务仓库：`application.git_repo`（如 `growth/uic-passport.git`）——看 commit diff / 接口实现；
  - 测试工程仓库：`task_jenkins_job.ci_git_url`（如 `test/site/interface_xxx.git`）——改 pom / 用例数据。
- 无 gitlab 凭据时，环境内 `QUNHE_TOKEN` 等业务 token **不是** gitlab PAT；需用户提供 `write_repository` 权限 token（克隆/推送），创建 MR 需 +`api` scope。
- 看增量变更：`git log` / `git diff baseline..target`（baseline 在 task 记录或增量报告中有：如 `release/20260818:8e7d78b`）。
- **方法级功能 → HTTP 接口的映射**：方法名（如 `sendOpenAccountResetPasswordMail`）→ 在 Controller 里搜调用点 → 找路径常量（如 `PassPortCustomerRpcApis.RPC_XXX`）→ 拼出完整 URL（前缀 + 常量值）→ 确认请求 DTO。

## 补接口定义

用 `api_case_generation` skill：
1. `get_projects_by_cmdbtag` / `get_environments_by_project`：定位项目、环境 ID（推荐环境）；
2. `get_modules` / `get_apis_by_module`：确认接口是否已有定义（同项目同 method+path 已存在会创建失败）；
3. `create_api_definition`：method+path+目录+请求配置；
4. `get_environments_by_project` 返回的 cmdbtag/appName 可喂给流量工具。

## 生成用例（正常+异常）

用 `skill_apollo_ai_generate_test_case`：
- **正常场景**：走通完整业务链路（含本次变更代码分支）；
- **异常场景**：覆盖服务端错误分支（如账号不存在 → `c=-1` + `subCode`；无效 token → 特定错误码）；
- 身份头参考同模块现有成功用例；基于真实流量样本生成时，把 `prepare_headers_from_traffic` 返回的 keptHeaders 透传为 headers；
- **必须实测后再定断言**：`run_test_case` → `get_exec_result` 看真实响应 → 再 `update_test_case` 补精确断言（HTTP 200 + `$.c` + 业务字段），不要凭猜测写断言。

## 绑定计划与验证

- `test_plan_bind_cases`（apiCaseIds + environmentId）绑定到计划，确认计划用例数增加；
- 单用例复跑验证通过；
- 计划是 BY_ENVIRONMENT_DEPLOY / KUAFU_MOON_CI 触发的，不要手动重跑干扰；提示用户下次环境部署触发巡检会自动执行新用例并刷新覆盖率。

## 历史经验（已证实的修复模式）

| 场景 | 根因 | 修复 |
|---|---|---|
| PQ 模型专题列表v2/tags 空数据 | 断言写死必须有数据，测试账号下数据为空 | 断言改 HTTP 200 + `$.c=0` 数据无关 |
| freetable 保存自定义搜索条件堆积超 20 | 每次巡检新增从不清理 | 前置 groovy「先删后存」幂等脚本 |
| uic-passport 开账户重置密码邮件 0 覆盖 | 新增功能无测试用例 | 补 2 接口 × (正常+异常) 4 用例，绑定计划 182→186 |
