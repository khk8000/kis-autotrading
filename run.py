#!/usr/bin/env python
"""
[원칙 기반 통합 설계] 자동 주식 거래 시스템 최상위 부트스트래퍼 (Bootstrapper)

본 스크립트는 시스템이 CLI, Web, 데몬 중 어떤 모드로 실행되든 간에
환경변수를 정화하고, 인프라 레이어 객체(Auth, Market, Order, Config)를 정방향으로 조립하여
코어 엔진(TradingSystem)에 완벽하게 의존성을 주입(DI)하는 단일 진입점입니다.
"""

import argparse
import os
import sys
import logging
from datetime import datetime

# ==============================================================================
# [원칙 기반 정화] 구글 코랩 환경 자동 감지 및 인프라 환경변수 일괄 바인딩
# ==============================================================================
try:
    from google.colab import userdata
    try:
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
                
            print("🔒 [인프라 브릿지] 구글 코랩 Secrets 데이터를 OS 표준 환경변수로 자동 동기화했습니다.")
    except AttributeError:
        pass
except ImportError:
    pass

# ==============================================================================
# [통합 환경 설계] 프로젝트 내부 모듈 정방향 참조 구조 이식
# ==============================================================================
from src.core.config import ConfigManager
from src.api.auth import KoreaInvestmentAuth
from src.api.market_data import MarketData
from src.api.order import OrderAPI
from src.core.trading_system import TradingSystem
from src.modes.cli_mode import run_cli_mode
from src.modes.web_mode import run_web_mode

def setup_global_logging():
    """땜질식 로그 추적을 배제하고, 전역 추적성을 확보하기 위한 표준 로깅 설계"""
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
        
    log_filename = f"{log_dir}/trading_{datetime.now().strftime('%Y%m%d')}.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger("root")

def main():
    # 1. 전역 로깅 인프라 가동
    logger = setup_global_logging()
    logger.info("==================================================")
    logger.info("🚀 [부트스트랩] 자동매매 인프라 레이어 빌드를 시작합니다.")
    logger.info("==================================================")

    # 2. 명령행 인자(Arguments) 파싱 인터페이스 정의
    parser = argparse.ArgumentParser(description="한국투자증권 자동 주식 거래 시스템 진입점")
    parser.add_name = "run.py"
    parser.add_argument('mode', choices=['cli', 'web', 'daemon'], default='cli', nargs='?',
                        help='실행 모드: cli(명령행), web(스트림릿), daemon(백그라운드)')
    parser.add_argument('--strategy-type', choices=['basic', 'high_frequency'], default='basic',
                        help='활성화할 알고리즘 전략 유형 지정')
    parser.add_argument('--force', action='store_true',
                        help='⚠️ [엔진 가드레일 우회] FORCE_BYPASS 환경변수를 강제 활성화합니다.')
    args = parser.parse_args()

    # 3. 가드레일 우회 옵션 전역 환경변수 동기화
    if args.force:
        os.environ["FORCE_BYPASS"] = "TRUE"
        logger.warning("⚠️ [부트스트랩] 강제 실행 옵션(--force)으로 인해 전역 시간선 통제 장치가 무력화됩니다.")

    try:
        # ==============================================================================
        # 🔥 [의존성 주입 파이프라인] 상위 레이어에서 순차적으로 인프라 객체 조립
        # ==============================================================================
        logger.info("📦 1/4. 통합 환경설정 매니저(ConfigManager) 가동...")
        config_manager = ConfigManager(config_dir='config')
        
        logger.info("📦 2/4. 한국투자증권 인증 인프라(KoreaInvestmentAuth) 로드...")
        auth_client = KoreaInvestmentAuth(config_path='config/api_config.yaml')
        
        logger.info("📦 3/4. 시세 정보 게이트웨이(MarketData) 바인딩...")
        market_data = MarketData(auth_client=auth_client, mode='paper')
        
        logger.info("📦 4/4. 주문/계좌 관리 파이프라인(OrderAPI) 동기화...")
        # 계좌 정보는 가상 OS 레벨에 정화 배치된 표준 환경변수에서 상속 흡수
        account_no = os.environ.get("KIS_PAPER_ACC", "")
        order_api = OrderAPI(auth_client=auth_client, account_no=account_no, mode='paper')

        # ==============================================================================
        # 🤝 [의존성 주입 완료] 코어 엔진에 완성된 하위 인프라 인스턴스를 주입하여 단일화
        # ==============================================================================
        logger.info("⚙️ 인프라 조립 완료. 코어 엔진(TradingSystem)에 의존성을 일괄 주입합니다.")
        trading_system = TradingSystem(
            auth_client=auth_client,
            market_data=market_data,
            order_api=order_api,
            config_manager=config_manager,
            strategy_type=args.strategy_type
        )

        # ==============================================================================
        # 🛣️ [실행 컨테이너 분기] 조립된 코어 엔진을 각 모드 인터페이스로 정방향 전달
        # ==============================================================================
        if args.mode == 'cli':
            logger.info(f"💻 CLI 실행 컨테이너로 진입합니다. (선택 전략: {args.strategy_type})")
            # 2단계에서 정화된 코어 엔진의 내부 스케줄러 루프를 발동시킵니다.
            trading_system.initialize()
            trading_system.run_scheduler()
            
        elif args.mode == 'daemon':
            logger.info(f" Background 데몬(Daemon) 모드로 진입합니다. (선택 전략: {args.strategy_type})")
            # 데몬 모드 역시 CLI와 동일하게 무한 스케줄러 자율 루프를 기반으로 은닉 구동됩니다.
            trading_system.initialize()
            trading_system.run_scheduler()
            
        elif args.mode == 'web':
            logger.info("🌐 Web 대시보드 인프라 프레임워크 제어권을 구동합니다.")
            # 웹 모드는 Streamlit 컨테이너에 완벽히 조립된 시스템 인스턴스를 이관합니다.
            run_web_mode(trading_system, args)

    except Exception as e:
        logger.critical(f"💀 [🔥 시스템 붕괴] 최상위 부트스트래핑 단계에서 치명적 에러 발생: {str(e)}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    # 멀티프로세싱 가드레일 보존
    import multiprocessing
    multiprocessing.freeze_support()
    main()