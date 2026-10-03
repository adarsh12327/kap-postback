import hashlib,hmac,json,os,time,base64
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qsl
MAX_AGE=7*24*60*60
def validate(v):
    token=os.getenv("BOT_TOKEN","")
    if not v or not token: raise ValueError("Telegram authentication is not configured")
    d=dict(parse_qsl(v,keep_blank_values=True)); received=d.pop("hash",None)
    if not received: raise ValueError("Missing Telegram signature")
    stamp=int(d.get("auth_date","0"))
    if not stamp or abs(time.time()-stamp)>3600: raise ValueError("Telegram authentication expired")
    check="\n".join(f"{k}={x}" for k,x in sorted(d.items()))
    key=hmac.new(b"WebAppData",token.encode(),hashlib.sha256).digest()
    expected=hmac.new(key,check.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,received): raise ValueError("Invalid Telegram signature")
    user=json.loads(d.get("user","{}"))
    if not user.get("id"): raise ValueError("Telegram user missing")
    return user
def enc(o): return base64.urlsafe_b64encode(json.dumps(o,separators=(",",":")).encode()).decode().rstrip("=")
def dec(v): return json.loads(base64.urlsafe_b64decode(v+"="*(-len(v)%4)).decode())
def make_session(u):
    safe={k:u.get(k,"") for k in ("id","first_name","last_name","username","language_code","photo_url")}
    body=enc({"u":safe,"exp":int(time.time())+MAX_AGE})
    sig=hmac.new((os.getenv("SESSION_SECRET") or os.getenv("BOT_TOKEN","")).encode(),body.encode(),hashlib.sha256).hexdigest()
    return body+"."+sig
def current(h):
    try:
        c=SimpleCookie();c.load(h or "");m=c.get("kap_session")
        if not m:return None
        body,sig=m.value.rsplit(".",1);sec=(os.getenv("SESSION_SECRET") or os.getenv("BOT_TOKEN","")).encode()
        if not hmac.compare_digest(hmac.new(sec,body.encode(),hashlib.sha256).hexdigest(),sig):return None
        x=dec(body);return x["u"] if int(x["exp"])>=int(time.time()) else None
    except Exception:return None
class handler(BaseHTTPRequestHandler):
    def sendj(self,status,data,cookie=None):
        raw=json.dumps(data).encode();self.send_response(status);self.send_header("Content-Type","application/json");self.send_header("Cache-Control","no-store")
        if cookie:self.send_header("Set-Cookie",cookie)
        self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        u=current(self.headers.get("Cookie"));self.sendj(200,{"ok":True,"authenticated":bool(u),"user":u})
    def do_POST(self):
        try:
            n=int(self.headers.get("Content-Length","0"));p=json.loads(self.rfile.read(n).decode());u=validate(p.get("initData",""));t=make_session(u)
            cookie=f"kap_session={t}; Path=/; Max-Age={MAX_AGE}; HttpOnly; Secure; SameSite=Lax"
            safe={k:u.get(k,"") for k in ("id","first_name","last_name","username","language_code","photo_url")}
            self.sendj(200,{"ok":True,"authenticated":True,"user":safe},cookie)
        except Exception as e:self.sendj(401,{"ok":False,"error":str(e)[:160]})
    def do_DELETE(self):
        self.sendj(200,{"ok":True},"kap_session=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax")
