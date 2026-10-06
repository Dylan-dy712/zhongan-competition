# 当前理赔与关怀演示：运行、部署与回滚

2026-10-06 统一入口变更：本文件下方保留旧静态演示的历史部署记录。当前账号与资料整理入口已迁入 `apps/web`；新的 Nginx 配置将 `/mobile-demo/` 转向 `/#/claim`，需部署后生效。原型仅作设计参考。运行和验证见根目录 README 与 `docs/requirements/accounts-and-unified-entry.md`。

2026-10-02 更新。当前维护的前端是 `output_dir/product-design/home-proposal.html`。旧 React 手机 Demo 和重复理赔入口已归档后清理。

## 入口

- 公网理赔入口：<http://49.235.108.92/mobile-demo/>
- 公网关怀欢迎页：<http://49.235.108.92/mobile-demo/#/welcome>
- 本地原型：<http://127.0.0.1:5181/home-proposal.html#/claim>
- 原真实 API 聊天应用：`apps/web`，服务器根路径仍可访问。

公网默认进入“填写申请 → 上传材料 → 核对提交”；模拟提交成功后可以“完成”或“查看专属关怀”，进入欢迎页及独立资料授权流程。

## 再次部署

在项目根目录执行：

```powershell
python scripts/build_proposal_preview.py
python scripts/deploy_mobile_preview.py --host 49.235.108.92 --key .secrets/tencent_cvm_49_235_108_92
python scripts/verify_proposal_release.py
```

构建脚本只打包当前 HTML、直接引用的 JS/CSS 和所需 WebP，不上传测试脚本、截图、源码备份或凭据。每个版本使用独立目录及带版本号的静态引用。SSH 使用已有可信主机记录，不自动接受未知主机密钥。

`/var/www/zhongan-web/mobile-demo` 是指向 `.mobile-demo-releases` 当前版本的符号链接，部署通过原子切换链接发布。此次未修改 Nginx、数据库或 API 服务。

## 检查记录

- `output_dir/mobile-demo/deployment.json`：当前版本、上一版、全部文件 SHA-256。
- `output_dir/mobile-demo/public-release-checks.json`：26 个公网文件逐项比对通过，默认入口为 `/claim`；原站点及 `/health` 均返回 200。
- `output_dir/mobile-demo/server-cleanup.json`：服务器清理目录清单、保留版本与归档位置。
- `output_dir/mobile-demo/local-cleanup.json`：本地清理清单和 ZIP 备份位置。

## 清理和恢复

服务器保留当前版与上一版回滚目录；9 个更早的静态发布版本和对应暂存目录先归档，再从原目录移除。服务器归档位于 `/home/ubuntu/zhongan-archives/`，不作为网站文件发布。

本地清理了 `apps/web/src/demo`、`src/claim`、旧 `demo.ts`、旧 Demo 检查脚本、`dist-mobile-demo` 以及 4 个历史原型构建。完整备份位于 `output_dir/archive/legacy-demo-20261001T211058Z.zip`；新版源码和原始设计素材保留。

回滚时使用 `deployment.json` 的 `previous` 相对路径创建临时链接，核对目标仍位于 `.mobile-demo-releases` 后原子替换 `mobile-demo`。本地旧源码可以从 ZIP 按需恢复，勿直接覆盖新版工作区。

## 当前能力范围

这是前端流程原型，申请资料仅在页面内存中保留，文件不上传服务器、不创建真实理赔、不发送通知。关怀内容是预置病例展示，问答服务尚未连接。真实 API 聊天应用的运行说明仍见根目录 README。
