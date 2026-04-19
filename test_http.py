import urllib.request
import urllib.parse
from linklocal.config import load_config

token = load_config()["superuser_token"]
data = urllib.parse.urlencode({"token": token}).encode("utf-8")

# Login
req = urllib.request.Request("http://127.0.0.1:5050/", data=data)
try:
    with urllib.request.urlopen(req) as res:
        print("Login status:", res.getcode())
        cookie = res.info().get("Set-Cookie")
except Exception as e:
    print("Login error:", e)

# Dashboard
req2 = urllib.request.Request("http://127.0.0.1:5050/dashboard")
if cookie:
    req2.add_header("Cookie", cookie)
try:
    with urllib.request.urlopen(req2) as res2:
        print("Dashboard status:", res2.getcode())
except urllib.error.HTTPError as e:
    print("Dashboard error status:", e.code)
    print(e.read()[:2000].decode("utf-8", errors="ignore"))
except Exception as e:
    print("Dashboard error general:", e)
