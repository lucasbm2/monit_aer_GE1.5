import streamlit as st
import pandas as pd
import os
import time
import requests
from datetime import datetime, timedelta
from collections import deque
from io import StringIO
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="Telemetría", layout="wide")

st.markdown(
    "<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;}</style>",
    unsafe_allow_html=True
)

with st.sidebar:
    st.header("Configuración")
    frecuencia = st.select_slider("Actualización (s)", options=[1, 2, 5, 10, 15, 30], value=1)
    opciones_tiempo = {
        "15 min": 0.25,
        "1 hora": 1,
        "4 horas": 4,
        "24 horas": 24,
        "1 semana": 168
    }
    seleccion_t = st.selectbox("Ventana:", options=list(opciones_tiempo.keys()), index=0)
    horas_vista = opciones_tiempo[seleccion_t]

st.title("Panel de Control Aerogenerador")

ruta_csv = "C:/DATOS_FINALES_X.csv"
url_prediccion = "http://127.X.X.X/predecir_csv"

main_placeholder = st.empty()

if "hist_predicciones" not in st.session_state:
    st.session_state.hist_predicciones = deque(maxlen=20000)


def traducir_estado(codigo):
    try:
        codigo = int(codigo)
    except Exception:
        return "Sin datos"

    estados = {
        8: "Sistema OK",
        6: "Sistema OK",
        2: "Sin errores",
        20: "Calma",
        0: "Sin datos"
    }

    return estados.get(codigo, f"Estado {codigo}")


def cargar_lineas_csv():
    if horas_vista >= 168:
        max_lineas = 1210000
        salto_lineas = 600
    elif horas_vista >= 24:
        max_lineas = 180000
        salto_lineas = 120
    elif horas_vista >= 4:
        max_lineas = 35000
        salto_lineas = 20
    elif horas_vista >= 1:
        max_lineas = 10000
        salto_lineas = 5
    else:
        max_lineas = 3000
        salto_lineas = 1

    with open(ruta_csv, "r", encoding="utf-8", errors="ignore") as f:
        cabecera = f.readline()
        lineas = list(deque(f, maxlen=max_lineas))

    if not lineas:
        return None

    if salto_lineas > 1:
        lineas_muestreadas = lineas[::salto_lineas]

        if lineas[-1] not in lineas_muestreadas:
            lineas_muestreadas.append(lineas[-1])

        lineas = lineas_muestreadas

    return cabecera + "".join(lineas)


def reconstruir_fechas(df):
    df = df.copy().reset_index(drop=True)

    hora_parseada = pd.to_datetime(
        df["Hora"].astype(str),
        format="%H:%M:%S",
        errors="coerce"
    )

    df = df[hora_parseada.notna()].copy()
    hora_parseada = hora_parseada[hora_parseada.notna()]

    segundos = (
        hora_parseada.dt.hour * 3600 +
        hora_parseada.dt.minute * 60 +
        hora_parseada.dt.second
    )

    df["_segundos"] = segundos.values

    salto_dia = df["_segundos"].diff() < -43200
    bloque_dia = salto_dia.cumsum()

    bloque_actual = bloque_dia.max()
    hoy = datetime.now().date()

    df["Fecha_base"] = bloque_dia.apply(
        lambda b: hoy - timedelta(days=int(bloque_actual - b))
    )

    df["Hora_dt"] = pd.to_datetime(
        df["Fecha_base"].astype(str) + " " + df["Hora"].astype(str),
        errors="coerce"
    )

    df = df.drop(columns=["_segundos", "Fecha_base"])
    df = df.dropna(subset=["Hora_dt"])

    return df


def cargar_datos_realtime():
    if not os.path.exists(ruta_csv):
        return None

    try:
        contenido = cargar_lineas_csv()

        if not contenido:
            return None

        df = pd.read_csv(
            StringIO(contenido),
            on_bad_lines="skip",
            engine="python"
        )

        if df.empty:
            return None

        df.columns = df.columns.str.strip()

        if "Hora" not in df.columns:
            return None

        df = df[df["Hora"].astype(str).str.contains("Hora") == False]

        columnas_numericas = [
            "V_Fase_A",
            "V_Fase_B",
            "V_Fase_C",
            "Potencia_kW",
            "Viento_ms",
            "RPM",
            "T_Exterior",
            "tower_accel",
            "generator_cooling_air",
            "Cod_Error"
        ]

        for c in columnas_numericas:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        df = reconstruir_fechas(df)

        ahora = datetime.now()
        tiempo_limite = ahora - timedelta(hours=horas_vista)

        df = df.sort_values("Hora_dt")

        df_filtrado = df[
            (df["Hora_dt"] >= tiempo_limite) &
            (df["Hora_dt"] <= ahora)
        ]

        if df_filtrado.empty:
            df_filtrado = df.tail(300)

        return df_filtrado.copy()

    except Exception:
        return None


