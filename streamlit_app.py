import streamlit as st
import pandas as pd
import numpy as np
import time
from datetime import datetime

# Set Page Config for responsive layout
st.set_page_config(page_title="QuantOption Pro Live", layout="wide", initial_sidebar_state="expanded")
st.title("📊 QuantOption Pro - Live Chain Analytics Engine")

# --- SIMULATION FEED GENERATOR WITH MULTI-METRIC TRACKERS ---
def fetch_mock_option_chain(base_spot, is_stock=False):
    step = 20 if is_stock else 50
    strikes = range(int(base_spot - (step * 4)), int(base_spot + (step * 5)), step)
    data = []
    for s in strikes:
        data.append({
            'strike': s, 'type': 'CE',
            'ltp': max(2.0, (base_spot - s) + 40 + np.random.uniform(-2, 2)) if not is_stock else max(1.0, (base_spot * 0.02) + np.random.uniform(-0.5, 0.5)),
            'oi': int(1500000 * np.random.uniform(0.7, 1.3)) if not is_stock else int(80000 * np.random.uniform(0.5, 1.5)),
            'iv': 12.5 + np.random.uniform(-0.5, 1.0)
        })
        data.append({
            'strike': s, 'type': 'PE',
            'ltp': max(2.0, (s - base_spot) + 35 + np.random.uniform(-2, 2)) if not is_stock else max(1.0, (base_spot * 0.02) + np.random.uniform(-0.5, 0.5)),
            'oi': int(1400000 * np.random.uniform(0.7, 1.3)) if not is_stock else int(75000 * np.random.uniform(0.5, 1.5)),
            'iv': 13.1 + np.random.uniform(-0.5, 1.2)
        })
    return pd.DataFrame(data)

# --- SESSION STATE WAREHOUSE ---
if "snapshot_history" not in st.session_state:
    st.session_state.snapshot_history = {}
if "intraday_log" not in st.session_state:
    st.session_state.intraday_log = pd.DataFrame(columns=[
        "Timestamp", "Spot", "PCR", "Res_Min", "Res_Max", "Sup_Min", "Sup_Max", "India_VIX", "ATM_Straddle"
    ])
if "running" not in st.session_state:
    st.session_state.running = False

# --- SIDEBAR CONTROL PANEL ---
st.sidebar.header("🔧 Configuration Panel")

target_symbol = st.sidebar.selectbox(
    "Select Underlying Asset", 
    ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "RELIANCE", "TCS", "INFY", "HDFCBANK"]
)

broker_api_key = st.sidebar.text_input("Broker API Key", type="password")
client_id = st.sidebar.text_input("Client ID")

col1, col2 = st.sidebar.columns(2)
if col1.button("▶️ START ENGINE", use_container_width=True):
    st.session_state.running = True
if col2.button("⏸️ STOP ENGINE", use_container_width=True):
    st.session_state.running = False

# --- LIVE REFRESH LOOP CONTAINER ---
placeholder = st.empty()

# Dynamically establishing trading base price registers
base_price_map = {
    "NIFTY": 24334.30, "BANKNIFTY": 58521.40, "FINNIFTY": 26903.35, "SENSEX": 78151.45,
    "RELIANCE": 1327.20, "TCS": 2269.00, "INFY": 1096.50, "HDFCBANK": 819.60
}
base_spot = base_price_map.get(target_symbol, 24334.30)
is_stock_asset = target_symbol in ["RELIANCE", "TCS", "INFY", "HDFCBANK"]

# Initialize baseline structural parameters
if "sim_vix" not in st.session_state:
    st.session_state.sim_vix = 12.88

