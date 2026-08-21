---
name: ui-autotest-autofix
description: 从 Jenkins allure 报告诊断 UI 自动化失败用例，在 hades-kuboss-test 仓库做最小定位器级修复，推送并建 MR，交 Apollo 复跑收敛。触发词：allure 报告、jenkins-uitest-linux、UI 用例失败/修复、build 号链接。
---

# UI 自动化失败诊断与修复闭环

只做代码层分析与修改；容器无浏览器，**不运行 UI case、不伪造运行结果**。复跑由用户在 Apollo/Jenkins 触发。

## 0. 凭证与边界（先读）

| 用途 | 凭证 | 注意 |
|---|---|---|
| 读 Jenkins（构建/allure/console） | `curl -sg -u '<JENKINS_USER>:<JENKINS_API_TOKEN>' <JENKINS_HOST>/...`（Jenkins 个人设置页生成 API Token，自行保管，勿入库） | 只读；触发构建需另有 Build 权限 |
| clone/push/建 MR | Jenkins 构建参数里的 `gitlabToken`（qacenter 账号）：`https://qacenter:<token>@gitlab.qunhequnhe.com/test/site/hades-kuboss-test.git` | **禁止用 yanhao 的 token 推送/建 MR**（yanhao 不能合并自己发起的 MR） |

- 默认仓库 `test/site/hades-kuboss-test`，基线 `master`；分支命名 `feature/yanhao-<YYYYMMDD>`。
- 最终回复三段式：`## 结果` / `## 产物` / `## 验证边界`（已完成/未执行/建议外部验证）。

## 1. 取证清单（按序，内网可匿名访问）

设 build 号 N：

1. **构建参数**（确认跑的分支、计划、拿 CI token）：
   `/job/jenkins-uitest-linux/N/api/json?tree=result,actions[parameters[name,value]]`
2. **allure 汇总**：`/job/jenkins-uitest-linux/N/allure/widgets/summary.json`
3. **失败清单**：`.../allure/data/suites.json` → 递归 walk，叶子节点 `status in (failed,broken)` 取 name+uid
4. **用例详情**：`.../allure/data/test-cases/<uid>.json` →
   - `statusMessage`（报错选择器/断言）、`statusTrace`（`__tests__/...js:行号`）
   - `testStage.attachments`：Screenshot / Babel错误收集 / CaughtConsoleError / CaughtNetworkError
5. **截图**：`.../allure/data/attachments/<source>` 下载后**直接用 Read 看**（多模态），截图是最直接证据
6. **控制台日志**：`/job/jenkins-uitest-linux/N/consoleText` → 用例段内的真实点击序列

证据冲突时以下载更多证据解决，不猜。

## 2. 控制台日志判读语义（pybell 行为，血泪总结）

- **`[click success]` ≠ 生效**：click 是坐标点击，被遮罩/loading mask/弹窗挡住时报 success 但空跑。
- **`waitForByText` 超时只记 warn 不抛错**（fail-soft）→ 只能当等待闸门，不能当断言。
- **`waitFor`/`click`/`keyboardType` 找不到会抛错**（hard）→ 用例失败点多是这类，报错即行号。
- `[Page Load]/[Page Domcontentloaded]` 判断导航/硬跳转；**点击后无任何页面事件** = 可能 `window.open` 新标签或空跑。
- 想在看板留分支痕迹：测试里加 `console.log`，会进 Jenkins console。

## 3. 根因分类与修复模式（对号入座）

