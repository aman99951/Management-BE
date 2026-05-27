import os, sys
import sqlite3
import psycopg2

base = r'C:\Users\aman9\Downloads\MG-Techno-Pro\Management-tool\backend'
pg_url = 'postgresql://neondb_owner:npg_kO1bPACFMEL2@ep-divine-water-apoz3ytr-pooler.c-7.us-east-1.aws.neon.tech/neondb?sslmode=require'

sqlite = sqlite3.connect(os.path.join(base, 'db.sqlite3'))
sqlite.row_factory = sqlite3.Row
rows = sqlite.execute('SELECT * FROM api_employee').fetchall()
sqlite.close()

print(f'Read {len(rows)} employees from SQLite')

pg = psycopg2.connect(pg_url)
cur = pg.cursor()
cur.execute('SELECT email FROM api_employee')
existing = {r[0] for r in cur.fetchall()}
print(f'Existing in PG: {existing}')

inserted = 0
for r in rows:
    if r['email'] not in existing:
        cur.execute(
            'INSERT INTO api_employee (name, email, team, created_at) VALUES (%s, %s, %s, %s)',
            (r['name'], r['email'], r['team'], r['created_at'])
        )
        inserted += 1
        print(f'Inserted: {r["email"]}')
    else:
        print(f'Skipped: {r["email"]}')

pg.commit()
cur.close()
pg.close()
print(f'\nDone. Inserted {inserted} employees.')
