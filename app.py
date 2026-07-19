import sys
import time
import threading
from datetime import datetime
import pandas as pd
import numpy as np
import xlwings as xw
import customtkinter as ctk

# Set styling theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# ==========================================
# 1. OPTION ANALYTICS ENGINE
# ==========================================
class RealTimeOptionEngine:
    def __init__(self, symbol, excel_file):
        self.symbol = symbol
        self.excel_file = excel_file
        self.snapshots = {}
        self.workbook = None
        self._init_excel()

    def _init_excel(self):
        try:
            self.workbook = xw.Book(self.excel_file)
        except Exception:
            self.workbook = xw.Book()
            self.workbook.save(self.excel_file)

        for sheet in ['OptionChain', 'IntradayLog']:
            if sheet not in [s.name for s in self.workbook.sheets]:
                self.workbook.sheets.add(sheet)
                
        log_sheet = self.workbook.sheets['IntradayLog']
        if log_sheet.range("A1").value is None:
            log_sheet.range("A1").value = ["Timestamp", "Spot", "PCR", "Res_Min", "Res_Max", "Sup_Min", "Sup_Max"]

    def process_data_cycle(self, raw_feed, spot_price):
        df = pd.DataFrame(raw_feed)
        current_time = datetime.now().strftime("%H:%M:%S")
        self.snapshots[current_time] = df
        
        if len(self.snapshots) > 200:
            del self.snapshots[next(iter(self.snapshots))]

        keys = list(self.snapshots.keys())
        t1_time = keys[-30] if len(keys) > 30 else keys[0]

        analyzed_chain = self._calculate_metrics(t1_time, current_time)
        zones = self._calculate_zones(current_time, spot_price)
        self._push_to_excel(analyzed_chain, zones)
        return zones

    def _calculate_metrics(self, t1, t2):
        df1 = self.snapshots[t1].set_index(['strike', 'type'])
        df2 = self.snapshots[t2].set_index(['strike', 'type'])

        t_delta = max((datetime.strptime(t2, "%H:%M:%S") - datetime.strptime(t1, "%H:%M:%S")).seconds / 60.0, 0.5)

        comp_df = pd.DataFrame(index=df2.index)
        comp_df['LTP'] = df2['ltp']
        comp_df['OI'] = df2['oi']
        comp_df['IV'] = df2['iv']
        comp_df['d_Price'] = df2['ltp'] - df1['ltp'].reindex(df2.index)
        comp_df['d_OI'] = df2['oi'] - df1['oi'].reindex(df2.index)
        comp_df.fillna(0, inplace=True)

        comp_df['OI_Velocity_Min'] = comp_df['d_OI'] / t_delta
        avg_change = comp_df['d_OI'].abs().mean()
        comp_df['Velocity_Alert'] = np.where(comp_df['d_OI'].abs() > (2 * avg_change), "🚨 SPIKE", "Normal")

        conditions = [
            (comp_df['d_Price'] > 0) & (comp_df['d_OI'] > 0),
            (comp_df['d_Price'] < 0) & (comp_df['d_OI'] > 0),
            (comp_df['d_Price'] < 0) & (comp_df['d_OI'] < 0),
            (comp_df['d_Price'] > 0) & (comp_df['d_OI'] < 0)
        ]
        labels = ['Long Buildup', 'Short Buildup', 'Long Unwinding', 'Short Covering']
        comp_df['Buildup_Tag'] = np.select(conditions, labels, default='Neutral')

        return comp_df.reset_index()

    def _calculate_zones(self, current_time, spot_price):
        df = self.snapshots[current_time]
        ce_df = df[df['type'] == 'CE']
        pe_df = df[df['type'] == 'PE']
        
        pcr = pe_df['oi'].sum() / ce_df['oi'].sum() if ce_df['oi'].sum() > 0 else 0
        top3_ce = ce_df.nlargest(3, 'oi')['strike'].tolist()
        top3_pe = pe_df.nlargest(3, 'oi')['strike'].tolist()
        
        return {
            'Time': current_time, 'Spot': spot_price, 'PCR': round(pcr, 3),
            'R_Min': min(top3_ce) if top3_ce else spot_price, 'R_Max': max(top3_ce) if top3_ce else spot_price,
            'S_Min': min(top3_pe) if top3_pe else spot_price, 'S_Max': max(top3_pe) if top3_pe else spot_price
        }

    def _push_to_excel(self, chain_df, zones):
        self.workbook.sheets['OptionChain'].range("A1").value = chain_df
        log_sheet = self.workbook.sheets['IntradayLog']
        last_row = log_sheet.range('A' + str(log_sheet.cells.last_cell.row)).end('up').row + 1
        log_sheet.range(f"A{last_row}").value = [
            zones['Time'], zones['Spot'], zones['PCR'], 
            zones['R_Min'], zones['R_Max'], zones['S_Min'], zones['S_Max']
        ]

