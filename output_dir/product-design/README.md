# 暖愈智护 · 手机端前端

当前演示入口是 `home-proposal.html`。此目录使用原生 HTML、CSS、JavaScript 与哈希路由，不依赖 npm 构建；`apps/web` 是独立的真实 API 聊天应用。

## 本地预览

在项目根目录运行：

```sh
python -m http.server 5181 --bind 127.0.0.1 --directory output_dir/product-design
```

打开 `http://127.0.0.1:5181/home-proposal.html#/home`。

- `#/claim`：理赔申请、材料选择、核对与模拟提交。
- `#/welcome`：关怀服务介绍及资料用途说明。
- `#/home`：康复指引、看病总结和费用说明。
- `#/chat`：暖暖的示例解读、关键语句解释和聊天输入。
- `#/records`：个人档案、病情分组、时间排序和独立就医详情。

## 文件组织

入口按依赖顺序加载脚本，请保留加载顺序。

- `proposal.js`、`proposal-flow.js`：基础页面、导航与本地文件选择。
- `claim-entry.js`：理赔流程。
- `care-home.js`：首页和康复指引。
- `document-pages.js`、`visit-summary.js`、`expense-page.js`：资料、总结和费用。
- `report-chat.js`、`inline-report.js`：报告与最终聊天展示。
- `encounter-data.js`：多次就医的统一示例数据，先于其他脚本加载。
- `records-page.js`：病情分组、时间排序和就医详情。
- `encounter-context.js`：最后加载，让首页、聊天、费用、资料与康复页使用当前选中的就医记录，并隔离各次就医的临时输入。
- 同名 CSS 提供页面样式，`care-polish.css` 统一视觉，`care-usability.css` 调整字号、对比度、紧凑布局和触控区域。
- `assets/`：入口实际引用的 WebP 素材。
- `care-polish-image-prompts.json`：本轮新增插画的生成提示词。

## 校验与发布

在项目根目录运行：

```sh
node scripts/check_records_page.cjs
node scripts/check_encounter_context.cjs
python scripts/build_proposal_preview.py
```

检查脚本覆盖病情筛选、时间排序、跨页面病例资料隔离、临时输入恢复、导航和快捷解读，以及入口脚本语法和引用。它们不执行浏览器视觉检查。

构建脚本只打包入口、直接引用的脚本和样式、必需的 WebP 图片，并生成 `output_dir/mobile-demo/latest-build.json`。部署需要 Python 的 `paramiko`、已有 SSH 凭据，以及已配置静态站点目录的服务器：

```sh
python scripts/deploy_mobile_preview.py --host <server-host> --key <local-ssh-private-key>
python scripts/verify_proposal_release.py
```

部署脚本使用已验证的 SSH 主机密钥，上传后校验 SHA-256，再通过符号链接切换版本并保留上一版。校验脚本适用于现有演示服务器，逐文件比对公网内容并检查原站点和健康接口；更换服务器时需同步调整校验地址。

## 演示范围

当前页面为交互原型，病例与个人档案为虚构示例。材料仅在浏览器本地预览；模拟提交不创建真实理赔。AI 问答、通知和跨会话持久化尚未接通。不同就医保留独立资料与费用，理赔状态不表示康复状态。

在“就医记录”中打开某次就医后，首页、问暖暖、费用与资料会随之切换；首页的病例按钮可返回记录列表选择其他就医。对话、草稿、所选文件和提醒按就医分别暂存，浏览器返回时恢复对应记录。聊天中的“看病经过／费用解读／下一步安排”直接定位已有解读，不调用 AI；自由输入会明确提示服务尚未接通。

本目录无需真实医疗原件、访问令牌或私钥即可运行。