if st.session_state.running:
    while st.session_state.running:
        current_time = datetime.now().strftime("%H:%M:%S")
        
        # Simulate real-time ticking mechanics
        drift_scale = 1.0 if is_stock_asset else 8.0
        base_spot += np.random.uniform(-drift_scale, drift_scale * 1.05)
        st.session_state.sim_vix += np.random.uniform(-0.15, 0.16)
        st.session_state.sim_vix = max(9.0, min(30.0, st.session_state.sim_vix))
        
        # Ingest option chain
        df_current = fetch_mock_option_chain(base_spot, is_stock=is_stock_asset)
        st.session_state.snapshot_history[current_time] = df_current
        
        keys = list(st.session_state.snapshot_history.keys())
        t1_time = keys[-5] if len(keys) > 5 else keys[0]
        
        df1 = st.session_state.snapshot_history[t1_time].set_index(['strike', 'type'])
        df2 = df_current.set_index(['strike', 'type'])
        
        # Calculate Delta Metrics
        comp_df = pd.DataFrame(index=df2.index)
        comp_df['LTP'] = df2['ltp']
        comp_df['OI'] = df2['oi']
        comp_df['IV'] = df2['iv']
        comp_df['d_Price'] = df2['ltp'] - df1['ltp'].reindex(df2.index)
        comp_df['d_OI'] = df2['oi'] - df1['oi'].reindex(df2.index)
        comp_df.fillna(0, inplace=True)
        
        # Trader Vocabulary Classifier Matrix
        conditions = [
            (comp_df['d_Price'] > 0) & (comp_df['d_OI'] > 0),
            (comp_df['d_Price'] < 0) & (comp_df['d_OI'] > 0),
            (comp_df['d_Price'] < 0) & (comp_df['d_OI'] < 0),
            (comp_df['d_Price'] > 0) & (comp_df['d_OI'] < 0)
        ]
        labels = ['Long Buildup', 'Short Buildup', 'Long Unwinding', 'Short Covering']
        comp_df['Buildup_Tag'] = np.select(conditions, labels, default='Neutral')
        comp_df = comp_df.reset_index()
        
        # Structural Calculations
        ce_df = df_current[df_current['type'] == 'CE']
        pe_df = df_current[df_current['type'] == 'PE']
        pcr = pe_df['oi'].sum() / ce_df['oi'].sum() if ce_df['oi'].sum() > 0 else 0
        
        top3_ce = ce_df.nlargest(3, 'oi')['strike'].tolist()
        top3_pe = pe_df.nlargest(3, 'oi')['strike'].tolist()
        res_min, res_max = (min(top3_ce), max(top3_ce)) if top3_ce else (base_spot, base_spot)
        sup_min, sup_max = (min(top3_pe), max(top3_pe)) if top3_pe else (base_spot, base_spot)
        
        # --- ATM STRADDLE PREMIUM ENGINE ---
        step = 20 if is_stock_asset else 50
        atm_strike = round(base_spot / step) * step
        atm_ce = ce_df[ce_df['strike'] == atm_strike]['ltp'].values
        atm_pe = pe_df[pe_df['strike'] == atm_strike]['ltp'].values
        straddle_premium = (atm_ce[0] + atm_pe[0]) if (len(atm_ce) > 0 and len(atm_pe) > 0) else 150.0
        
        # Directional Signal Interpretation
        if pcr >= 1.25:
            trade_suggestion = "🟢 STRONG BULLISH (LOOK FOR LONG ENTRIES)"
            signal_color = "green"
        elif pcr <= 0.75:
            trade_suggestion = "🔴 STRONG BEARISH (LOOK FOR SHORT SHORTS)"
            signal_color = "red"
        else:
            trade_suggestion = "🟡 RANGEBOUND / NEUTRAL ZONE (WAIT FOR BREAKOUT)"
            signal_color = "orange"
            
        # Log entry for correlation metrics
        new_row = pd.DataFrame([{
            "Timestamp": current_time, "Spot": base_spot, "PCR": pcr,
            "Res_Min": res_min, "Res_Max": res_max, "Sup_Min": sup_min, "Sup_Max": sup_max,
            "India_VIX": st.session_state.sim_vix, "ATM_Straddle": straddle_premium
        }])
        st.session_state.intraday_log = pd.concat([st.session_state.intraday_log, new_row], ignore_index=True)
        
        # --- RENDERING THE VISUAL WEB UI ---
        with placeholder.container():
            st.markdown(f"### Strategy Action: :{signal_color}[{trade_suggestion}]")
            
            # Metrics Dashboard Grid
            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            m_col1.metric("📌 Spot Price", f"{base_spot:.2f}")
            m_col2.metric("📊 PCR Ratio", f"{pcr:.2f}")
            m_col3.metric("📉 India VIX", f"{st.session_state.sim_vix:.2f}")
            m_col4.metric("🛡️ ATM Straddle ({})".format(atm_strike), f"₹{straddle_premium:.2f}")
            
            st.markdown("---")
            
            # MULTI-AXIS CHART PLOTTING (PCR, VIX, STRADDLE)
            st.subheader("📈 Multi-Color Volatility Correlation Panel")
            metrics_chart_df = st.session_state.intraday_log.set_index("Timestamp")
            
            # Render lines in distinct tracks
            st.line_chart(metrics_chart_df[["PCR", "India_VIX", "ATM_Straddle"]])
            
            st.markdown("---")
            
            # Live Price Trajectory Index Channel Chart
            st.subheader("📊 Underlying Support/Resistance Price Tracker")
            st.line_chart(metrics_chart_df[["Spot", "Res_Min", "Sup_Min"]])
            
            st.markdown("---")
            
            # Option Chain Table Display
            st.subheader("⛓️ Processed Live Option Chain Data Matrix")
            def format_buildup(val):
                color = 'transparent'
                if val == 'Long Buildup': color = '#1e3d22'
                elif val == 'Short Buildup': color = '#3d1e1e'
                elif val == 'Short Covering': color = '#1e2d3d'
                return f'background-color: {color}'
            
            styled_df = comp_df.style.map(format_buildup, subset=['Buildup_Tag'])
            st.dataframe(styled_df, use_container_width=True, height=350)
            
        time.sleep(3)
else:
    st.info("Engine Idle. Enter your broker configuration metadata panel variables and click 'START ENGINE' to initialize dashboards.")
