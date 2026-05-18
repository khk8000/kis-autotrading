# src/modes/cli_mode.py
import logging
import time

logger = logging.getLogger(__name__)

def run_cli_mode(trading_system, args):
    """
    CLI 실행 모드 컨테이너 (인자 가로채기 및 땜질식 리임포트 완전 제거)
    """
    logger.info("정방향 CLI 단발성/실시간 매매 루프에 진입합니다.")
    
    try:
        # 시스템 초기화 (마켓 데이터 세팅 및 API 연결 상태 점검)
        trading_system.initialize()
        
        if args.force:
            logger.info("⚠️ 강제 실행(--force) 옵션이 활성화되었습니다. 시장 시간 조건을 우회합니다.")
            
        # 실제 매매 사이클 실행 (기존 main.py 내부의 실행 코어 비즈니스 로직)
        while True:
            logger.info("🔄 [매매 루프 탐색 중] 전략 주기에 맞춰 거래 프로세스를 가동합니다.")
            
            # 주입받은 트레이딩 시스템의 코어 엔진 가동
            results = trading_system.execute_strategy_loop()
            
            logger.info(f"📊 루프 정산 결과 -> 매수: {len(results.get('buys', []))}건, 매도: {len(results.get('sells', []))}건")
            
            # 단발성 실행 옵션이 필요하다면 여기서 체크 후 탈출 (기존 --once 대응)
            # 여기서는 실시간 대기를 위해 기본 loop sleep을 보수적으로 부여
            time.sleep(60) 
            
    except KeyboardInterrupt:
        logger.info("🛑 사용자의 입력(Ctrl+C)에 의해 CLI 거래 루프를 안전하게 종료합니다.")
    except Exception as e:
        logger.error(f"🚨 CLI 실행 모드 내부 루프 중단 오류: {str(e)}", exc_info=True)