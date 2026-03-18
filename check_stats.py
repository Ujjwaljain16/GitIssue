import asyncio
import os
from dotenv import load_dotenv
import asyncpg

load_dotenv()

async def main():
    conn = await asyncpg.connect(os.getenv('DATABASE_URL'))
    try:
        i = await conn.fetchval('SELECT COUNT(*) FROM issues')
        s = await conn.fetchval('SELECT COUNT(*) FROM duplicate_suggestions')
        l = await conn.fetchval('SELECT COUNT(*) FROM suggestion_labels')
        print(f'✅ Issues: {i}, Suggestions: {s}, Labels: {l}')
    finally:
        await conn.close()

asyncio.run(main())
