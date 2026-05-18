#!/usr/bin/env python
"""
통합 자동 주식 거래 시스템 엔트리 포인트 (start.py)
- [독립환경구축] 구글 코랩 및 로컬 인프라 환경을 최상단에서 자동 감지하여 단일화합니다.
- [뗌질식 수정 금지] 하위 모듈로 내려가기 전 모든 의존성 객체를 빌드하여 주입합니다.
"""

import argparse
import os
import sys
import logging
from src.config.config_manager import ConfigManager
from src.core.trading_system import TradingSystem

# KIS(한국투자증권) 내부 인증 및 통신 레이어 모듈 임포트 (기존 프로젝트 구조 원본 반영)
from src.api.kis_auth import KoreaInvestmentAuth
from src.core.market_data import MarketData
from src.core.order_api import OrderAPI

logger = logging.getLogger(__name__)

def bootstrap_environment():
    """구글 코랩 환경 자동 감지 및 인프라 표준 환경변수 일괄 바인딩"""
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
            print("🔒 [인프라 브릿지] 구글 코랩 Secrets 데이터를 가상 OS 레벨 표준 환경변수로 바인딩했습니다.")
    except (ImportError, AttributeError):
        # 로컬 서버 또는 일반 리눅스 환경일 경우 패스
        pass

def parse_arguments():
    """프로젝트 전체에서 유일하게 실행 인자를 제어하는 파서"""
    parser = argparse.ArgumentParser(description='통합 자동 주식 거래 시스템')
    
    parser.add_argument('--mode', choices=['cli', 'web', 'daemon'], default='cli',
                        help='실행 모드 (cli: 명령행 루프, web: 웹 대시보드, daemon: 백그라운드 스레드)')
    parser.add_argument('--strategy-type', default='basic', 
                        help='전략 유형 (basic, day_trading, high_frequency, ml_high_frequency)')
    parser.add_argument('--config', default='config/api_config.yaml', 
                        help='글로벌 설정 및 API 명세 파일 경로')
    parser.add_argument('--force', action='store_true', 
                        help='시간 외 또는 조건 미달 시에도 거래 가드레일을 강제 바이패스')
    
    return parser.parse_args()

def main():
    # 1. 환경 분석 및 로깅 초기화
    bootstrap_environment()
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    args = parse_arguments()
    logger.info(f"🚀 [시스템 구동] 모드: {args.mode.upper()} | 전략 패키지: {args.strategy_type}")

    # 2. 강제 실행 플래그 전역 컨텍스트 바인딩
    if args.force:
        os.environ["FORCE_BYPASS"] = "True"
        logger.warning("⚠️ 전역 강제 바이패스 플래그가 설정되었습니다. 시장 외 시간 매매가 허용됩니다.")

    try:
        # 3. 설정 매니저 단일 원본 빌드
        config_manager = ConfigManager(args.config)
        
        # 4. 하위 모듈이 각자 각개격파로 만들던 KIS 커넥션 객체들을 여기서 딱 한 번 정방향으로 빌드
        # ConfigManager 혹은 OS 환경변수로부터 직접 원본 값을 파싱합니다.
        api_key = os.environ.get("KIS_API_KEY") or config_manager.get("KIS_API_KEY")
        secret_key = os.environ.get("KIS_SECRET_KEY") or config_manager.get("KIS_SECRET_KEY")
        account_no = os.environ.get("KIS_PAPER_ACC") or config_manager.get("KIS_ACCOUNT_NO")
        run_mode = config_manager.get("RUN_MODE", "paper")
        
        if not api_key or not secret_key:
            raise ValueError("KIS API 인증 키 원본 데이터가 누락되었습니다. 환경변수나 yaml 설정을 점검하십시오.")
            
        # 5. 순차적 의존성 결합 (인증 -> 마켓 -> 주문)
        auth_client = KoreaInvestmentAuth(api_key=api_key, secret_key=secret_key, mode=run_mode)
        market_data = MarketData(auth_client=auth_client, mode=run_mode)
        order_api = OrderAPI(auth_client=auth_client, account_no=account_no, mode=run_mode)
        
        # 6. 정화 완료된 TradingSystem에 무결한 원본 객체 통째로 주입 (Dependency Injection)
        trading_system = TradingSystem(
            auth_client=auth_client,
            market_data=market_data,
            order_api=order_api,
            config_manager=config_manager,
            strategy_type=args.strategy_type
        )
        
        # 7. 라우터 작동 (각 실행 모드에 완성된 엔진 수송)
        if args.mode == 'cli':
            logger.info("정방향 CLI 단발성/실시간 매매 엔진을 가동합니다.")
            # CLI 모드는 백그라운드 스레드를 틀 필요 없이 동기식 루프를 직접 호출하거나 start()를 사용합니다.
            trading_system.start()
            
            # 메인 스레드가 즉시 죽지 않도록 대기 및 제어 루프 유지
            try:
                while trading_system.is_running:
                    time.sleep(1)
            except KeyboardInterrupt:
                trading_system.stop()
                
        elif args.mode == 'web':
            logger.info("웹 대시보드 인프라 스트림을 기동합니다.")
            from src.modes.web_mode import run_web_mode
            run_web_mode(trading_system)
            
        elif args.mode == 'daemon':
            logger.info("백그라운드 데몬 서비스 상태로 진입합니다.")
            from src.modes.daemon_mode import run_daemon_mode
            run_daemon_mode(trading_system)
            
    except Exception as e:
        logger.critical(f"🔥 [치명적 결함] 최상단 부트스트랩 프로세스 붕괴: {str(e)}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()