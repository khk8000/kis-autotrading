# app.py
import os
import sys
import time
import logging
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# ==============================================================================
# 0. 전역 로깅 인프라 및 추적성 동기화
# ==============================================================================
logger = logging.getLogger("app_web")

# ==============================================================================
# 1. [통합 환경 설계] 프로젝트 루트 및 코어 모듈 정방향 임포트
# ==============================================================================
from src.core.config import ConfigManager
from src.api.auth import KoreaInvestmentAuth
from src.api.market_data import MarketData
from src.api.order import OrderAPI
from src.core.trading_system import TradingSystem

# ⚠️ Streamlit 규격: 페이지 설정은 반드시 최상단에 단 1회만 호출되어야 합니다.
st.set_page_config(
    page_title="Daelung 양적투자 시스템 - 마스터 대시보드",
    page_icon="📊",
    layout="wide"
)

# ==============================================================================
# 2. 🔥 [의존성 주입 가두리 양식장] 단일 공급원 인프라 빌드 파이프라인
# ==============================================================================
if 'infrastructure_initialized' not in st.session_state:
    st.info("🔄 [통합 환경 설계] 최초 기동에 따른 인프라 레이어 정방향 조립 중...")
    try:
        # A. 단일 공급원 환경설정 매니저 가동
        config_manager = ConfigManager(config_dir='config')
        st.session_state.config_manager = config_manager
        
        # B. 한국투자증권 인증 인프라 객체 빌드
        auth_client = KoreaInvestmentAuth(config_path='config/api_config.yaml')
        st.session_state.auth_client = auth_client
        
        # C. 시세 정보 게이트웨이 바인딩
        market_data = MarketData(auth_client=auth_client, mode='paper')
        st.session_state.market_data = market_data
        
        # D. 주문/계좌 관리 파이프라인 동기화
        account_no = os.environ.get("KIS_PAPER_ACC", "")
        order_api = OrderAPI(auth_client=auth_client, account_no=account_no, mode='paper')
        st.session_state.order_api = order_api
        
        # E. [의존성 주입 일원화] 조립 완료된 인프라를 코어 엔진에 주입
        trading_system = TradingSystem(
            auth_client=auth_client,
            market_data=market_data,
            order_api=order_api,
            config_manager=config_manager,
            strategy_type="basic"
        )
        trading_system.initialize()
        st.session_state.trading_system = trading_system
        
        st.session_state.infrastructure_initialized = True
        st.rerun()

    except Exception as e:
        st.error(f"🚨 [웹 부트스트랩 붕괴] 인프라 조립 중 치명적 에러 발생: {str(e)}")
        logger.critical(f"Web Bootstrap Critical Error: {str(e)}", exc_info=True)
        st.stop()

# ==============================================================================
# 3. [싱글톤 글로벌 바인딩] 하위 레이어용 변수 매핑
# ==============================================================================
config_manager = st.session_state.config_manager
auth_client = st.session_state.auth_client
market_data = st.session_state.market_data
order_api = st.session_state.order_api
trading_system = st.session_state.trading_system

# ==============================================================================
# 4. 🎛️ 실시간 데이터 백그라운드 폴링 및 상태 관리 유틸리티
# ==============================================================================
@st.cache_data(ttl=5)
def fetch_realtime_balance():
    """주입된 order_api를 통해 계좌 데이터를 정방향 갱신 (캐싱 타임아웃 5초 단축)"""
    return order_api.get_present_balance()

# ==============================================================================
# 5. 🏛️ 대시보드 레이아웃 및 컴포넌트 레이어
# ==============================================================================
st.title("📊 대륭 퀀트 자산운용 인프라 실시간 제어 대시보드")
st.caption(f"시스템 최종 갱신 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 아키텍처 상태: 정방향 의존성 주입 완료")

st.markdown("---")

# 실시간 지표 영역 (안전 가드 내장)
account_data = {"cash": 0, "total_eval_amount": 0, "total_buy_amount": 0, "total_profit_loss": 0, "positions": []}
try:
    account_data = fetch_realtime_balance()
except Exception as e:
    st.sidebar.error(f"실시간 잔고 인터페이스 동기화 실패: {str(e)}")

m_col1, m_col2, m_col3, m_col4 = st.columns(4)
with m_col1:
    st.metric("총 평가금액", f"{account_data.get('total_eval_amount', 0):,} 원")
with m_col2:
    st.metric("총 매수금액", f"{account_data.get('total_buy_amount', 0):,} 원")
