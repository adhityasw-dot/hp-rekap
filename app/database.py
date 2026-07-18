from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DB_PATH

# Pastikan folder data ada
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# Kolom baru di tabel items (migrasi ringan SQLite)
_ITEM_EXTRA_COLS = {
    "buyer": "VARCHAR(255) DEFAULT ''",
    "buyer_phone": "VARCHAR(60) DEFAULT ''",
    "imei": "VARCHAR(32) DEFAULT ''",
    "imei2": "VARCHAR(32) DEFAULT ''",
    "meid": "VARCHAR(32) DEFAULT ''",
    "serial_number": "VARCHAR(64) DEFAULT ''",
    "battery_health": "VARCHAR(16) DEFAULT ''",
    "device_info_json": "TEXT DEFAULT ''",
    "imei_checked_at": "DATETIME",
    "imei_provider": "VARCHAR(80) DEFAULT ''",
    "unit_photos_json": "TEXT DEFAULT '[]'",
    "threetools_photos_json": "TEXT DEFAULT '[]'",
}


def ensure_schema():
    """Migrasi ringan SQLite (kolom baru + tabel QC + sale_notas)."""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(items)")).fetchall()}
        if cols:
            for name, decl in _ITEM_EXTRA_COLS.items():
                if name not in cols:
                    conn.execute(text(f"ALTER TABLE items ADD COLUMN {name} {decl}"))
        # item_qc_checks.photos_json
        qc_cols = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(item_qc_checks)")).fetchall()
        }
        if qc_cols and "photos_json" not in qc_cols:
            conn.execute(
                text("ALTER TABLE item_qc_checks ADD COLUMN photos_json TEXT DEFAULT '[]'")
            )
        # sale_notas — arsip nota + TTD digital
        tables = {
            r[0]
            for r in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        if "sale_notas" not in tables:
            conn.execute(
                text(
                    """
                    CREATE TABLE sale_notas (
                        id INTEGER PRIMARY KEY,
                        item_id INTEGER NOT NULL,
                        nota_no VARCHAR(32) DEFAULT '',
                        buyer_name VARCHAR(255) DEFAULT '',
                        buyer_phone VARCHAR(60) DEFAULT '',
                        item_name VARCHAR(255) DEFAULT '',
                        imei VARCHAR(32) DEFAULT '',
                        serial_number VARCHAR(64) DEFAULT '',
                        sell_price FLOAT DEFAULT 0,
                        sell_date DATE,
                        battery_health VARCHAR(16) DEFAULT '',
                        snapshot_json TEXT DEFAULT '{}',
                        signature_path VARCHAR(512) DEFAULT '',
                        signed_at DATETIME,
                        agreed_terms BOOLEAN DEFAULT 0,
                        voided BOOLEAN DEFAULT 0,
                        created_by VARCHAR(64) DEFAULT '',
                        created_at DATETIME,
                        updated_at DATETIME,
                        FOREIGN KEY(item_id) REFERENCES items(id) ON DELETE CASCADE
                    )
                    """
                )
            )
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sale_notas_item_id ON sale_notas(item_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sale_notas_nota_no ON sale_notas(nota_no)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sale_notas_buyer_name ON sale_notas(buyer_name)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_sale_notas_buyer_phone ON sale_notas(buyer_phone)"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
