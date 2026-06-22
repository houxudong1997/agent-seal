# nginx/ssl/

Place your TLS certificate files here (mounted read-only at `/etc/nginx/ssl` in the nginx container).

## Required files for HTTPS

| File         | Description                              |
|-------------|------------------------------------------|
| `cert.pem`  | Full certificate chain (server + intermediates) |
| `key.pem`   | Private key (RSA 2048+ or ECDSA P-256+)  |

> **⚠️ Keep `key.pem` secret** — never commit it to version control.
> Add to `.gitignore`: `nginx/ssl/*.pem`

## Generate self-signed cert for local development

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout nginx/ssl/key.pem \
  -out nginx/ssl/cert.pem \
  -subj "/CN=localhost"
```

## Production: Let's Encrypt via certbot

```bash
certbot certonly --webroot -w /var/www/certbot \
  -d your-domain.com \
  --cert-name agent-audit
# Then copy:
#   cp /etc/letsencrypt/live/agent-audit/fullchain.pem nginx/ssl/cert.pem
#   cp /etc/letsencrypt/live/agent-audit/privkey.pem   nginx/ssl/key.pem
```

## Enabling HTTPS in nginx

The default nginx configuration (`conf.d/default.conf`) only listens on HTTP (port 80).
To enable HTTPS, add a second `server` block to `default.conf`:

```nginx
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate     /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;

    # Modern TLS config
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;

    include /etc/nginx/conf.d/common.conf;
}
```

## HTTP-only mode (default)

If no cert files are placed here, the nginx container starts in HTTP-only mode (port 80).
TLS termination is entirely optional — the container works correctly without certs.
