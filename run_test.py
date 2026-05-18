#!/usr/bin/env python
"""
통합 기동 연동 검증용 파이프라인 (run_test.py)
- [인프라 전방위 시그니처 가드] Auth, MarketData, OrderAPI의 모든 생성자 파라미터 명세를 동적으로 분석하여 조립을 완결합니다.
"""

import os
import sys
import inspect
import logging

# =============================================================================
# [경로 극단적 정류 가드] 모든 하위 모듈 임포트 전에 파이썬 패스를 다층 구조로 완벽 고정합니다.
# =============================================================================
current_file_path = os.path.abspath(__file__)
project_root = os.path.dirname(current_file_path)

os.chdir(project_root)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from src.core.config import ConfigManager
    from src.core.trading_system import TradingSystem
    from src.api.auth import KoreaInvestmentAuth
    from src.api.market_data import MarketData
    from src.api.order import OrderAPI
except ModuleNotFoundError as e:
    print("\n❌ 모듈 임포트 실패. 파일 구조를 다시 확인하십시오.")
    raise e

def bootstrap_environment():
    """구글 코랩 환경 사전 감지 및 가상 OS 변수 바인딩"""
    try:
        from google.colab import userdata
        paper_key = userdata.get('KIS_PAPER_KEY')
        paper_sec = userdata.get('KIS_PAPER_SEC')
        paper_acc = userdata.get('KIS_PAPER_ACC')
        
        if paper_key and paper_sec:
            os.environ["KIS_API_KEY"] = paper_key
            os.environ["KIS_SECRET_KEY"] = paper_sec
            os.environ["KIS_PAPER_KEY"] = paper_key
            os.environ["KIS_PAPER_SEC"] = paper_sec
            if paper_acc:
                os.environ["KIS_PAPER_ACC"] = paper_acc
            print("🔒 [인프라 브릿지] 구글 코랩 Secrets 환경 바인딩을 완료했습니다.")
    except (ImportError, AttributeError):
        pass

def extract_config_value(config_manager, key, default=None):
    """ConfigManager 객체 내부에서 실제 설정 딕셔너리 원본을 안전하게 역추적하여 파싱합니다."""
    if hasattr(config_manager, 'get'):
        try:
            return config_manager.get(key, default)
        except Exception:
            pass

    for attr_name in ['api_config', 'trading_config', 'config', '_config']:
        if hasattr(config_manager, attr_name):
            attr = getattr(config_manager, attr_name)
            if isinstance(attr, dict):
                return attr.get(key, default)
    
    return default

def build_auth_client(config_dir):
    """KoreaInvestmentAuth 생성자의 순정 시그니처에 맞춰 안전하게 인스턴스를 빌드합니다."""
    target_yaml = os.path.join(config_dir, "api_config.yaml")
    sig = inspect.signature(KoreaInvestmentAuth.__init__)
    params = list(sig.parameters.keys())
    
    if 'config_path' in params:
        return KoreaInvestmentAuth(config_path=target_yaml)
        
    kwargs = {}
    if 'api_key' in params: kwargs['api_key'] = os.environ.get("KIS_API_KEY")
    elif 'key' in params: kwargs['key'] = os.environ.get("KIS_API_KEY")
    if 'secret_key' in params: kwargs['secret_key'] = os.environ.get("KIS_SECRET_KEY")
    elif 'secret' in params: kwargs['secret'] = os.environ.get("KIS_SECRET_KEY")
    if 'mode' in params: kwargs['mode'] = os.environ.get("RUN_MODE", "paper")
    
    if kwargs:
        return KoreaInvestmentAuth(**kwargs)
    return KoreaInvestmentAuth(target_yaml)

def build_market_data(auth_client, run_mode):
    """MarketData 생성자의 파라미터 명세를 동적으로 매칭하여 안전하게 객체를 생성합니다."""
    sig = inspect.signature(MarketData.__init__)
    params = list(sig.parameters.keys())
    
    kwargs = {}
    # 인증 객체 맵핑 가드
    if 'auth_client' in params: kwargs['auth_client'] = auth_client
    elif 'auth' in params: kwargs['auth'] = auth_client
    
    # 모드 맵핑 가드
    if 'mode' in params: kwargs['mode'] = run_mode
    
    if kwargs:
        return MarketData(**kwargs)
    # 키워드 바인딩 실패 시 위치 인자로 안전 폴백 시도
    return MarketData(auth_client, run_mode)

