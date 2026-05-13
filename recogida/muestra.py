import socket, struct, os, time
import pandas as pd
from datetime import datetime

# --- CONFIGURACIÓN ---
PLC_IP = "192.168.X.X"
PLC_PORT = X
ruta_csv = os.path.join(os.path.expanduser("~"), "DATOS_FINALES_X.csv")
LLAVE = bytes.fromhex("X")


MAPEO = {
    "V_Fase_A": 58, "V_Fase_B": 62, "V_Fase_C": 66,
    "Potencia_kW": 74, "RPM": 82, "Viento_ms": 94,
    
    # --- BLOQUE TÉRMICO ---
    "T_Exterior": 186,     
    "T_Winding_1": 194,     
    "T_Winding_2": 198,    
    "T_Gearbox_Sump": 202,  
    "T_Gearbox_Brg": 206,   
    "T_Gen_Bearing_A": 210, 
    "T_Bearing_B": 214,     
    "T_Nacelle": 222,       
    "T_Gen_Air": 226,       
    "T_Rotor_Brg": 234      
}

def monitor_autonomo():
    # Inicialización del CSV
    if not os.path.exists(ruta_csv):
        pd.DataFrame(columns=["Hora"] + list(MAPEO.keys())).to_csv(ruta_csv, index=False)

    while True:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10)
            s.connect((PLC_IP, PLC_PORT))
            s.send(LLAVE) 
            
            while True:
                raw = s.recv(1024)
                
                if len(raw) >= 400:
                    datos = {"Hora": datetime.now().strftime("%H:%M:%S")}
                    
                    for var, off in MAPEO.items():
                        val = struct.unpack('<f', raw[off:off+4])[0]
                        datos[var] = round(val, 2)

                    # --- INTERFAZ VISUAL ---
                    os.system('cls' if os.name == 'nt' else 'clear')
                    print(f"      >>> ANALIZADOR VJ2.2 PRO (TELEMETRÍA TOTAL) <<<")
                    print(f" Hora: {datos['Hora']} | Estado: CONECTADO | Bytes: {len(raw)}")
                    print("=" * 70)
                    print(f" RED:         {datos['V_Fase_A']} V | {datos['V_Fase_B']} V | {datos['V_Fase_C']} V")
                    print(f" POTENCIA:    {datos['Potencia_kW']} kW | VIENTO: {datos['Viento_ms']} m/s")
                    print(f" GENERACIÓN:  {datos['RPM']} RPM")
                    print("-" * 70)
                    print(f" AMBIENTE:    Exterior: {datos['T_Exterior']}°C | TOWER ACCELERATION: {datos['T_Nacelle']}°C")
                    print(f" ROTOR BEARING: {datos['T_Gearbox_Sump']}°C | Rodam.: {datos['T_Gearbox_Brg']}°C")
                    print(f" GENERATOR COOLING AIR:   {datos['T_Winding_1']}°C | GEARBOX BEARING A: {datos['T_Winding_2']}°C | DRIVE TRAIN ACCELERATION {datos['T_Gen_Air']}°C")
                    print(f" RODAMIENTOS: Gen A: {datos['T_Gen_Bearing_A']}°C | Gen B: {datos['T_Bearing_B']}°C")
                    print(f" ROTOR:       Rodam. Rotor: {datos['T_Rotor_Brg']}°C")
                    print("=" * 70)
                    print(f" Registrando en: {os.path.basename(ruta_csv)}")
                    
                    pd.DataFrame([datos]).to_csv(ruta_csv, mode='a', index=False, header=False)
                
                time.sleep(0.5)

        except Exception as e:
            os.system('cls' if os.name == 'nt' else 'clear')
            print(f"Buscando señal del PLC... (Error: {e})")
            time.sleep(5)
        finally:
            s.close()

if __name__ == "__main__":
    monitor_autonomo()