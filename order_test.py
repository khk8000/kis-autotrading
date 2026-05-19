#!/usr/bin/env python
"""
주문 및 체결 파이프라인 단독 구동 검증 스크립트 (order_test.py)
- [호가단위 규격 정류] KRX 호가단위(500원 틱)를 강제 주입하여 서버 거절을 원천 차단합니다.
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

    # [KRX 호가 단위 보정 가드레일 장착] 20만~50만원 구간은 500원 틱 제한 적용
    raw_target_price = int(current_price * 0.98)
    target_buy_price = (raw_target_price // 500) * 500 

    print("\n" + "="*60)
    confirm = input(f"⚠️ 실제로 [{run_mode}] 서버에 {ticker} 1주 지정가 매수 주문을 전송하시겠습니까? (y/n): ")
    if confirm.lower() != 'y':
        logger.info("❌ 사용자가 테스트를 취소했습니다.")
        return
    print("="*60 + "\n")
    
    logger.info(f"🚀 2단계: 지정가 매수 주문 전송 -> 정류 가격: {target_buy_price}원(500원 틱), 수량: 1주")
    try:
        buy_response = None
        if hasattr(order_api, 'place_order'):
            method = getattr(order_api, 'place_order')
            
            kwargs = {
                "stock_code": ticker,
                "order_type": "buy",          
                "quantity": 1,                
                "price": target_buy_price,    
                "order_division": "00"         
            }
            
            logger.info("⚙️ [인터페이스 호출] place_order() 정밀 틱 동기화 전송")
            buy_response = method(**kwargs)
                
        if buy_response:
            logger.info(f"🟢 매수 주문 전송 시도 완료.")
            logger.info(f"📝 한국투자증권 서버 반환 데이터 원본: {buy_response}")
        else:
            # 만약 내부에서 예외 처리를 먹고 None을 뱉었을 경우를 위해 가용성 로깅 유지
            logger.warning("⚠️ place_order가 정상 구조를 반환하지 않았습니다. 내부 로그 확인 필요.")
            return

    except Exception as e:
        logger.critical(f"💥 매수 주문 전송 중 예외 발생: {str(e)}", exc_info=True)
        return

    time.sleep(2) 
    logger.info("🚀 3단계: 후속 데이터 파이프라인 연동 검증")
    if hasattr(order_api, 'get_order_status'):
        try:
            status = order_api.get_order_status()
            logger.info(f"📋 주문 당일 대기열 조회 성공: {status}")
        except Exception as e:
            logger.warning(f"⚠️ 주문 상태 조회 중 오류: {e}")

if __name__ == "__main__":
    run_order_test()