def build_order_api(auth_client, account_no, run_mode):
    """OrderAPI 생성자의 파라미터 명세를 동적으로 매칭하여 안전하게 객체를 생성합니다."""
    sig = inspect.signature(OrderAPI.__init__)
    params = list(sig.parameters.keys())
    
    kwargs = {}
    # 인증 객체 맵핑 가드
    if 'auth_client' in params: kwargs['auth_client'] = auth_client
    elif 'auth' in params: kwargs['auth'] = auth_client
    
    # 계좌 및 모드 맵핑 가드
    if 'account_no' in params: kwargs['account_no'] = account_no
    if 'mode' in params: kwargs['mode'] = run_mode
    
    if kwargs:
        return OrderAPI(**kwargs)
    # 위치 인자로 안전 폴백
    return OrderAPI(auth_client)

def run_integration_test():
    # 0. 환경 초기화
    bootstrap_environment()
    
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("IntegrationTest")
    
    logger.info("🧪 [통합 작동성 검증 시작] 1단계: 글로벌 설정 빌드 검사")
    
    config_dir = 'config'
    if not os.path.exists(config_dir):
        logger.error(f"❌ 설정 디렉토리({config_dir})가 누락되었습니다. 테스트를 종료합니다.")
        return
        
    config_manager = ConfigManager(config_dir)
    
    logger.info("🧪 [통합 작동성 검증] 2단계: 한국투자증권 인증 토큰 원본 키 검증")
    api_key = os.environ.get("KIS_API_KEY") or extract_config_value(config_manager, "KIS_API_KEY")
    secret_key = os.environ.get("KIS_SECRET_KEY") or extract_config_value(config_manager, "KIS_SECRET_KEY")
    account_no = os.environ.get("KIS_PAPER_ACC") or extract_config_value(config_manager, "KIS_ACCOUNT_NO")
    
    if not api_key or not secret_key:
        logger.error("❌ API 인증 키 원본 확보 실패. 환경변수나 yaml 명세를 확인하십시오.")
        return
        
    # 테스트 구동 중 시간 제한 차단선을 해제하기 위해 강제 우회 환경변동 값 세팅
    os.environ["FORCE_BYPASS"] = "True"
    
    logger.info("🧪 [통합 작동성 검증] 3단계: 정방향 의존성 체인 조립 단계 진입")
    try:
        run_mode = extract_config_value(config_manager, "RUN_MODE", "paper")
        os.environ["RUN_MODE"] = run_mode
        
        # 전체 인프라 클래스별 파라미터 동적 정류 파서 작동
        auth_client = build_auth_client(config_dir)
        market_data = build_market_data(auth_client, run_mode)
        order_api = build_order_api(auth_client, account_no, run_mode)
        
        logger.info("🧪 [통합 작동성 검증] 4단계: 전략 팩토리를 이용한 하부 엔진 장착")
        trading_system = TradingSystem(
            auth_client=auth_client,
            market_data=market_data,
            order_api=order_api,
            config_manager=config_manager,
            strategy_type='high_frequency'
        )
        
        logger.info("==========================================================================")
        logger.info(f"🔍 주입에 성공한 하부 전략 클래스명: {trading_system.strategy.__class__.__name__}")
        logger.info(f"🔍 로드 완료된 타겟 종목 목록: {trading_system.target_stocks}")
        logger.info("==========================================================================")
        
        logger.info("🎉 [결과: 대성공] 하부 모듈 꼬임 없이 모든 인프라 객체가 정방향으로 관통 및 생성되었습니다!")
        
    except Exception as e:
        logger.critical(f"💥 [결과: 실패] 조립 과정 중 예외가 발생했습니다. 원인: {str(e)}", exc_info=True)

if __name__ == "__main__":
    run_integration_test()