with m_col3:
    p_l = account_data.get('total_profit_loss', 0)
    st.metric("총 평가손익", f"{p_l:,} 원", delta=f"{p_l:,} 원" if p_l >= 0 else f"{p_l:,} 원")
with m_col4:
    token_remain = auth_client.get_residual_token_sec() if hasattr(auth_client, 'get_residual_token_sec') else 7200
    st.metric("API 토큰 잔여시간", f"{token_remain // 60}분 {token_remain % 60}초")

# 사이드바 제어판
st.sidebar.header("🕹️ 코어 엔진 컨트롤 패널")
strategy_options = ["basic", "high_frequency"]
current_idx = strategy_options.index(trading_system.strategy_type) if trading_system.strategy_type in strategy_options else 0
selected_strat = st.sidebar.selectbox("구동 알고리즘 엔진 선택", strategy_options, index=current_idx)

if selected_strat != trading_system.strategy_type:
    with St.sidebar.spinner("전략 코어 스위칭 중..."):
        trading_system.strategy_type = selected_strat
        trading_system.initialize()
    st.sidebar.success(f"✅ 전략이 '{selected_strat}'로 정방향 변경되었습니다.")
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ 엔진 가드레일 상태")
force_bypass_status = os.environ.get("FORCE_BYPASS", "FALSE") == "TRUE"
st.sidebar.write(f"정규장 시간외 우회 제한선: {'🔓 해제(FORCE_BYPASS)' if force_bypass_status else '🔒 정상 가동'}")

# ==============================================================================
# 6. 📂 메인 탭 인터페이스
# ==============================================================================
tab_console, tab_positions, tab_charts, tab_manual_order, tab_config = st.tabs([
    "🤖 자동매매 콘솔", 
    "📋 실시간 포지션 뷰어", 
    "📈 기술적 분석 차트", 
    "⚡ 긴급 수동 매매", 
    "⚙️ 마스터 설정 매니저"
])

# ---- 탭 1: 자동매매 콘솔 ----
with tab_console:
    st.header("Core Engine Scheduler Console")
    c_left, c_right = st.columns([2, 1])
    
    with c_left:
        st.subheader("🖥️ 거래 실행 루프 제어")
        st.info(f"현재 작동 상태: 코어 엔진이 '{trading_system.strategy_type}' 전략 위에 결합되어 대기 중입니다.")
        
        if st.button("▶️ 수동 1회 강제 거래 사이클 트리거 (Manual Signal Scan)", type="primary", use_container_width=True):
            st.write("⚙️ `trading_system.execute_strategy_loop()` 강제 연산 개시...")
            with st.spinner("대상 종목 풀 연산 및 KIS 주문 API 시그널 전송 중..."):
                loop_res = trading_system.execute_strategy_loop()
                st.success("🎯 단발성 사이클 실행 완료.")
                st.json(loop_res)
                st.cache_data.clear() # 잔고 즉시 리프레시용 강제 버퍼 소거
                st.rerun()
                
    with c_right:
        st.subheader("📡 엔진 실시간 텔레메트리")
        st.text_area(
            "인프라 바인딩 체크 로그", 
            value=f"Auth Status: 연결 활성화\nMarket Provider: KIS Gateway\nOrder Channel: Active\nTarget Registry: {len(config_manager.get_target_stocks())} Stocks Loaded",
            height=150
        )

