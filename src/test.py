# src/test_asyncpg_probe.py
import os, asyncio, asyncpg, ssl
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

host = os.getenv("PUBLIC_PGHOST") or os.getenv("PGHOST") or "localhost"
port = int(os.getenv("PGPORT") or "5432")
user = (os.getenv("PGUSER") or "").strip()
pwd  = (os.getenv("PGPASSWORD") or "").strip()
db   = (os.getenv("PGDATABASE") or "postgres").strip()

print("Using:", {"host": host, "port": port, "user": user, "db": db})

# ⚠️ Disable verification (OK for dev; prefer a CA file for prod)
ssl_ctx = ssl.create_default_context()
ssl_ctx.check_hostname = False
ssl_ctx.verify_mode = ssl.CERT_NONE

async def main():
    conn = await asyncpg.connect(
        host=host, port=port, user=user, password=pwd, database=db,
        ssl=ssl_ctx, timeout=10
    )
    ver = await conn.fetchval("select version()")
    print("Connected OK:", ver)
    await conn.close()

asyncio.run(main())