1. **前端改版选择器失效**（字段删/改 id、按钮结构变）→ 线上 bundle 核实后修选择器。bundle 取法：`https://beta-salesplatform.qunhequnhe.com/bdsystem` 的 entry HTML → CDN `qhstaticssl.kujiale.com/__p/static/-saas-fe-bdsystem-front/` 下 `pages/index/entry.*.js`（路由→懒加载 chunk：`component:function(){return e.e(<id>)...}`）；中文常 `\uXXXX` 转义，解码再搜；自研 Modal 在 `qunhe.*.js`，容器 `role="presentation"`、隐藏时 style 含 hidden。**bundle 是最后手段**，截图+日志能定因就别挖 bundle。
2. **固定下标 XPath 失配**（隐藏预渲染弹窗、关闭后残留 modal 使 `[N]` 错位/越界）→ 改 `[last()]`（portal 挂 DOM 末尾，可见弹窗最后挂载）或限定可见弹窗：`//div[@role='presentation' and not(contains(@style,'hidden'))]//...`。仓库既有 idiom：`productYesLast()`、`confirmButtonLast`、`hiddenSubmitOK`（lib/selector/）。
3. **坐标点击被 loading 遮罩吞**（弹窗表格重载期勾选不生效）→ DOM 级 click：`pyBell.evaluate` 内 `n.click()` + `waitForEvaluate` 以 `checked` 状态为准重试。
4. **盲短等待空跑链**（1.5-6s 等不到→后续整链静默空跑）→ 点击/断言前加 **30s 硬 `waitFor` 闸门**（抛错信息明确）。
5. **表单新标签页打开**（宫格按钮 window.open）→ `pyBell.pageSwitch("/product/")`；**注意 pageSwitch 用 `pages.find()` 取第一个匹配**：点按钮前先用 `pyBell.browser.pages()`（check-common.js 有先例）关闭同 URL 残留旧 tab；已有客户的新标签表单**无客户信息段**→ 整段条件跳过（探针失败吞掉，后续硬步骤兜底判 fail）。
6. **测试数据过期**（员工账号下线等，如 heling/和铃）→ 换有效数据（yanhao/颜浩；同名 span 用 `[last()]`）。客户名称类数据（如「和铃测试1498」）不是员工账号，别误改。
7. **产品级变更**（路由 404、模块迁移、入口下线）→ `describe.skip` + 注释说明，报告里请用户确认新入口，**不硬修**。
8. **环境抖动**（多页面卡空白/"加载中"、校验接口 404、`JSHandle@error` 散落、同批仍有用例通过=间歇）→ 硬闸门容错；若 30s 仍挂，报错会指明闸门，按环境问题上报，不改脚本。

## 4. 修复纪律

- **只修运行分支上实际失败的点**；同批通过的同模式写法不动（最小改动）。
- 三重复核：控制台序列 + 失败截图 + 代码；改前确认选择器引用范围（grep 全仓库，防悬空/误伤）。
- 校验：`node --check` 每个改动文件；新 XPath 用 lxml 在模拟 DOM 验证（嵌套/扁平/隐藏弹窗并存三形态）；require 加载 selector 模块（@qunhe/pybell 未安装时 require 失败属预期，以 node --check 为准）。
- 报告里标注**收敛观察点**（下轮可能再调的地方）。

## 5. 交付

- 从最新 master 切 `feature/yanhao-<YYYYMMDD>`；commit：`fix(<scope>): <描述>(build #N)`。
- push 与建 MR 均用 CI token。MR：`POST https://gitlab.qunhequnhe.com/api/v4/projects/test%2Fsite%2Fhades-kuboss-test/merge_requests`，header `PRIVATE-TOKEN: <CI token>`；标题结尾加 `(by 数字员工)`；`remove_source_branch: true`；描述三段模板：

```
# 简要描述:
- ...
# 影响范围:
- ...
# 测试回归的建议:
- ...
```

## 6. 复跑闭环

- 触发权在用户：Apollo 计划里把**分支参数填 feature 分支**即可跑未合并代码；或本地 `yarn start __tests__/order/<file>.js ...`。
- 跑完用户发 allure 链接 → 回 §1 继续收敛；全绿后用户在 GitLab 合并（author 是 qacenter，yanhao 可合并）。
- 若用户要求代触发 Jenkins：yanhao 无 Build 权限（403 + `X-Required-Permission: hudson.model.Item.Build`），直接说明并给出已备参数，不反复试探。