def cargar_prediccion_modelo():
    try:
        r = requests.get(url_prediccion, timeout=3)

        if r.status_code != 200:
            return {
                "error": f"HTTP {r.status_code}",
                "detalle": r.text
            }

        return r.json()

    except requests.exceptions.Timeout:
        return {
            "error": "Timeout: la API tarda demasiado en responder"
        }

    except requests.exceptions.ConnectionError:
        return {
            "error": "No se puede conectar con la API. Comprueba que api_prediccion.py está ejecutándose."
        }

    except Exception as e:
        return {
            "error": str(e)
        }


def registrar_prediccion(prediccion):
    if prediccion is None:
        return

    if "P_ESPERADA" not in prediccion:
        return

    st.session_state.hist_predicciones.append({
        "Hora_dt": datetime.now(),
        "P_ESPERADA": pd.to_numeric(prediccion.get("P_ESPERADA", 0), errors="coerce"),
        "P_ACT_MODELO": pd.to_numeric(prediccion.get("P_ACT", 0), errors="coerce"),
        "ERROR": pd.to_numeric(prediccion.get("ERROR", 0), errors="coerce"),
        "ERROR_PORC": pd.to_numeric(prediccion.get("ERROR_PORC", 0), errors="coerce"),
        "ESTADO_RENDIMIENTO": prediccion.get("ESTADO_RENDIMIENTO", "SIN_DATOS")
    })


def obtener_df_predicciones():
    df_pred = pd.DataFrame(st.session_state.hist_predicciones)

    if df_pred.empty:
        return df_pred

    tiempo_limite = datetime.now() - timedelta(hours=horas_vista)

    df_pred = df_pred[
        (df_pred["Hora_dt"] >= tiempo_limite) &
        (df_pred["Hora_dt"] <= datetime.now())
    ].copy()

    return df_pred


def preparar_datos_grafica(df):
    if df.empty:
        return df

    df_graf = df.copy()
    df_graf = df_graf.sort_values("Hora_dt")
    df_graf = df_graf.set_index("Hora_dt")

    columnas_grafica = ["Viento_ms", "RPM", "Potencia_kW"]

    columnas_existentes = [
        c for c in columnas_grafica
        if c in df_graf.columns
    ]

    if not columnas_existentes:
        return pd.DataFrame()

    if horas_vista >= 168:
        regla = "10min"
    elif horas_vista >= 24:
        regla = "60s"
    elif horas_vista >= 4:
        regla = "30s"
    elif horas_vista >= 1:
        regla = "10s"
    else:
        regla = "2s"

    df_graf = (
        df_graf[columnas_existentes]
        .resample(regla)
        .mean()
        .dropna(how="all")
        .reset_index()
    )

    max_puntos = 1200

    if len(df_graf) > max_puntos:
        paso = max(1, len(df_graf) // max_puntos)
        df_graf = df_graf.iloc[::paso].reset_index(drop=True)

    return df_graf


def preparar_predicciones_grafica(df_pred):
    if df_pred is None or df_pred.empty:
        return pd.DataFrame()

    df_pred = df_pred.copy()
    df_pred = df_pred.sort_values("Hora_dt")
    df_pred = df_pred.set_index("Hora_dt")

    if horas_vista >= 168:
        regla = "10min"
    elif horas_vista >= 24:
        regla = "60s"
    elif horas_vista >= 4:
        regla = "30s"
    elif horas_vista >= 1:
        regla = "10s"
    else:
        regla = "2s"

    df_pred = (
        df_pred[["P_ESPERADA", "P_ACT_MODELO"]]
        .resample(regla)
        .mean()
        .dropna(how="all")
        .reset_index()
    )

    max_puntos = 1200

    if len(df_pred) > max_puntos:
        paso = max(1, len(df_pred) // max_puntos)
        df_pred = df_pred.iloc[::paso].reset_index(drop=True)

    return df_pred


def crear_grafica(df, df_pred=None):
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    if "Viento_ms" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["Hora_dt"],
                y=df["Viento_ms"],
                name="Viento (m/s)",
                mode="lines",
                line=dict(color="#29b5e8", width=2)
            ),
            secondary_y=False
        )

    if "RPM" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["Hora_dt"],
                y=df["RPM"],
                name="RPM",
                mode="lines",
                line=dict(color="#ff4b4b", width=2)
            ),
            secondary_y=True
        )

    if "Potencia_kW" in df.columns:
        fig.add_trace(
            go.Scatter(
                x=df["Hora_dt"],
                y=df["Potencia_kW"],
                name="Generación real (kW)",
                mode="lines",
                line=dict(color="#ffaa00", width=2)
            ),
            secondary_y=True
        )

    if df_pred is not None and not df_pred.empty and "P_ESPERADA" in df_pred.columns:
        fig.add_trace(
            go.Scatter(
                x=df_pred["Hora_dt"],
                y=df_pred["P_ESPERADA"],
                name="Generación esperada modelo (kW)",
                mode="lines",
                line=dict(color="#00ff88", width=2, dash="dot")
            ),
            secondary_y=True
        )

    fig.update_layout(
        height=460,
        template="plotly_dark",
        margin=dict(l=20, r=20, t=20, b=20),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0
        ),
        xaxis_title="Tiempo",
        hovermode="x unified"
    )

    fig.update_yaxes(title_text="Viento (m/s)", range=[0, 20], secondary_y=False)
    fig.update_yaxes(title_text="RPM / Generación", range=[0, 2000], secondary_y=True)

    return fig


