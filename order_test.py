#!/usr/bin/env python
"""
주문 및 체결 파이프라인 단독 구동 검증 스크립트 (order_test.py)
- [한투 실전 데이터 구조 매핑] 서버 리턴 구조 확인에 따른 파싱 규칙 완전 동기화 버전
"""

import os
import sys
import time
import inspect
import logging

# [경로 정류] 프로젝트 루트 최우선 바인딩
current_file_path = os.path.abspath(__file__)
project_root = os.path.dirname(current_file_path)
os.chdir(project_root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from src.core.config import ConfigManager
    from src.api.auth import KoreaInvestmentAuth
    from src.api.order import OrderAPI
    from src.api.market_data import MarketData
except ModuleNotFoundError as e:
    print(f"❌ 모듈 로드 실패: {e}")
    sys.exit(1)

def bootstrap_environment():
    try:
        from google.colab import userdata
        for key in ['KIS_PAPER_KEY', 'KIS_PAPER_SEC', 'KIS_PAPER_ACC']:
            val = userdata.get(key)
            if val:
                os.environ[key.replace("PAPER_", "")] = val
                os.environ[key] = val
        print("🔒 [인프라 브릿지] 구글 코랩 Secrets 환경 변수 바인딩 완료.")
    except Exception:
        pass

def extract_config_value(config_manager, key, default=None):
    if hasattr(config_manager, 'get'):
        try: return config_manager.get(key, default)
        except Exception: pass
    for attr_name in ['api_config', 'trading_config', 'config', '_config']:
        if hasattr(config_manager, attr_name):
            attr = getattr(config_manager, attr_name)
            if isinstance(attr, dict): return attr.get(key, default)
    return default

def build_auth_client(config_dir):
    target_yaml = os.path.join(config_dir, "api_config.yaml")
    return KoreaInvestmentAuth(config_path=target_yaml) if 'config_path' in inspect.signature(KoreaInvestmentAuth.__init__).parameters else KoreaInvestmentAuth(target_yaml)

def build_market_data(auth_client, run_mode):
    sig = inspect.signature(MarketData.__init__)
    params = list(sig.parameters.keys())
    kwargs = {}
    if 'auth' in params: kwargs['auth'] = auth_client
    elif 'auth_client' in params: kwargs['auth_client'] = auth_client
    if 'mode' in params: kwargs['mode'] = run_mode
    try:
        if kwargs: return MarketData(**kwargs)
    except TypeError: pass
    return MarketData(auth_client)

def build_order_api(auth_client, account_no, run_mode):
    sig = inspect.signature(OrderAPI.__init__)
    params = list(sig.parameters.keys())
    kwargs = {}
    if 'auth' in params: kwargs['auth'] = auth_client
    elif 'auth_client' in params: kwargs['auth_client'] = auth_client
    if 'account_no' in params: kwargs['account_no'] = account_no
    if 'mode' in params: kwargs['mode'] = run_mode
    try:
        if kwargs: return OrderAPI(**kwargs)
    except TypeError: pass
    return OrderAPI(auth_client)

def run_order_test():
    bootstrap_environment()
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("OrderTest")
    
    logger.info("⚡ [주문 샌드박스 테스트 시작]")
    
    config_manager = ConfigManager('config')
    run_mode = os.environ.get("RUN_MODE") or extract_config_value(config_manager, "RUN_MODE", "paper")
    account_no = os.environ.get("KIS_PAPER_ACC") or extract_config_value(config_manager, "KIS_ACCOUNT_NO")
    
    auth_client = build_auth_client('config')
    market_data = build_market_data(auth_client, run_mode)
    order_api = build_order_api(auth_client, account_no, run_mode)
    
    ticker = "005930" 
    logger.info(f"🔍 1단계: 타겟 종목({ticker}) 현재가 데이터 조회 테스트")
    
    current_price = None
    try:
        res = market_data.get_stock_current_price(ticker)
        if isinstance(res, dict):
            # [정류 가드] 한투 리턴 데이터 원본의 루트 레벨 구조 완벽 추적 파싱
            current_price = res.get('stck_prpr') or res.get('output', {}).get('stck_prpr') or res.get('price')
        else:
            current_price = res
            
        if current_price:
            current_price = int(float(current_price))
        else:
            raise ValueError(f"원본 응답 구조 파싱 불가: {res}")
            
    except Exception as e:
        logger.error(f"❌ 현재가 조회 실패: {e}")
        return

    logger.info(f"📊 {ticker} 현재가 확보 성공: {current_price}원")

    print("\n" + "="*60)
    confirm = input(f"⚠️ 실제로 [{run_mode}] 서버에 {ticker} 1주 지정가 매수 주문을 전송하시겠습니까? (y/n): ")
    if confirm.lower() != 'y':
        logger.info("❌ 사용자가 테스트를 취소했습니다.")
        return
    print("="*60 + "\n")

    # 체결 방지를 위해 현재가 대비 2% 낮은 안전지대 매수 단가 산출
    target_buy_price = int(current_price * 0.98) 
    
    logger.info(f"🚀 2단계: 지정가 매수 주문 전송 -> 가격: {target_buy_price}원, 수량: 1주")
    try:
        buy_response = None
        for method_name in ['order_cash', 'buy_limit', 'buy', 'create_order']:
            if hasattr(order_api, method_name):
                method = getattr(order_api, method_name)
                logger.info(f"⚙️ [인터페이스 호출] {method_name}() 진입")
                
                # 매뉴얼 가이드 기반 대문자 및 문자열 안전 폴백
                if method_name == 'order_cash':
                    buy_response = method(code=ticker, qty="1", price=str(target_buy_price), order_type="00")
                else:
                    buy_response = method(ticker, 1, target_buy_price)
                break
                
        if buy_response:
            logger.info(f"🟢 매수 주문 전송 시도 완료.")
            logger.info(f"📝 한국투자증권 서버 반환 데이터 원본: {buy_response}")
        else:
            available_order_methods = [m for m in dir(order_api) if not m.startswith('_')]
            logger.error(f"❌ OrderAPI 내부에 가용한 주문 메서드가 없습니다. 목록: {available_order_methods}")
            return

    except Exception as e:
        logger.critical(f"💥 매수 주문 전송 중 예외 발생: {str(e)}", exc_info=True)
        return

    time.sleep(2) 
    logger.info("🚀 3단계: 후속 데이터 파이프라인 연동 검증")
    for method_name in ['get_account_balance', 'get_balance']:
        if hasattr(order_api, method_name):
            try:
                balance = getattr(order_api, method_name)()
                logger.info(f"💼 계좌 잔고 조회 성공 [{method_name}]: {balance}")
                break
            except Exception as e:
                logger.warning(f"⚠️ {method_name} 실행 중 오류: {e}")

if __name__ == "__main__":
    run_order_test()