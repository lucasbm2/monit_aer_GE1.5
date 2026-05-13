from flask import Flask, request, jsonify
from flask_cors import CORS
from pathlib import Path
from collections import deque
from io import StringIO
from datetime import datetime
import pandas as pd
import joblib

app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).resolve().parent

RUTA_CSV_TIEMPO_REAL = r"C:\DATOS_FINALES_VJ22.csv"
RUTA_CSV_CON_PREDICCION = str(BASE_DIR / "DATOS_FINALES_VJ22_CON_PREDICCION.csv")
RUTA_MODELO = BASE_DIR / "modelo_rendimiento_pi3b.pkl"
RUTA_FEATURES = BASE_DIR / "features_modelo.pkl"

modelo = joblib.load(RUTA_MODELO)
features = joblib.load(RUTA_FEATURES)

ULTIMA_FIRMA_GUARDADA = None


def convertir_numero(valor):
    if valor is None:
        return 0.0

    valor = str(valor).strip()

    if valor == "" or valor.lower() in ["nan", "none", "null"]:
        return 0.0

    valor = valor.replace(",", ".").replace(" ", "")

    return float(valor)


def leer_ultimas_lineas_csv(max_lineas=2000):
    with open(RUTA_CSV_TIEMPO_REAL, "r", encoding="utf-8-sig", errors="ignore") as f:
        cabecera = f.readline()
        lineas = list(deque(f, maxlen=max_lineas))

    if not lineas:
        return pd.DataFrame()

    contenido = cabecera + "".join(lineas)

    df = pd.read_csv(
        StringIO(contenido),
        sep=",",
        engine="python",
        on_bad_lines="skip"
    )

    df.columns = [col.strip() for col in df.columns]

    return df


def leer_ultima_fila_valida_csv():
    df = leer_ultimas_lineas_csv(max_lineas=2000)

    if df.empty:
        return None, {"error": "El CSV está vacío"}

    columnas_necesarias = [
        "Viento_ms",
        "RPM",
        "T_Exterior",
        "Potencia_kW"
    ]

    for col in columnas_necesarias:
        if col not in df.columns:
            return None, {
                "error": f"Falta la columna {col} en el CSV",
                "columnas_csv": list(df.columns)
            }

    df = df[df["Hora"].astype(str).str.contains("Hora") == False] if "Hora" in df.columns else df

    for col in columnas_necesarias:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=columnas_necesarias)

    if df.empty:
        return None, {"error": "No hay filas válidas en el CSV"}

    return df.iloc[-1], None


def leer_csv_tiempo_real():
    df = pd.read_csv(
        str(RUTA_CSV_TIEMPO_REAL),
        sep=",",
        engine="python",
        encoding="utf-8-sig",
        on_bad_lines="skip"
    )

    df.columns = [col.strip() for col in df.columns]

    return df


def mapear_fila_csv(fila):
    return {
        "V_WIN": fila.get("Viento_ms", 0),
        "N_ROT_PLC": fila.get("RPM", 0),
        "WIND_DEV_10SEC": 0,
        "POS_NAC": 0,
        "BL1_ACT": 0,
        "BL2_ACT": 0,
        "BL3_ACT": 0,
        "T_AMB": fila.get("T_Exterior", 0),
        "P_ACT": fila.get("Potencia_kW", 0)
    }


def calcular_prediccion(data):
    entrada = {}

    for col in features:
        if col not in data:
            return None, {"error": f"Falta la variable {col}"}

        try:
            entrada[col] = convertir_numero(data[col])
        except ValueError:
            return None, {"error": f"Valor inválido en {col}: {data[col]}"}

    df_entrada = pd.DataFrame([entrada])
    p_esperada = float(modelo.predict(df_entrada[features])[0])

    respuesta = {
        "P_ESPERADA": round(p_esperada, 2)
    }

    if "P_ACT" in data:
        try:
            p_act = convertir_numero(data["P_ACT"])
        except ValueError:
            return None, {"error": f"Valor inválido en P_ACT: {data['P_ACT']}"}

        error = p_act - p_esperada
        error_porc = error / p_esperada if p_esperada != 0 else 0

        v_win = convertir_numero(data.get("V_WIN", entrada.get("V_WIN", 0)))
        rpm = convertir_numero(data.get("N_ROT_PLC", data.get("RPM", 0)))

        maquina_en_produccion = (
            rpm > 1 and
            v_win >= 2.5 and
            p_act > 0
        )

        anomalia = (
            maquina_en_produccion and
            p_esperada > 150 and
            p_act < p_esperada * 0.75
        )

        if not maquina_en_produccion:
            estado = "SIN_PRODUCCION"
        elif error_porc < -0.45:
            estado = "ANOMALIA"
        elif error_porc < -0.30:
            estado = "AVISO"
        else:
            estado = "NORMAL"

        respuesta.update({
            "P_ACT": round(p_act, 2),
            "ERROR": round(error, 2),
            "ERROR_PORC": round(error_porc * 100, 2),
            "ANOMALIA_RENDIMIENTO": bool(anomalia),
            "ESTADO_RENDIMIENTO": estado,
            "MAQUINA_EN_PRODUCCION": bool(maquina_en_produccion),
            "V_WIN": round(v_win, 2),
            "RPM": round(rpm, 2)
        })

    return respuesta, None


def generar_firma_fila(fila_original):
    fila_dict = fila_original.fillna("").to_dict()
    return tuple((str(k), str(v)) for k, v in fila_dict.items())


