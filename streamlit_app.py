import streamlit as st
import pandas as pd
import numpy as np
import time
from datetime import datetime
from dhanhq import DhanContext, dhanhq
import plotly.graph_objects as go

# Set Page Config for responsive layout
st.set_page_config(page_title="QuantOption Pro Live - Dhan Engine", layout="wide", initial_sidebar_state="expanded")
st.title("📊 QuantOption Pro - Live Dhan Analytics Engine")

# --- SIMULATION FEED GENERATOR (FALLBACK FOR WEEKENDS) ---
def fetch_mock_option_chain(base_spot, is_stock=False):
    step = 20 if is_stock else 50
    strikes = range(int(base_spot - (step * 4)), int(base_spot + (step * 5)), step)
    data = []
    for s in strikes:
        data.append({
            'strike': s, 'type': 'CE',
            'ltp': max(2.0, (base_spot - s) + 40 + np.random.uniform(-4, 4)) if not is_stock else max(1.0, (base_spot * 0.02) + np.random.uniform(-0.5, 0.5)),
            'oi': int(1500000 * np.random.uniform(0.7, 1.3)) if not is_stock else int(80000 * np.random.uniform(0.5, 1.5)),
            'iv': 12.5 + np.random.uniform(-0.5, 1.0)
        })
        data.append({
            'strike': s, 'type': 'PE',
            'ltp': max(2.0, (s - base_spot) + 35 + np.random.uniform(-4, 4)) if not is_stock else max(1.0, (base_spot * 0.02) + np.random.uniform(-0.5, 0.5)),
            'oi': int(1400000 * np.random.uniform(0.7, 1.3)) if not is_stock else int(75000 * np.random.uniform(0.5, 1.5)),
            'iv': 13.1 + np.random.uniform(-0.5, 1.2)
        })
    return pd.DataFrame(data)

# --- DHAN DATA ENGINE INTEGRATION ---
def fetch_dhan_option_chain(dhan_client, security_id, exchange_segment, expiry_date):
    try:
        oc_data = dhan_client.option_chain(
            under_security_id=int(security_id),
            under_exchange_segment=exchange_segment,
            expiry=expiry_date
        )
        
        if oc_data.get('status') == 'success' and 'data' in oc_data:
            chain_records = []
            base_spot = oc_data['data'].get('last_price', 0.0)
            option_chain_map = oc_data['data'].get('oc', {})
            
            if not option_chain_map:
                st.warning("Dhan connected, but returned an empty option chain. (Market might be closed or expiry is invalid).")
                return 0.0, pd.DataFrame()
                
            for strike_str, options in option_chain_map.items():
                strike_val = float(strike_str)
                if 'ce' in options:
                    ce = options['ce']
                    chain_records.append({
                        'strike': strike_val, 'type': 'CE',
                        'ltp': ce.get('last_price', 0.0), 'oi': ce.get('oi', 0),
                        'iv': ce.get('implied_volatility', 15.0)
                    })
                if 'pe' in options:
                    pe = options['pe']
                    chain_records.append({
                        'strike': strike_val, 'type': 'PE',
                        'ltp': pe.get('last_price', 0.0), 'oi': pe.get('oi', 0),
                        'iv': pe.get('implied_volatility', 15.0)
                    })
            return base_spot, pd.DataFrame(chain_records)
        else:
            st.error(f"Dhan API Response Error: {oc_data.get('remarks', 'Unknown error')}")
    except Exception as e:
        st.error(f"Dhan Link Exception: {str(e)}")
    return 0.0, pd.DataFrame()

# --- HELPER TO BUILD OHLC CANDLES ---
def update_ohlc_history(history_list, current_price, current_time):
    if not history_list or history_list[-1]['time'] != current_time:
        history_list.append({
            'time': current_time, 'open': current_price, 'high': current_price, 'low': current_price, 'close': current_price
        })
    else:
        history_list[-1]['high'] = max(history_list[-1]['high'], current_price)
        history_list[-1]['low'] = min(history_list[-1]['low'], current_price)
        history_list[-1]['close'] = current_price
    if len(history_list) > 40:
        history_list.pop(0)

# --- SESSION STATE WAREHOUSE ---
if "snapshot_history" not in st.session_state:
    st.session_state.snapshot_history = {}
if "intraday_log" not in st.session_state:
    st.session_state.intraday_log = pd.DataFrame(columns=["Timestamp", "Spot", "PCR", "Res_Min", "Res_Max", "Sup_Min", "Sup_Max", "India_VIX", "ATM_Straddle"])
if "atm_ce_ohlc" not in st.session_state:
    st.session_state.atm_ce_ohlc = []
if "atm_pe_ohlc" not in st.session_state:
    st.session_state.atm_pe_ohlc = []
if "running" not in st.session_state:
    st.session_state.running = False

