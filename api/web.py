from http.server import BaseHTTPRequestHandler

PAGE = "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1,viewport-fit=cover\"><title>KAP — Web Login</title>\n<script src=\"https://telegram.org/js/telegram-web-app.js\"></script>\n<style>*{box-sizing:border-box}body{margin:0;min-height:100vh;background:linear-gradient(145deg,#080d19,#111b31);color:#fff;font-family:system-ui,-apple-system,sans-serif;display:grid;place-items:center;padding:20px}.card{width:min(430px,100%);padding:30px 24px;border:1px solid #263552;border-radius:24px;background:#10192b;box-shadow:0 20px 60px #0007;text-align:center}.logo{width:74px;height:74px;margin:auto;border-radius:20px;display:grid;place-items:center;background:#5875ff;font-size:30px;font-weight:900}h1{margin:18px 0 8px;font-size:28px}.sub{color:#aab7d0;line-height:1.5}.status{margin-top:22px;padding:14px;border-radius:14px;background:#0a1222;color:#c9d4e9;line-height:1.45}.small{margin-top:14px;color:#7786a3;font-size:12px}</style></head>\n<body><main class=\"card\"><div class=\"logo\">K</div><h1>KAP Web Login</h1><p class=\"sub\">Secure login using your Telegram account.</p><div id=\"status\" class=\"status\">Checking Telegram Mini App…</div><p class=\"small\">No Telegram or third-party OTP is requested on this page.</p></main>\n<script>\nconst tg=window.Telegram?.WebApp,status=document.getElementById(\"status\");\nif(tg){tg.ready();tg.expand();if(tg.initData){fetch(\"/api/miniapp\",{method:\"POST\",headers:{\"content-type\":\"application/json\"},body:JSON.stringify({initData:tg.initData})}).then(r=>r.json()).then(x=>{if(x.ok&&x.user)status.innerHTML=\"✅ Logged in as <b>\"+(x.user.first_name||\"Telegram user\")+\"</b>\";else status.textContent=x.error||\"Telegram authentication failed.\"}).catch(()=>status.textContent=\"Connection error. Please try again.\");}else status.textContent=\"Open this page from the KAP Telegram bot to sign in.\"}else status.textContent=\"Open this page from the KAP Telegram bot to sign in.\";\n</script></body></html>"

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        raw = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def do_POST(self):
        self.do_GET()
