# app/scf_config.py
import os, json
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(__file__))

def _helius_urls():
    key = os.getenv("HELIUS_KEY") or ""
    if not key:
        return {"ws": "", "http": ""}
    base = "mainnet.helius-rpc.com"
    return {
        "ws":   f"wss://{base}/?api-key={key}",
        "http": f"https://{base}/?api-key={key}",
    }

def load_env():
    load_dotenv(os.path.join(ROOT, ".env"))
    # Prefer explicit RPC_*; otherwise fall back to HELIUS_KEY-derived URLs
    helius = _helius_urls()
    cfg = {
        "rpc_ws":        os.getenv("RPC_PRIMARY")      or helius["ws"],
        "rpc_http":      os.getenv("RPC_HTTP_PRIMARY") or helius["http"],
        "rpc_ws_backup": os.getenv("RPC_BACKUP")       or "",
        "db_url":        os.getenv("DB_URL")           or "postgresql://scf:scf@localhost:5432/scf",
        "raydium_amm":   os.getenv("RAYDIUM_AMM")      or "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
        "raydium_clmm":  os.getenv("RAYDIUM_CLMM")     or "4hGdEStwqyqZkG2tZibsSDQ7SBy7xH2sVQ2QJVV5o4Ck",
        "orca_amm":      os.getenv("ORCA_AMM")         or "9WwG7VJp49r4bgx1mVQqzKkGKuX3sX5Y3F9F6w8vG8bS",
    }
    return cfg

def load_thresholds():
    path = os.path.join(ROOT, "thresholds.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
