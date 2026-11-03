import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

origin = sys.argv[1].rstrip("/")
url = urlsplit(origin)
assert url.scheme == "https" and url.hostname and re.fullmatch(r"[a-z0-9-]+\.trycloudflare\.com", url.hostname)
assert not url.username and not url.password and not url.port and not url.path and not url.query and not url.fragment
target = Path("/etc/returntech/backend.env")
lines = target.read_text(encoding="utf-8").splitlines()
changed = set()
for index, line in enumerate(lines):
    key = line.partition("=")[0]
    if key in {"FRONTEND_URL", "MAIL_APP_URL"}:
        lines[index] = f'{key}="{origin}"'
        changed.add(key)
for key in {"FRONTEND_URL", "MAIL_APP_URL"} - changed:
    lines.append(f'{key}="{origin}"')
fd, name = tempfile.mkstemp(prefix=".backend-env-", dir=target.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
        output.write("\n".join(lines) + "\n")
    os.chmod(name, 0o600)
    os.replace(name, target)
finally:
    if os.path.exists(name):
        os.unlink(name)
public_directory = Path("/var/lib/returntech")
public_directory.mkdir(mode=0o755, exist_ok=True)
public_url_file = public_directory / "public-url.txt"
public_url_file.write_text(origin + "\n", encoding="utf-8")
public_url_file.chmod(0o644)
print("Origem pública atualizada; credenciais existentes preservadas.")