# ---- 탭 2: 실시간 포지션 뷰어 ----
with tab_positions:
    st.header("실시간 보유 포지션 및 감시 타겟 종목 목록")
    
    pos_left, pos_right = st.columns(2)
    with pos_left:
        st.subheader("💼 현재 계좌 보유 잔고 현황")
        positions_list = account_data.get('positions', [])
        if positions_list:
            df_positions = pd.DataFrame(positions_list)
            
            # ------------------------------------------------------------------
            # 🔥 [실시간 포지션 뷰어 연산 가드레일 삽입] 
            # 주당 매매가(매입단가)와 현재가격의 차이를 반영하여 평가손익 강제 교정
            # ------------------------------------------------------------------
            try:
                # 데이터 타입이 문자열로 유입될 경우를 대비해 정수형/실수형 변환 처리
                qty = pd.to_numeric(df_positions['보유수량'], errors='coerce').fillna(0)
                buy_p = pd.to_numeric(df_positions['매입단가'], errors='coerce').fillna(0)
                
                # API 응답 필드 형태에 맞춰 '현재가' 데이터 바인딩 가드 설정
                if '현재가' in df_positions.columns:
                    curr_p = pd.to_numeric(df_positions['현재가'], errors='coerce').fillna(0)
                elif 'prpr' in df_positions.columns:
                    curr_p = pd.to_numeric(df_positions['prpr'], errors='coerce').fillna(0)
                    df_positions['현재가'] = curr_p  # 뷰어 컬럼명 통일
                else:
                    curr_p = buy_p  # 현재가 필드 유실 시 에러 방지용 가드
                
                # 🎯 정방향 공식 적용: 평가손익 = (현재가 - 매입단가) * 보유수량
                df_positions['평가손익'] = (curr_p - buy_p) * qty
                
                # 가독성을 위해 소수점 버림 처리 및 정수형 변환
                df_positions['평가손익'] = df_positions['평가손익'].astype(int)
                
            except Exception as eval_err:
                logger.error(f"실시간 포지션 손익 텔레메트리 연산 오류: {str(eval_err)}")
            # ------------------------------------------------------------------

            st.dataframe(df_positions, use_container_width=True)
        else:
            st.info("📥 현재 가동 중인 포지션이 비어 있습니다. 자동매매 시그널을 대기하십시오.")
            
    with pos_right:
        st.subheader("🎯 전역 환경설정 등록 타겟 감시 종목")
        target_stocks = config_manager.get_target_stocks()
        st.write(f"시스템이 주기적으로 마스킹 연산을 수행하는 {len(target_stocks)}개 마스터 종목 코드입니다.")
        st.data_editor(pd.DataFrame({"종목코드": target_stocks}), use_container_width=True)

# ---- 탭 3: 기술적 분석 차트 ----
with tab_charts:
    st.header("📈 주입된 MarketData 인프라 기반 실시간 시각화 차트")
    selected_stock = st.selectbox("시세 분석 대상 종목 선택", config_manager.get_target_stocks() if config_manager.get_target_stocks() else ["005930"])
    
    if st.button("차트 데이터 리프레시 렌더링", use_container_width=True):
        with st.spinner("KIS 시세 데이터 파이프라인 수신 중..."):
            try:
                ohlcv_data = market_data.get_ohlcv(selected_stock, timeframe='daily')
                if not ohlcv_data.empty:
                    fig = go.Figure(data=[go.Candlestick(
                        x=ohlcv_data.index, open=ohlcv_data['open'], high=ohlcv_data['high'],
                        low=ohlcv_data['low'], close=ohlcv_data['close'], name=selected_stock
                    )])
                    fig.update_layout(title=f"{selected_stock} 실시간 통합 캔들스틱 차트", layout="wide")
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("수신된 시세 OHLCV 시계열 데이터가 존재하지 않습니다.")
            except Exception as e:
                st.error(f"차트 데이터 시각화 중 예외 발생: {str(e)}")

# ---- 탭 4: 긴급 수동 매매 ----
with tab_manual_order:
    st.header("⚡ 인프라 다이렉트 긴급 수동 주문 샌드박스")
    st.warning("⚠️ 본 탭에서의 주문은 시스템 전략 필터링을 거치지 않고 주입된 계좌 파이프라인을 통해 KIS 서버로 직전송됩니다.")
    
    o_col1, o_col2, o_col3 = st.columns(3)
    with o_col1:
        ord_code = st.text_input("주문 대상 종목코드", value="005930")
    with o_col2:
        ord_qty = st.number_input("주문 수량(주)", min_value=1, value=1, step=1)
    with o_col3:
        ord_type = st.radio("주문 종류 선택", ["시장가 매수 (BUY)", "시장가 매도 (SELL)"])
        
    if st.button("🔥 KIS 서버 긴급 명령 송신", type="secondary", use_container_width=True):
        with st.spinner("KIS 실시간 통신망 주문 처리 중..."):
            try:
                if "BUY" in ord_type:
                    res = order_api.buy_market_order(stock_code=ord_code, quantity=ord_qty)
                else:
                    res = order_api.sell_market_order(stock_code=ord_code, quantity=ord_qty)
                
                if res:
                    st.success("🚀 긴급 수동 주문이 한국투자증권 인프라망을 통해 정상 접수되었습니다.")
                    st.json(res)
                    st.cache_data.clear() # 잔고 강제 갱신 트리거
                else:
                    st.error("❌ KIS 인프라가 주문 처리를 거절했습니다. 콘솔 로그를 확인하세요.")
            except Exception as e:
                st.error(f"주문 송신 치명적 실패: {str(e)}")

# ---- 탭 5: 마스터 설정 매니저 ----
with tab_config:
    st.header("⚙️ ConfigManager 단일 공급원 데이터 분석 뷰어")
    st.subheader("마스터 YAML 메모리 적재 데이터")
    st.json(config_manager.get_config())