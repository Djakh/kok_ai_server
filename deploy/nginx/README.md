# Nginx upload-limit deployment

The API accepts up to 40,000,000 bytes of image content in one tree-analysis request, plus up to
2,000,000 bytes of multipart framing. Nginx must have a larger ceiling so accepted requests reach
FastAPI and application-level failures use the normal JSON error envelope.

On the API host, copy `kokai-upload-limits.conf` to the Nginx snippets directory:

```bash
sudo install -m 0644 deploy/nginx/kokai-upload-limits.conf \
  /etc/nginx/snippets/kokai-upload-limits.conf
```

Include it inside the existing `server {}` block for `api.kokai.uz`:

```nginx
server {
    server_name api.kokai.uz;

    include /etc/nginx/snippets/kokai-upload-limits.conf;

    # Existing TLS and proxy locations remain here.
}
```

Validate and reload without dropping active connections:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Confirm the active configuration rather than only the edited source file:

```bash
sudo nginx -T | grep -n -E 'server_name api.kokai.uz|client_max_body_size'
```

The expected active value is `client_max_body_size 48m`. If another enclosing or location-specific
directive overrides it, update that directive as well. An Nginx HTML 413 means this configuration
has not been loaded by the server handling the request.
