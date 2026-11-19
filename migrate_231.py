"""Migración aditiva 2.3.1; detener servicio y realizar copia previa."""
import sqlite3
from platform_app import DB, ENTITIES
from platform_app.participant_schema import SCHEMA_PARTICIPANTS
VERSION = '2.3.1'

def main():
    if not DB.is_file():
        raise RuntimeError('Falta la base central')
    with sqlite3.connect(f'file:{DB}?mode=rw', uri=True, timeout=20) as central:
        central.row_factory = sqlite3.Row
        if central.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Base central dañada')
        entities = central.execute('SELECT slug FROM entities ORDER BY id').fetchall()
        for ent in entities:
            slug = ent['slug']
            path = ENTITIES / slug / 'data' / 'rifas.sqlite3'
            if not path.is_file():
                raise RuntimeError(f'Falta base de {slug}')
            with sqlite3.connect(f'file:{path}?mode=rw', uri=True, timeout=20) as con:
                con.execute('PRAGMA foreign_keys=ON')
                if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError(f'Integridad incorrecta: {slug}')
                for table in ('participants', 'credit_movements', 'module_versions', 'metadata'):
                    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        raise RuntimeError(f'{slug}: falta {table}; se requiere 2.3.0')
                con.executescript(SCHEMA_PARTICIPANTS)
                con.execute('INSERT INTO module_versions(module,version) VALUES(?,?) ON CONFLICT(module) DO UPDATE SET version=excluded.version,updated_at=CURRENT_TIMESTAMP', ('participantes', VERSION))
                con.execute('INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', ('schema_version', VERSION))
            central.execute('UPDATE entities SET version=? WHERE slug=?', (VERSION, slug))
            print('Migrada:', slug)
        central.execute('INSERT OR IGNORE INTO releases(version,notes) VALUES(?,?)', (VERSION, 'Cambio y recuperación de contraseña; baja mixta'))
    print('MIGRACIÓN 2.3.1 FINALIZADA')
if __name__ == '__main__':
    main()
