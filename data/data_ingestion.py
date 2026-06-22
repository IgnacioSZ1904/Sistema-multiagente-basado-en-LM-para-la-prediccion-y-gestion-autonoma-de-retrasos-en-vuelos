from __future__ import annotations

import sys
from pathlib import Path

import duckdb

# ---------------------------------------------------------------------------
# Rutas y constantes
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent

PARQUET_FILE_PATH = DATA_DIR / "Flight_Delay.parquet"
ANALYTICAL_DB_PATH = DATA_DIR / "analytical_db.duckdb"

TABLE_NAME = "flights"


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------

def validate_parquet(parquet_path: Path) -> None:
    """
    Comprueba que el archivo parquet existe y es legible.
    """

    if not parquet_path.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo:\n{parquet_path}\n\n"
            "Descárgalo desde:\n"
            "https://www.kaggle.com/datasets/arvindnagaonkar/flight-delay"
        )

    try:
        with duckdb.connect() as con:
            con.execute(
                f"SELECT * FROM read_parquet('{parquet_path}') LIMIT 1"
            ).fetchone()

    except Exception as exc:
        raise ValueError(
            f"El archivo no parece ser un parquet válido:\n{exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Creación de la base de datos
# ---------------------------------------------------------------------------

def setup_analytical_db(
    parquet_path: Path = PARQUET_FILE_PATH,
    db_path: Path = ANALYTICAL_DB_PATH,
) -> None:
    """
    Importa el parquet a una tabla física DuckDB.

    Esto copia los datos una sola vez y deja la tabla preparada
    para consultas analíticas rápidas.
    """

    print(f"[setup_db] Validando parquet: {parquet_path}")
    validate_parquet(parquet_path)

    print(f"[setup_db] Creando base de datos: {db_path}")

    with duckdb.connect(str(db_path)) as con:

        # Eliminar tabla previa si existe
        con.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")

        print("[setup_db] Importando datos...")

        con.execute(f"""
            CREATE TABLE {TABLE_NAME} AS
            SELECT *
            FROM read_parquet('{parquet_path}')
        """)

        result = con.execute(
            f"SELECT COUNT(*) FROM {TABLE_NAME}"
        ).fetchone()
        total_rows = result[0] if result else 0

        schema = con.execute(
            f"DESCRIBE {TABLE_NAME}"
        ).fetchall()

    print()
    print("=" * 60)
    print("BASE DE DATOS INICIALIZADA")
    print("=" * 60)
    print(f"Archivo DB : {db_path}")
    print(f"Tabla      : {TABLE_NAME}")
    print(f"Registros  : {total_rows:,}")
    print()

    print("Columnas detectadas:")
    for column_name, column_type, *_ in schema:
        print(f"  - {column_name:<30} {column_type}")

    print()
    print("[OK] DuckDB listo para consultas.")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        setup_analytical_db()

    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
