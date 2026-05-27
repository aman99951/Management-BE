import sqlite3
conn = sqlite3.connect(r'C:\Users\aman9\Downloads\MG-Techno-Pro\Management-tool\backend\db.sqlite3')
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT * FROM api_fathomconfig').fetchall()
conn.close()
if rows:
    for r in rows:
        print(dict(r))
else:
    print('No FathomConfig rows found')
