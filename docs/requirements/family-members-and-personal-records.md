# 家庭成员与个人就医记录

首页组件及其现有内容保持不变，不新增家庭聚合服务。“我的”切换只改变档案、授权和记录展示；不修改首页的当前关怀、已打开的对话或材料草稿。

## 数据与迁移

- 部署 API 前运行项目现有迁移命令 `python -m scripts.migrate_database`，包含新增 `021_family_members.sql`。
- `account_members` 保存账号与人员关系及基础资料，沿用现有 `subject_id`。迁移回填注册账号的本人档案，默认待补全，不改变历史案件和授权。
- 注册后首次读取成员列表也会补建本人档案。本人资料完成后才能添加家人。姓名必填；性别和出生日期可不填写。
- 家人创建时只建立账号访问关系，不自动授权。本人和家人的授权版本、撤回状态分别管理。
- 无删除、解绑或实名核验功能。无法明确归属的历史资料不按姓名迁移。

## 接口

| 接口 | 行为 |
| --- | --- |
| `GET /v1/me/members` | 列出账号自己的成员，包括未授权成员 |
| `POST /v1/me/members` | 添加家人，服务端生成人员标识 |
| `PATCH /v1/me/members/{subject_id}` | 编辑资料，不能把本人变为家人或反向修改 |
| `GET/POST /v1/me/consents?subject_id=...` | 查询或修改指定成员授权；省略参数兼容本人授权 |
| `GET /v1/conversations?subject_id=...` | 校验账号访问权限，返回该人员全部可访问记录 |

成员输入为 `name`、`relationship`（`self/parent/spouse/child/other`）、`gender`（`male/female/unspecified`）、`birth_date`（日期或 null）。响应增加 `subject_id` 和 `profile_completed`。出生日期不能晚于当天。成员接口不接受客户端指定身份、角色或完成状态。

对话列表、创建和详情均返回 `subject_id`。未筛选的列表保持既有最近 100 条行为，个人记录列表不受该上限影响。跨账号成员访问、对话访问和筛选均由服务端拒绝。

## 页面行为

- 底部导航为首页、问暖暖、我的；记录二级页高亮“我的”。最近记录以案件分组，按最近更新时间取第一组，不把更新时间显示成就诊日期。
- 当前查看人员按本人稳定标识区分账号保存。重新登录会校验选择是否有效，退出时清除当前账号选择及会话内容。
- 新对话独立选择人员。首页整理材料时独立选人；“我的”的空记录入口携带当前人员。
- 材料表单人员与新对话人员分别保存。返回首页和切换查看人员保留材料草稿；改为其他就医人员时，已有草稿需要确认舍弃。提交及上传期间不能开始另一项业务。
- 切换人员或退出后，过时的记录与授权请求不会覆盖新页面。撤回某人授权只清除该人不可再访问的业务内容。

## 验证

- 前端：`npm run build`、`npm run test:navigation`、`npm run test:auth`、`npm run test:availability`（在 `apps/web` 下执行）。
- 权限及迁移：设置指向隔离测试数据库的 `ZHONGAN_AUTH_TEST_DATABASE_URL`，执行 `python -m unittest tests.test_family_members tests.test_accounts`。测试在临时 schema 内使用合成数据，结束后删除该 schema。
- Chromium：`node scripts/check_family_pages.cjs` 使用项目本机既有 Playwright 运行时及纯合成 HTTP 响应，检查 320、390、1024 像素布局、键盘弹窗、过时请求、草稿保留、独立业务归属、添加编辑和退出。截图及结果保存在 `output_dir/family-members`。

本次本机验证：构建、三个前端检查、6 项数据库及账号测试、21 项对话单元及成员契约测试、Chromium 交互和布局检查通过。额外的 `scripts.check_conversation_integration` 在预期拒绝不可变快照修改后的查询处收到 `psycopg.InternalError: got no result from the query`，未完成整套检查；本次使用的是 PGlite Socket 临时数据库，仍需在原生 PostgreSQL 环境复核该完整集成检查。没有部署或修改线上数据库。

2026-10-09 发布前复核：服务器 PostgreSQL 16.15 随机隔离 schema 中，6 项成员与账号测试、98 项完整对话/Worker 集成检查全部通过，无跳过。此前本地 PGlite 的异常恢复限制已由原生数据库验证补齐，临时测试 schema 和测试目录已清理。独立发布分支的构建、导航、授权和可用性检查全部通过。
