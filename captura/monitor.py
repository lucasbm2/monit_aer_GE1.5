import os, struct, pandas as pd
from datetime import datetime
from scapy.all import sniff, IP, TCP, conf

ruta_csv = os.path.join(os.path.expanduser("~"), "Desktop", "DATOS_FINALES_X.csv")
mi_iface = next((iface for iface in conf.ifaces.values() if "192.168.X.X" in str(iface.ip)), None)

# MAPEO DE PRECISIÓN (Basado en tu última captura hex)
MAPEO = {
    "Potencia_kW": 128,  # <--- OFFSET ACTUALIZADO
    "RPM": 136, 
    "Viento_ms": 148,
    "V_Fase_A": 112,
    "T_Ambiente": 240,
    "T_Aceite": 236
}

def procesar(pkt):
    if pkt.haslayer(TCP) and pkt[IP].src == "192.168.X.X":
        raw = bytes(pkt)
        if len(raw) >= 462:
            try:
                datos = {"Hora": datetime.now().strftime("%H:%M:%S")}
                for var, off in MAPEO.items():
                    val = struct.unpack('<f', raw[off:off+4])[0]
                    # Filtro para limpiar basura de red
                    datos[var] = round(val, 2) if -10 < val < 5000 else 0.0

                os.system('cls' if os.name == 'nt' else 'clear')
                print(f"       >>> ANALIZADOR DE GENERACIÓN <<<")
                print(f" Hora: {datos['Hora']} | PLC: 192.168.X.X")
                print("-" * 55)
                print(f" POTENCIA:    {datos['Potencia_kW']} kW")
                print(f" GENERACIÓN:  {datos['RPM']} RPM | {datos['Viento_ms']} m/s")
                print(f" RED:         {datos['V_Fase_A']} V")
                print(f" TÉRMICO:     Amb: {datos['T_Ambiente']}°C | Aceite: {datos['T_Aceite']}°C")
                print("-" * 55)
                print(f" Archivo: Desktop/DATOS_FINALES_X.csv")

                df = pd.DataFrame([datos])
                df.to_csv(ruta_csv, mode='a', index=False, header=not os.path.exists(ruta_csv))
            except: pass

if mi_iface:
    sniff(iface=mi_iface, filter="tcp and host 192.168.X.X", prn=procesar, store=0)