def guardar_fila_con_prediccion(fila_original, respuesta, data_modelo):
    global ULTIMA_FIRMA_GUARDADA

    firma_actual = generar_firma_fila(fila_original)

    if firma_actual == ULTIMA_FIRMA_GUARDADA:
        return False

    fila = fila_original.fillna("").to_dict()

    fila["FechaHora_Prediccion"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fila["P_ESPERADA"] = respuesta.get("P_ESPERADA", 0)
    fila["P_ACT_MODELO"] = respuesta.get("P_ACT", 0)
    fila["ERROR_MODELO"] = respuesta.get("ERROR", 0)
    fila["ERROR_PORC_MODELO"] = respuesta.get("ERROR_PORC", 0)
    fila["ESTADO_RENDIMIENTO"] = respuesta.get("ESTADO_RENDIMIENTO", "")
    fila["MAQUINA_EN_PRODUCCION"] = respuesta.get("MAQUINA_EN_PRODUCCION", False)
    fila["ANOMALIA_RENDIMIENTO"] = respuesta.get("ANOMALIA_RENDIMIENTO", False)

    fila["V_WIN_MODELO"] = data_modelo.get("V_WIN", 0)
    fila["N_ROT_PLC_MODELO"] = data_modelo.get("N_ROT_PLC", 0)
    fila["WIND_DEV_10SEC_MODELO"] = data_modelo.get("WIND_DEV_10SEC", 0)
    fila["POS_NAC_MODELO"] = data_modelo.get("POS_NAC", 0)
    fila["BL1_ACT_MODELO"] = data_modelo.get("BL1_ACT", 0)
    fila["BL2_ACT_MODELO"] = data_modelo.get("BL2_ACT", 0)
    fila["BL3_ACT_MODELO"] = data_modelo.get("BL3_ACT", 0)
    fila["T_AMB_MODELO"] = data_modelo.get("T_AMB", 0)

    df_fila = pd.DataFrame([fila])

    existe = Path(RUTA_CSV_CON_PREDICCION).exists()

    df_fila.to_csv(
        RUTA_CSV_CON_PREDICCION,
        mode="a",
        header=not existe,
        index=False,
        encoding="utf-8-sig"
    )

    ULTIMA_FIRMA_GUARDADA = firma_actual

    return True


@app.route("/", methods=["GET"])
def inicio():
    return jsonify({
        "status": "api funcionando",
        "rutas": [
            "/health",
            "/columnas_csv",
            "/ultima_fila_csv",
            "/predecir",
            "/predecir_csv"
        ]
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/columnas_csv", methods=["GET"])
def columnas_csv():
    try:
        df_csv = leer_csv_tiempo_real()
    except FileNotFoundError:
        return jsonify({
            "error": f"No existe el archivo {str(RUTA_CSV_TIEMPO_REAL)}"
        }), 404
    except Exception as e:
        return jsonify({
            "error": f"No se pudo leer el CSV: {str(e)}"
        }), 500

    return jsonify({
        "ruta_csv": str(RUTA_CSV_TIEMPO_REAL),
        "ruta_csv_con_prediccion": str(RUTA_CSV_CON_PREDICCION),
        "columnas_csv": list(df_csv.columns),
        "features_modelo": features
    })


@app.route("/ultima_fila_csv", methods=["GET"])
def ultima_fila_csv():
    try:
        fila, error = leer_ultima_fila_valida_csv()
    except FileNotFoundError:
        return jsonify({
            "error": f"No existe el archivo {str(RUTA_CSV_TIEMPO_REAL)}"
        }), 404
    except Exception as e:
        return jsonify({
            "error": f"No se pudo leer el CSV: {str(e)}"
        }), 500

    if error:
        return jsonify(error), 400

    return jsonify({
        "ruta_csv": str(RUTA_CSV_TIEMPO_REAL),
        "ultima_fila": fila.fillna("").to_dict()
    })


@app.route("/predecir", methods=["POST"])
def predecir():
    data = request.get_json()

    if data is None:
        return jsonify({"error": "No se recibió JSON"}), 400

    respuesta, error = calcular_prediccion(data)

    if error:
        return jsonify(error), 400

    return jsonify(respuesta)


@app.route("/predecir_csv", methods=["GET"])
def predecir_csv():
    try:
        fila, error = leer_ultima_fila_valida_csv()
    except FileNotFoundError:
        return jsonify({
            "error": f"No existe el archivo {str(RUTA_CSV_TIEMPO_REAL)}"
        }), 404
    except Exception as e:
        return jsonify({
            "error": f"No se pudo leer el CSV: {str(e)}"
        }), 500

    if error:
        return jsonify(error), 400

    data = mapear_fila_csv(fila)

    respuesta, error = calcular_prediccion(data)

    if error:
        return jsonify(error), 400

    try:
        guardado = guardar_fila_con_prediccion(fila, respuesta, data)
        error_guardado = None
    except Exception as e:
        guardado = False
        error_guardado = str(e)

    respuesta["FUENTE"] = "CSV"
    respuesta["RUTA_CSV"] = str(RUTA_CSV_TIEMPO_REAL)
    respuesta["RUTA_CSV_CON_PREDICCION"] = str(RUTA_CSV_CON_PREDICCION)
    respuesta["GUARDADO_CSV_CON_PREDICCION"] = guardado
    respuesta["ERROR_GUARDADO_CSV_CON_PREDICCION"] = error_guardado
    respuesta["DATOS_USADOS"] = data

    return jsonify(respuesta)


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        threaded=True
    )