# ==========================================
# 2. DESKTOP GUI INTERFACE
# ==========================================
class OptionTradingApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("QuantOption Pro - Live Chain Tracker")
        self.geometry("450x600")
        self.resizable(False, False)
        self.is_running = False

        self.title_label = ctk.CTkLabel(self, text="QUANTOPTION REAL-TIME ENGINE", font=ctk.CTkFont(size=18, weight="bold"))
        self.title_label.pack(pady=20)

        self.input_frame = ctk.CTkFrame(self)
        self.input_frame.pack(pady=10, px=20, fill="x", padx=20)

        self.lbl_sym = ctk.CTkLabel(self.input_frame, text="Target Index/Stock:")
        self.lbl_sym.grid(row=0, column=0, padx=10, pady=10, sticky="w")
        self.entry_sym = ctk.CTkEntry(self.input_frame, width=180)
        self.entry_sym.insert(0, "NIFTY")
        self.entry_sym.grid(row=0, column=1, padx=10, pady=10)

        self.lbl_key = ctk.CTkLabel(self.input_frame, text="Broker API Key:")
        self.lbl_key.grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.entry_key = ctk.CTkEntry(self.input_frame, show="*", width=180)
        self.entry_key.grid(row=1, column=1, padx=10, pady=10)

        self.lbl_id = ctk.CTkLabel(self.input_frame, text="Client ID:")
        self.lbl_id.grid(row=2, column=0, padx=10, pady=10, sticky="w")
        self.entry_id = ctk.CTkEntry(self.input_frame, width=180)
        self.entry_id.grid(row=2, column=1, padx=10, pady=10)

        self.status_frame = ctk.CTkFrame(self, fg_color="#1E1E1E")
        self.status_frame.pack(pady=20, fill="x", padx=20)

        self.lbl_status = ctk.CTkLabel(self.status_frame, text="Status: Disconnected", text_color="orange", font=ctk.CTkFont(weight="bold"))
        self.lbl_status.pack(pady=8)

        self.lbl_metrics = ctk.CTkLabel(self.status_frame, text="Spot: -- | PCR: --\nS/R Zone: --", font=ctk.CTkFont(size=13))
        self.lbl_metrics.pack(pady=8)

        self.btn_toggle = ctk.CTkButton(self, text="START LIVE ENGINE", fg_color="green", hover_color="#005F00", command=self.toggle_engine, height=45)
        self.btn_toggle.pack(pady=15, fill="x", padx=20)

    def toggle_engine(self):
        if not self.is_running:
            self.is_running = True
            self.btn_toggle.configure(text="STOP ENGINE", fg_color="red", hover_color="#5F0000")
            self.lbl_status.configure(text="Status: Active & Streaming...", text_color="green")
            threading.Thread(target=self.background_worker, daemon=True).start()
        else:
            self.is_running = False
            self.btn_toggle.configure(text="START LIVE ENGINE", fg_color="green", hover_color="#005F00")
            self.lbl_status.configure(text="Status: Disconnected", text_color="orange")

    def background_worker(self):
        engine = RealTimeOptionEngine(symbol=self.entry_sym.get(), excel_file="Live_Option_Dashboard.xlsx")
        base_spot = 24300.0
        while self.is_running:
            base_spot += np.random.uniform(-10, 12)
            strikes = range(int(base_spot - 200), int(base_spot + 250), 50)
            
            raw_feed = []
            for s in strikes:
                raw_feed.append({'strike': s, 'type': 'CE', 'ltp': max(5.0, (base_spot - s) + 40 + np.random.uniform(-2,2)), 'oi': int(1500000 * np.random.uniform(0.7, 1.3)), 'iv': 12.5 + np.random.uniform(-0.5, 1.0)})
                raw_feed.append({'strike': s, 'type': 'PE', 'ltp': max(5.0, (s - base_spot) + 35 + np.random.uniform(-2,2)), 'oi': int(1400000 * np.random.uniform(0.7, 1.3)), 'iv': 13.1 + np.random.uniform(-0.5, 1.2)})

            zones = engine.process_data_cycle(raw_feed, spot_price=base_spot)
            
            self.lbl_metrics.configure(
                text=f"Spot: {zones['Spot']:.2f}  |  PCR: {zones['PCR']}\nSupport: {zones['S_Min']} - {zones['S_Max']} | Resistance: {zones['R_Min']} - {zones['R_Max']}"
            )
            
            time.sleep(3)

if __name__ == "__main__":
    app = OptionTradingApp()
    app.mainloop()

