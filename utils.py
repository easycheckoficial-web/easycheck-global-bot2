import os, re, unicodedata, datetime

def is_debug() -> bool:
    v = os.getenv("DEBUG_HTML","")
    return bool(str(v).strip())

def slugify(*parts) -> str:
    s = " ".join([p for p in parts if p]).strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+","-", s).strip("-")
    return s[:90]

def now_iso() -> str:
    return datetime.datetime.utcnow().isoformat()+"Z"
