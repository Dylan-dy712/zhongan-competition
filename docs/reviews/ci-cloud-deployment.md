# CI通过后同步云端

`.github/workflows/ci.yml`对main的PR及push运行两个检查：backend使用Python3.12和原生PostgreSQL16，执行单测、审核、聊天/Worker、发布/反馈/竞争检查与shell语法检查；web使用Node24执行锁定依赖安装、TypeScript/Vite构建，并保存带CI_REVISION的web-dist产物。检查只使用合成数据库和明确模型替身，不注入医疗材料或生产凭据。官方Actions固定到已核实的提交SHA。

本线程按用户授权，在PR CI成功后合并，再等待合并后的main push CI成功，使用本机SSH认证同步云服务器。SSH私钥不上传GitHub，不保存在Actions secrets。这里不是已配置了无人值守的Actions SSH部署；同步由本机执行现有部署入口，私钥仍只在本机使用。

```powershell
git fetch origin main
git switch --detach origin/main
python -m scripts.deploy_remote --host <host> --key <本机私钥路径>
```

deploy_remote拒绝脏工作树、非当前远端main、没有对应ci.yml成功push运行的提交。PR通过不能代替合并后确切SHA的通过记录。网页从该CI运行下载，index.html及CI_REVISION必须匹配；不打包可能陈旧的本地dist。源码仅打包当前提交中允许的目录，REVISION记录准确提交。

远端沿用deploy_update_ubuntu：flock拒绝重叠部署，先备份应用/网页/配置，停API与Worker后备份数据库，再执行事务迁移、依赖一致性和Nginx检查，启动服务并核验health。失败恢复应用和配置，数据库备份保留供人工处理，不自动覆盖业务数据库。数据库和模型密钥仍只从远端既有受限配置读取；不打印或回传密钥。

部署后必须读回远端REVISION、API/Worker/Nginx状态、公开health与网页资源。CI成功只代表覆盖的合成程序路径通过，不代表官方KR、医学盲评或所有上线回滚条件已验收。

## 移动端原型预览

2026-10-06 统一入口更新：新的 Nginx 配置将 `/mobile-demo` 与 `/mobile-demo/` 重定向到 `/#/claim`。部署后的主网页版本检查使用 `/CI_REVISION`；历史原型产物检查改用 `/.mobile-demo-releases/<sha>/CI_REVISION`，避免旧路径重定向导致部署误失败。另校验重定向目标及账号接口的 OpenAPI 路由。下段保留原型打包机制说明，静态产物仍可作为设计参考保存。

`output_dir/product-design` 是独立的虚构交互原型，集成后 CI 增加病例隔离检查和 `mobile-dist` 构建产物。它与主聊天应用共同接受同一 main 提交 CI 门禁，部署到 `/mobile-demo/`；默认显示首页。产物包含提交 SHA 与文件哈希，资源地址为 `/.mobile-demo-releases/<sha>/`，旧浏览器继续使用旧资源。发布切换 symlink 并保留旧版，失败恢复前一入口；不会把原型静态内容当作真实医疗报告。`output_dir/医疗费用` 知识草稿不在部署白名单中，未注册成已审核知识。
