# 评委扫码体验入口

比赛入口是独立的 `zhongan-judge-demo` 服务，经主站 `/judge/` 反向代理。它复用现有账号、授权和可撤销的 12 小时会话，50 个账号、人员档案和会话权限分别隔离。

首次扫码时，浏览器生成并保存随机访问标识，服务端只保存其 SHA-256。短数据库事务加锁分配空闲账号；同一浏览器重复扫码、重试或退出后再进入仍分配原账号。第 51 个新浏览器收到明确的满额提示。更换设备、浏览器或清除站点数据会被视为新访客，因此这里保证的是浏览器隔离，不是真实身份识别。

测试账号使用随机密码，不公开密码，也不复用既有用户身份。体验邀请码保存在服务器受限文件 `/home/ubuntu/.config/zhongan/judge-demo.env` 中；分享链接通过 URL fragment 携带邀请码，页面读取后移除。浏览器从服务端领取独立登录会话，再进入现有首页。首次资料已完善，并为虚构体验材料建立单次关怀授权。不得为体验账号导入真实用户材料。

入口安装使用 `python -m scripts.deploy_judge_demo --host <host> --key <本机SSH私钥> --install`。先在随机临时 PostgreSQL schema 中验证 50 人并发、重复进入、满额、跨账号读取拒绝、退出和过期，再创建实际账号、启用独立服务并重载 Nginx。安装失败恢复已有路由、服务定义和入口版本。主站 Nginx 配置通过可选 include 保留体验服务路由；主站正式发布仍沿用原有 CI 和确切 main 提交门禁。

`python -m scripts.create_judge_demo_qr --host <host> --key <本机SSH私钥>` 读取服务器邀请码，验证公网路由后生成链接、PNG/SVG 二维码和可打印海报。分享链接和二维码即是体验访问能力，不能提交到代码仓库。生成文件在 `output_dir/judge-demo/`。

前端验证：`node apps/web/scripts/check-judge-entry.mjs`。后端验证：`python -m unittest discover -s tests -p test_judge_demo.py -v`；配置 `ZHONGAN_AUTH_TEST_DATABASE_URL` 才执行临时数据库并发与隔离检查。生产分配绑定不自动清空，不会将已经使用的账号发给新访客。

比赛结束后可先停用新分配：`sudo systemctl disable --now zhongan-judge-demo`。若还需撤销已发会话，应由维护人员只对 `judge_demo_slots` 关联的账号撤销 `auth_sessions` 并停用对应 `actors`，不得清空全站会话。保留数据前明确后续用途，清理仅针对本活动合成数据。
