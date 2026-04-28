import pandas as pd
import numpy as np
import os

# Columnas de alto valor analítico (excluimos las redundantes)
COLUMNAS = [
    # Temporales
    "Year", "Month", "DayofMonth", "FlightDate",
    # Aerolínea y rutas
    "Marketing_Airline_Network", "OriginCityName", "DestCityName",
    # Delays de salida y llegada
    "DepDelay", "DepDelayMinutes", "ArrDelay", "ArrDelayMinutes",
    # Causas del delay
    "CarrierDelay", "WeatherDelay", "NASDelay", "SecurityDelay", "LateAircraftDelay",
    # Operacional
    "TaxiOut", "TaxiIn", "AirTime", "Distance",
    "CRSElapsedTime", "ActualElapsedTime",
]

def optimizar_memoria(df: pd.DataFrame) -> pd.DataFrame:
    """
    Reduce el tipo de dato de cada columna al mínimo necesario
    sin pérdida de información.
    """
    memoria_antes = df.memory_usage(deep=True).sum() / 1024**2

    for col in df.select_dtypes(include=["float64"]).columns:
        df[col] = pd.to_numeric(df[col], downcast="float")  # float64 → float32

    for col in df.select_dtypes(include=["int64"]).columns:
        df[col] = pd.to_numeric(df[col], downcast="integer")  # int64 → int16/int32

    for col in df.select_dtypes(include=["object"]).columns:
        if df[col].nunique() / len(df) < 0.05:  # Baja cardinalidad → category
            df[col] = df[col].astype("category")

    memoria_despues = df.memory_usage(deep=True).sum() / 1024**2
    print(f"💾 Memoria: {memoria_antes:.1f} MB → {memoria_despues:.1f} MB "
          f"(ahorro: {(1 - memoria_despues/memoria_antes)*100:.1f}%)")

    return df


def main():
    file_path = "Flight_delay.parquet"

    print("📂 Cargando dataset con columnas seleccionadas...")
    df = pd.read_parquet(file_path, columns=COLUMNAS)
    print(f"✅ Registros cargados: {len(df):,}")

    print("\n🔧 Optimizando memoria...")
    df = optimizar_memoria(df)

    print("\n📊 Esquema resultante:")
    print(df.dtypes)

    print("\n📈 Estadísticas descriptivas de delays:")
    print(df[["DepDelay", "ArrDelay", "CarrierDelay",
              "WeatherDelay", "NASDelay"]].describe())

    # ── Análisis 1: Delay medio por aerolínea ──────────────────────────────
    delay_aerolinea = (
        df[df["DepDelay"] > 0]
        .groupby("Marketing_Airline_Network")
        .agg(
            avg_dep_delay=("DepDelay", "mean"),
            avg_arr_delay=("ArrDelay", "mean"),
            total_vuelos=("DepDelay", "count"),
            pct_carrier=("CarrierDelay", "mean"),
            pct_weather=("WeatherDelay", "mean"),
            pct_nas=("NASDelay", "mean"),
        )
        .reset_index()
        .sort_values("avg_dep_delay", ascending=False)
    )
    print("\n✈️ Delay por aerolínea:")
    print(delay_aerolinea.to_string(index=False))

    # ── Análisis 2: Delay por mes (estacionalidad) ─────────────────────────
    delay_mensual = (
        df[df["DepDelay"] > 0]
        .groupby("Month")["DepDelay"]
        .mean()
        .reset_index()
        .rename(columns={"DepDelay": "avg_dep_delay"})
    )
    print("\n📅 Delay medio por mes:")
    print(delay_mensual.to_string(index=False))

    # ── Análisis 3: Rutas con mayor delay ─────────────────────────────────
    delay_ruta = (
        df[df["DepDelay"] > 10]
        .groupby(["OriginCityName", "DestCityName"])
        .agg(
            avg_delay=("DepDelay", "mean"),
            vuelos=("DepDelay", "count")
        )
        .reset_index()
        .sort_values("avg_delay", ascending=False)
        .head(20)
    )
    print("\n🗺️ Top 20 rutas con mayor delay:")
    print(delay_ruta.to_string(index=False))

    # ── Guardar resultados ─────────────────────────────────────────────────
    os.makedirs("output", exist_ok=True)
    df.to_parquet("output/dataset_optimizado.parquet", index=False)
    delay_aerolinea.to_csv("output/delay_por_aerolinea.csv", index=False)
    delay_mensual.to_csv("output/delay_por_mes.csv", index=False)
    delay_ruta.to_csv("output/delay_por_ruta.csv", index=False)
    print("\n💾 Todos los resultados guardados en /output")


if __name__ == "__main__":
    main()