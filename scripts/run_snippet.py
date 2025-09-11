import os, sys
sys.path.insert(0, os.getcwd())
from agent.plc_agent.api.store import Store
from agent.plc_agent.api.routers.mappings import _load_mapping_from_user_db

st = Store.instance()
st.load_from_app_db()
print('tables loaded:', len(st.list_tables()))
for t in st.list_tables():
    print('table:', t['id'], t['name'], 'devId:', t.get('deviceId'))
    loaded = _load_mapping_from_user_db(t)
    print('loaded mapping deviceId:', loaded and loaded.get('deviceId'))
    print('loaded rows keys:', list((loaded or {}).get('rows', {}).keys()))
    # After loading, store should have rows
    if loaded:
        st.replace_mapping(t['id'], loaded)
    m = st.get_mapping(t['id'])
    print('store rows keys:', list((m or {}).get('rows', {}).keys()))
    # compute health
    sch = st.get_schema(t.get('schemaId')) or {'fields': []}
    required = [f.get('key') for f in (sch.get('fields') or [])]
    print('health:', st.mapping_health(t['id'], required_fields=required))