# --- SIDEBAR CONTROL PANEL ---
st.sidebar.header("🔌 Mode Selection")
engine_mode = st.sidebar.radio("Data Stream Source", ["Simulation Mode (Weekend/Testing)", "Live Dhan API Mode"])

st.sidebar.markdown("---")
st.sidebar.header("🔑 Dhan Developer Credentials")
client_id = st.sidebar.text_input("Dhan Client ID", type="default")
access_token = st.sidebar.text_input("Dhan Access Token (JWT)", type="password")

st.sidebar.markdown("---")
st.sidebar.header("🎯 Target Selection")
target_symbol = st.sidebar.selectbox("Select Asset Profile", ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX", "RELIANCE", "TCS", "INFY", "HDFCBANK"])
expiry_date = st.sidebar.text_input("Expiry Date (YYYY-MM-DD)", value="2026-07-23")

col1, col2 = st.sidebar.columns(2)
if col1.button("▶️ START ENGINE", use_container_width=True):
    if engine_mode == "Live Dhan API Mode" and (not client_id or not access_token):
        st.sidebar.error("Provide valid Dhan credentials first!")
    else:
        st.session_state.running = True
if col2.button("⏸️ STOP ENGINE", use_container_width=True):
    st.session_state.running = False

# Mappings
security_id_map = {"NIFTY": 13, "BANKNIFTY": 25, "FINNIFTY": 27, "SENSEX": 51, "RELIANCE": 2885, "TCS": 11536, "INFY": 1594, "HDFCBANK": 1333}
segment_map = {"NIFTY": "IDX_I", "BANKNIFTY": "IDX_I", "FINNIFTY": "IDX_I", "SENSEX": "IDX_I", "RELIANCE": "NSE_EQ", "TCS": "NSE_EQ", "INFY": "NSE_EQ", "HDFCBANK": "NSE_EQ"}
base_price_map = {"NIFTY": 24330.0, "BANKNIFTY": 52400.0, "FINNIFTY": 23200.0, "SENSEX": 80100.0, "RELIANCE": 2450.0, "TCS": 4150.0, "INFY": 1850.0, "HDFCBANK": 1650.0}

is_stock_asset = target_symbol in ["RELIANCE", "TCS", "INFY", "HDFCBANK"]
placeholder = st.empty()

if st.session_state.running:
    dhan = None
    if engine_mode == "Live Dhan API Mode":
        context = DhanContext(client_id, access_token)
        dhan = dhanhq(context)
        
    sim_spot = base_price_map.get(target_symbol, 24330.0)
    
    while st.session_state.running:
        current_time = datetime.now().strftime("%H:%M:%S")
        
        if engine_mode == "Live Dhan API Mode":
            scrip_id = security_id_map.get(target_symbol, 13)
            segment_id = segment_map.get(target_symbol, "IDX_I")
            base_spot, df_current = fetch_dhan_option_chain(dhan, scrip_id, segment_id, expiry_date)
        else:
            # Simulation mode parameters ticker
            sim_spot += np.random.uniform(-5, 5.2)
            base_spot = sim_spot
            df_current = fetch_mock_option_chain(base_spot, is_stock=is_stock_asset)
            
        if df_current.empty:
            st.info("Awaiting live data metrics from Dhan API streams... (Check error logs on screen or toggle to Simulation Mode)")
            time.sleep(3)
            continue
            
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
        
        # Buildup Tagging
        conditions = [
            (comp_df['d_Price'] > 0) & (comp_df['d_OI'] > 0),
            (comp_df['d_Price'] < 0) & (comp_df['d_OI'] > 0),
            (comp_df['d_Price'] < 0) & (comp_df['d_OI'] < 0),
            (comp_df['d_Price'] > 0) & (comp_df['d_OI'] < 0)
        ]
        labels = ['Long Buildup', 'Short Buildup', 'Long Unwinding', 'Short Covering']
        comp_df['Buildup_Tag'] = np.select(conditions, labels, default='Neutral')
        comp_df = comp_df.reset_index()
        
        ce_df = df_current[df_current['type'] == 'CE']
        pe_df = df_current[df_current['type'] == 'PE']
        pcr = pe_df['oi'].sum() / ce_df['oi'].sum() if ce_df['oi'].sum() > 0 else 0
        
        top3_ce = ce_df.nlargest(3, 'oi')['strike'].tolist()
        top3_pe = pe_df.nlargest(3, 'oi')['strike'].tolist()
        res_min, res_max = (min(top3_ce), max(top3_ce)) if top3_ce else (base_spot, base_spot)
        sup_min, sup_max = (min(top3_pe), max(top3_pe)) if top3_pe else (base_spot, base_spot)
        
        step = 20 if is_stock_asset else 50
        atm_strike = round(base_spot / step) * step
        atm_ce_row = ce_df[ce_df['strike'] == atm_strike]
        atm_pe_row = pe_df[pe_df['strike'] == atm_strike]
        
        ltp_ce = atm_ce_row['ltp'].values[0] if not atm_ce_row.empty else 0.0
        ltp_pe = atm_pe_row['ltp'].values[0] if not atm_pe_row.empty else 0.0
        straddle_premium = ltp_ce + ltp_pe
        
        update_ohlc_history(st.session_state.atm_ce_ohlc, ltp_ce, current_time)
        update_ohlc_history(st.session_state.atm_pe_ohlc, ltp_pe, current_time)
        
        if engine_mode == "Live Dhan API Mode":
            try:
                vix_res = dhan.get_ltp([("NSE_EQ", "26017")])
                live_vix = vix_res[0].get('ltp', 13.50) if vix_res else 13.50
            except:
                live_vix = 13.50
        else:
            live_vix = 13.20 + np.random.uniform(-0.1, 0.1)
        
        if pcr >= 1.25: trade_suggestion, signal_color = "🟢 STRONG BULLISH (GO LONG)", "green"
        elif pcr <= 0.75: trade_suggestion, signal_color = "🔴 STRONG BEARISH (GO SHORT)", "red"
        else: trade_suggestion, signal_color = "🟡 RANGEBOUND / NEUTRAL ZONE", "orange"
            
        new_row = pd.DataFrame([{"Timestamp": current_time, "Spot": base_spot, "PCR": pcr, "Res_Min": res_min, "Res_Max": res_max, "Sup_Min": sup_min, "Sup_Max": sup_max, "India_VIX": live_vix, "ATM_Straddle": straddle_premium}])
        st.session_state.intraday_log = pd.concat([st.session_state.intraday_log, new_row], ignore_index=True)
        
        with placeholder.container():
            st.markdown(f"### Strategy Action: :{signal_color}[{trade_suggestion}]")
            m_col1, m_col2, m_col3, m_col4 = st.columns(4)
            m_col1.metric("📌 Spot Price", f"{base_spot:.2f}")
            m_col2.metric("📊 PCR Ratio", f"{pcr:.2f}")
            m_col3.metric("📉 India VIX", f"{live_vix:.2f}")
            m_col4.metric(f"🛡️ ATM Straddle ({atm_strike})", f"₹{straddle_premium:.2f}")
            
            st.markdown("---")
            st.subheader(f"🕯️ ATM Strike {atm_strike} - Live Candlestick Analytics")
            c_col1, c_col2 = st.columns(2)
            df_ce_ohlc = pd.DataFrame(st.session_state.atm_ce_ohlc)
            df_pe_ohlc = pd.DataFrame(st.session_state.atm_pe_ohlc)
            
            with c_col1:
                st.markdown("**ATM Call Option (CE) Pricing**")
                if not df_ce_ohlc.empty:
                    fig_ce = go.Figure(data=[go.Candlestick(x=df_ce_ohlc['time'], open=df_ce_ohlc['open'], high=df_ce_ohlc['high'], low=df_ce_ohlc['low'], close=df_ce_ohlc['close'], increasing_line_color='#26a69a', decreasing_line_color='#ef5350')])
                    fig_ce.update_layout(xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=10, b=10), height=280)
                    st.plotly_chart(fig_ce, use_container_width=True)
            with c_col2:
                st.markdown("**ATM Put Option (PE) Pricing**")
                if not df_pe_ohlc.empty:
                    fig_pe = go.Figure(data=[go.Candlestick(x=df_pe_ohlc['time'], open=df_pe_ohlc['open'], high=df_pe_ohlc['high'], low=df_pe_ohlc['low'], close=df_pe_ohlc['close'], increasing_line_color='#26a69a', decreasing_line_color='#ef5350')])
                    fig_pe.update_layout(xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=10, b=10), height=280)
                    st.plotly_chart(fig_pe, use_container_width=True)
            
            st.markdown("---")
            st.subheader("📈 Volatility Correlation Panel (Line Form)")
            metrics_chart_df = st.session_state.intraday_log.set_index("Timestamp")
            st.line_chart(metrics_chart_df[["PCR", "India_VIX", "ATM_Straddle"]])
            
            st.markdown("---")
            st.subheader("📊 Support/Resistance Price Tracker (Line Form)")
            st.line_chart(metrics_chart_df[["Spot", "Res_Min", "Sup_Min"]])
            
            st.markdown("---")
            st.subheader("⛓️ Processed Live Option Chain Data Matrix")
            def format_buildup(val):
                color = 'transparent'
                if val == 'Long Buildup': color = '#1e3d22'
                elif val == 'Short Buildup': color = '#3d1e1e'
                elif val == 'Short Covering': color = '#1e2d3d'
                return f'background-color: {color}'
            styled_df = comp_df.style.map(format_buildup, subset=['Buildup_Tag'])
            st.dataframe(styled_df, use_container_width=True, height=300)
            
        time.sleep(3)
else:
    st.info("Dhan Engine Idle. Select mode, enter details in the left panel and tap 'START ENGINE'.")
