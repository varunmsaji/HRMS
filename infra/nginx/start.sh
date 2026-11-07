#!/bin/sh
# Entry point of docker-compose.prod.yml's `nginx` service.
#
# 1. Renders hrms-http.conf.template (port 80: ACME challenge + redirect) always, and
#    hrms.conf.template (the HTTPS servers) only once the Let's Encrypt certificate exists. Nginx
#    will not start with an `ssl_certificate` it cannot read, so on a first deployment, before
#    the certificate is issued, it serves port 80 alone and the HTTP-01 challenge can complete.
# 2. Watches the certificate. When it appears or changes (first issuance, or a renewal by the
#    `certbot` service), re-renders and reloads Nginx gracefully, so new connections get the new
#    certificate without anyone restarting the container. A config that fails `nginx -t` is not
#    loaded; the running one stays and the next check tries again.
set -eu

templates=/etc/nginx/templates
live="/etc/letsencrypt/live/${WEB_DOMAIN}"
vars='$API_DOMAIN $WEB_DOMAIN $STORAGE_DOMAIN'
interval="${CERT_CHECK_INTERVAL_SECONDS:-300}"

have_cert() { [ -s "$live/fullchain.pem" ] && [ -s "$live/privkey.pem" ]; }

cert_fingerprint() { cat "$live/fullchain.pem" "$live/privkey.pem" 2>/dev/null | sha256sum | cut -d' ' -f1; }

render() {
    envsubst "$vars" < "$templates/hrms-http.conf.template" > /etc/nginx/conf.d/hrms-http.conf
    if have_cert; then
        envsubst "$vars" < "$templates/hrms.conf.template" > /etc/nginx/conf.d/hrms.conf
    else
        rm -f /etc/nginx/conf.d/hrms.conf
        echo "nginx start: no certificate at $live yet. Serving HTTP only (ACME challenge and redirect); HTTPS turns on by itself once the certificate is issued." >&2
    fi
}

watch_cert() {
    last=$(cert_fingerprint)
    while :; do
        sleep "$interval"
        current=$(cert_fingerprint)
        [ "$current" = "$last" ] && continue
        render
        if nginx -t -q; then
            nginx -s reload
            last=$current
            echo "nginx start: certificate changed, configuration reloaded." >&2
        else
            echo "nginx start: the new configuration failed nginx -t; keeping the running one." >&2
        fi
    done
}

render
watch_cert &
exec nginx -g 'daemon off;'
