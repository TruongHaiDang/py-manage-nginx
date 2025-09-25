# py-manage-nginx

[![PyPI - Version](https://img.shields.io/pypi/v/py-manage-nginx.svg)](https://pypi.org/project/py-manage-nginx)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/py-manage-nginx.svg)](https://pypi.org/project/py-manage-nginx)

-----

## Table of Contents

- [Installation](#installation)
- [License](#license)

## Installation

```bash
pip install py-manage-nginx
```

## License

`py-manage-nginx` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.

## Run test

```bash
sudo $(which pytest) -s -v test.py::<function name>
```

### Example

```bash
sudo $(which pytest) -s -v test.py::test_create_hosting
```

```bash
sudo $(which pytest) -s -v test.py::test_remove_hosting
```

## Self-Signed SSL

```bash
sudo mkdir -p /etc/nginx/ssl/test.local
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/test.local/privkey.pem \
  -out /etc/nginx/ssl/test.local/fullchain.pem \
  -subj "/CN=test.local"
```

```nginx
server {
    listen 443 ssl;
    server_name test.local;

    ssl_certificate /etc/nginx/ssl/test.local/fullchain.pem;
    ssl_certificate_key /etc/nginx/ssl/test.local/privkey.pem;

    root /var/www/test.local;
}
```
