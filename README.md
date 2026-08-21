# ci-interface-test-recovery

**CI 接口测试失败自动修复与补例** —— 群核数字员工 skill 包。

## 用途

当接口测试 CI 失败（moon CI / Jenkins aegis-ci / Apollo 测试计划报告），或接口测试覆盖率低于目标需要补例提升覆盖率时，按本 skill 的端到端流程自动处理：

- 定位 CI 报告对应的 Aegis 任务
- 判断失败类别：A 构建/依赖问题 / B 用例问题 / C 服务异常
- 修复接口用例（断言过脆、数据堆积、数据过期、任务锁冲突）
- 补充接口定义与用例提升覆盖率
- 服务异常时点名具体服务 + traceId 汇报

## 结构

```
ci-interface-test-recovery/
├── SKILL.md                        # skill 入口：触发场景 + 流程 + 判断框架
└── references/
    ├── ci-task-lookup.md           # CI 报告 → Aegis 任务反查（表字段 + SQL 模板）
    ├── coverage-gap-analysis.md    # 覆盖率缺口定位 + 补接口/用例 SOP
    └── case-fix-patterns.md        # 6 类已证实失败模式库（判定证据 + 修复动作 + 案例）
```

## 依赖

本 skill 为纯文档型，无独立 scripts / MCP 工具。运行时复用数字员工已挂载的 qautomation 能力：

- `test_plan_analysis`（Apollo 报告定位、失败分析、绑定用例）
- `api_case_generation`（建接口定义、生成/更新/执行用例）
- `coverage-analysis`（taskId → JaCoCo 覆盖率缺口）
- `automation-query`（CI 任务反查、覆盖率趋势）

## 上载到数字员工技能平台

1. 打开 https://aiman.qunhequnhe.com/skills → 创建 skill
2. 名称：`ci-interface-test-recovery`；描述：CI 接口测试失败自动修复与补例
3. 导入本仓库 `ci-interface-test-recovery/` 目录（SKILL.md + references/）
4. 补充 tags（如 `ci` / `api` / `coverage` / `test_plan_analysis`）后发布分享
