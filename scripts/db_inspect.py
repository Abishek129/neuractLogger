import sqlite3, os, sys

p = sys.argv[1] if len(sys.argv) > 1 else 'mydatabase.db'
print('db:', p, 'exists:', os.path.exists(p), 'size:', os.path.getsize(p) if os.path.exists(p) else 0)
if not os.path.exists(p):
    sys.exit(0)
con = sqlite3.connect(p)
cur = con.cursor()
rows = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print('tables:', [r[0] for r in rows])
if os.path.basename(p) == 'app.db':
    try:
        rs = cur.execute("SELECT id,name,schema_id,db_target_id,status,last_migrated_at,mapping_health,device_id FROM app_device_tables").fetchall()
        print('app_device_tables rows:', len(rs))
        for r in rs:
            print(r)
    except Exception as e:
        print('app_device_tables err', e)
    try:
        sch = cur.execute("SELECT id,name FROM app_schemas").fetchall()
        print('schemas:', sch)
        for sid, name in sch:
            f = cur.execute("SELECT key,type,unit,scale,desc FROM app_schema_fields WHERE schema_id=?", (sid,)).fetchall()
            print('schema', sid, name, 'fields:', f)
    except Exception as e:
        print('schemas err', e)
    try:
        tgs = cur.execute("SELECT id,provider,conn,status FROM app_db_targets").fetchall()
        print('targets:', tgs)
        row = cur.execute("SELECT value FROM app_meta WHERE key='default_db_target'").fetchone()
        print('default_target:', row)
    except Exception as e:
        print('targets err', e)
for t in ['neuract__device_mappings','neuract_device_mappings','device_mappings']:
    try:
        cnt = cur.execute(f"SELECT COUNT(1) FROM {t}").fetchone()[0]
        print(t, 'rows', cnt)
        rs = cur.execute(f"SELECT * FROM {t} LIMIT 5").fetchall()
        print('sample rows', rs)
    except Exception as e:
        print(t, 'err', e)
con.close()
