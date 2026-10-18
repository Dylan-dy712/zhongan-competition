# Domain HTTPS deployment

Verified on 2026-10-16 (Asia/Shanghai):

- Public URL: https://zhongan.xinzhipingtai.cn
- DNS A record: `49.235.108.92`.
- Certificate: Let's Encrypt, covering `zhongan.xinzhipingtai.cn`.
- Certificate expiry at setup: 2027-01-14 03:19:27 Asia/Shanghai.
- HTTPS homepage, JavaScript, stylesheet and `/health` all passed public checks.
- Domain HTTP requests return 308 to HTTPS, preserving the path and query.
- Original `http://49.235.108.92/health` remains available.
- A Certbot simulated renewal including the Nginx deploy hook passed.

The application server includes `/etc/nginx/zhongan-https-listener*.conf`.
This optional include is also present in `deploy/nginx-zhongan-api.conf` so
subsequent deployments using this source keep the host's TLS listener.
All existing application locations, limits and proxy timeouts are shared by
HTTP and HTTPS. A separate `/etc/nginx/conf.d/zhongan-domain-http.conf` handles
the domain's HTTP redirect and serves HTTP-01 validation files directly.

Certificates and private keys remain managed by Certbot under
`/etc/letsencrypt/`; they must not be copied into the repository.
`certbot.timer` is enabled and runs the packaged renewal service. The executable
hook `/etc/letsencrypt/renewal-hooks/deploy/zhongan-nginx-reload` checks Nginx
configuration and reloads it after successful renewal.

The staged setup files are in `/home/ubuntu/zhongan-https-20261016`.
The setup script `deploy/configure_domain_https_ubuntu.sh` takes `enable` or
`redirect`; redirect is enabled only after public HTTPS has been verified.
It shares the application's deployment lock and backs up Nginx configuration
under `/var/backups/zhongan-https.*`. The backup immediately before enabling
TLS is `/var/backups/zhongan-https.TkZiyvcz`; the backup immediately before the
HTTP redirect is `/var/backups/zhongan-https.FHCAffad`.

To exercise renewal without Certbot's randomized scheduler delay:

```bash
sudo certbot renew --cert-name zhongan.xinzhipingtai.cn \
  --dry-run --run-deploy-hooks --non-interactive --no-random-sleep-on-renew
```

Public verification results are saved in
`output_dir/domain-https-20261016/verification.json`.

## Release overwrite regression (2026-10-16)

A later application release installed an Nginx site without the optional TLS
include. The domain still returned an HTTP 308 redirect, but Nginx no longer
listened on port 443. DNS, the certificate and the application remained healthy.
Restoring the include and reloading Nginx restored public HTTPS immediately.

The committed application site now loads the host-managed TLS include. When that
listener file exists, deployment also validates the exact release markers and
API routes over certificate-verified public HTTPS and checks `/judge/` before
reporting success. An HTTPS failure follows the existing deployment rollback.
The Linux deployment harness covers that failure and verifies frontend rollback
without restarting the running API.