while True:
    df_raw = cargar_datos_realtime()
    prediccion = cargar_prediccion_modelo()
    registrar_prediccion(prediccion)

    if df_raw is not None and not df_raw.empty:
        df_display = df_raw.copy()

        columnas_rellenar = [
            c for c in df_display.columns
            if c not in ("Hora", "Hora_dt")
        ]

        df_display[columnas_rellenar] = df_display[columnas_rellenar].fillna(0)

        ultimo = df_display.iloc[-1]

        cod_actual = int(ultimo.get("Cod_Error", 0))
        desc_actual = traducir_estado(cod_actual)

        with main_placeholder.container():
            if cod_actual in [8, 6, 2]:
                st.success(f"**SISTEMA OPERATIVO:** {desc_actual}")
            elif cod_actual == 20:
                st.info(f"**ESTADO:** {desc_actual}")
            elif cod_actual == 0:
                st.warning("**ESTADO PLC:** Sin datos")
            else:
                st.warning(f"**ESTADO PLC:** {desc_actual}")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Voltaje Red", f"{ultimo.get('V_Fase_A', 0):.1f} V")
            m2.metric("Generación", f"{ultimo.get('Potencia_kW', 0):.1f} kW")
            m3.metric("Viento", f"{ultimo.get('Viento_ms', 0):.2f} m/s")
            m4.metric("RPM", f"{int(ultimo.get('RPM', 0))} RPM")

            st.divider()

            st.subheader("Predicción de rendimiento")
            st.caption(f"Última lectura API: {datetime.now().strftime('%H:%M:%S')}")
            st.json(prediccion)

            if prediccion is not None and "P_ESPERADA" in prediccion:
                p_act = prediccion.get("P_ACT", 0)
                p_esperada = prediccion.get("P_ESPERADA", 0)
                error = prediccion.get("ERROR", 0)
                error_porc = prediccion.get("ERROR_PORC", 0)
                estado_rendimiento = prediccion.get("ESTADO_RENDIMIENTO", "SIN_DATOS")

                p1, p2, p3, p4, p5 = st.columns(5)

                p1.metric("Potencia real", f"{p_act:.1f} kW")
                p2.metric("Potencia esperada", f"{p_esperada:.1f} kW")
                p3.metric("Diferencia", f"{error:.1f} kW")
                p4.metric("Diferencia %", f"{error_porc:.1f} %")
                p5.metric("Estado modelo", estado_rendimiento)

            else:
                st.warning("No se pudo leer la predicción del modelo")
                st.write(prediccion)

            st.divider()

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Temp. Ambiente", f"{ultimo.get('T_Exterior', 0):.1f} °C")
            c2.metric("Vibración Torre", f"{ultimo.get('tower_accel', 0):.2f} mm/s²")
            c3.metric("Temp. Generador", f"{ultimo.get('generator_cooling_air', 0):.1f} °C")
            c4.metric("Estado PLC", f"{desc_actual} ({cod_actual})")

            st.divider()

            df_graf = preparar_datos_grafica(df_display)
            df_pred = obtener_df_predicciones()
            df_pred_graf = preparar_predicciones_grafica(df_pred)

            if df_graf is not None and not df_graf.empty:
                fig = crear_grafica(df_graf, df_pred_graf)

                st.plotly_chart(
                    fig,
                    use_container_width=True,
                    key=f"grafica_principal_{datetime.now().timestamp()}"
                )
            else:
                st.warning("No hay datos suficientes para pintar la gráfica.")

            desde = df_display["Hora_dt"].min().strftime("%Y-%m-%d %H:%M:%S")
            hasta = df_display["Hora_dt"].max().strftime("%Y-%m-%d %H:%M:%S")
            puntos_grafica = len(df_graf) if df_graf is not None else 0
            puntos_prediccion = len(df_pred_graf) if df_pred_graf is not None else 0

            st.caption(
                f"Datos actualizados: {datetime.now().strftime('%H:%M:%S')} | "
                f"Ventana mostrada: {desde} - {hasta} | "
                f"Registro PLC: {ultimo['Hora']} | "
                f"Puntos cargados: {len(df_display)} | "
                f"Puntos gráfica: {puntos_grafica} | "
                f"Puntos predicción: {puntos_prediccion}"
            )

    else:
        with main_placeholder.container():
            st.warning("Sin datos disponibles en la ventana seleccionada.")
            st.write(prediccion)

    time.sleep(frecuencia)
