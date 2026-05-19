import os
import sys
import time
import logging
import schedule
from datetime import datetime
from src.strategy.strategy_factory import StrategyFactory

logger = logging.getLogger(__name__)

class TradingSystem:
    def __init__(self, auth_client, market_data, order_api, config_manager, strategy_type="basic"):
        """
        [원칙 기반 통합 설계] 의존성 주입(Dependency Injection) 아키텍처 일원화
        
        기존의 실시간 스케줄링 비즈니스 로직과 가드레일 기능을 완벽히 유지하되,
        인프라 객체(Auth, Market, Order, Config)의 생성 제어권만 상위 레이어로 이관합니다.
        """
        # 1. 주입받은 인프라 레이어 인스턴스 단일 공급원 바인딩
        self.auth = auth_client
        self.market_data = market_data
        self.order_api = order_api
        self.config_manager = config_manager
        self.strategy_type = strategy_type
        
        # 2. 통합 설정 매니저로부터 데이터 동기화
        self.config = self.config_manager.get_config()
        self.target_stocks = self.config_manager.get_target_stocks()
        
        # 3. 전략 컨테이너 지연 로딩 필드
        self.strategy = None
        
        logger.info("⚙️ [통합 코어 엔진] 인프라 레이어 의존성 주입(DI) 완료 및 스케줄러 준비.")

    def initialize(self):
        """
        엔진 가동 전 전략 팩토리를 조립하고 최종 무결성을 검증합니다.
        """
        logger.info(f"🚀 [엔진 초기화] '{self.strategy_type}' 전략 파이프라인 조립을 시작합니다.")
        
        # [엔진 가드레일] 시간 및 우회 환경변수 동기화 확인
        force_bypass = os.environ.get("FORCE_BYPASS", "FALSE").upper() == "TRUE"
        if force_bypass:
            logger.warning("⚠️ [엔진 가드레일] FORCE_BYPASS 활성화 상태가 확인되었습니다. 시간 제한 차단선이 해제됩니다.")
            
        # 팩토리를 통해 전략 인스턴스 생성 (주입받은 인프라 전달)
        self.strategy = StrategyFactory.create_strategy(
            strategy_type=self.strategy_type,
            market_data=self.market_data,
            order_api=self.order_api,
            config=self.config
        )
        
        if not self.strategy:
            raise RuntimeError(f"❌ 전략 인스턴스 생성 실패: {self.strategy_type}")
            
        logger.info(f"✅ Trading system initialized successfully. 활성화된 전략: {self.strategy_type}")

    def trading_job(self):
        """
        스케줄러에 의해 주기적으로 무한루프 안에서 호출되는 핵심 거래 작업 매커니즘
        """
        logger.info("==================================================")
        logger.info("🔄 [스케줄 루프] 거래 작업(Trading Job) 기동")
        logger.info("==================================================")
        
        if not self.strategy:
            logger.error("❌ [코어 에러] 시스템이 초기화되지 않은 상태에서 작업이 호출되었습니다.")
            return

        # 시간대 가드레일 검증 (Bypass가 켜져있지 않다면 정규장 준수)
        if not self._is_trading_time():
            logger.info("🕒 현재는 정규 거래 시간(09:00~15:30)이 아닙니다. 스케줄 루프를 안전하게 스킵합니다.")
            return

        try:
            # 1. 한국투자증권 서버로부터 실시간 보유 잔고 및 포지션 동기화
            logger.info("📥 실시간 포지션 및 계좌 잔고 동기화 중...")
            current_positions = self.order_api.get_present_balance()
            
            # 2. 타겟 종목(4개 종목 등) 스캔 및 매매 시그널 연산/주문 실행 일임
            logger.info(f"🔍 대상 종목({len(self.target_stocks)}개) 시세 마스킹 및 전략 시그널 연산 시작...")
            results = self.strategy.check_and_execute(self.target_stocks, current_positions)
            
            # 3. 루프 결과 정산 및 추적성 로그 확보
            buys_count = len(results.get('buys', []))
            sells_count = len(results.get('sells', []))
            logger.info(f"📊 [루프 실행 완료] 당해 사이클 정산 -> 매수 체결 요청: {buys_count}건, 매도 체결 요청: {sells_count}건")
            
        except Exception as e:
            logger.error(f"🚨 [코어 엔진 런타임 에러] 매매 루프 실행 중 예외 발생: {str(e)}", exc_info=True)

    # ==================================================================
    # 🤝 [대시보드 강제 트리거 연동 브릿지] 
    # ==================================================================
    def execute_strategy_loop(self):
        """
        스트림릿 대시보드의 '수동 1회 강제 거래 사이클 트리거' 연동 인터페이스 프로토콜.
        대시보드가 요구하는 명칭을 코어의 핵심 로직인 trading_job으로 안전하게 바인딩합니다.
        """
        logger.info("⚡ [대시보드 수동 명령] 외부 프론트엔드로부터 강제 연산 명령이 수신되었습니다.")
        return self.trading_job()

    def run_scheduler(self):
        """
        기존 main.py와 데몬 모드에 존재하던 무한 스케줄러 루프를 코어 엔진 내부로 통합 내재화합니다.
        진입점(run.py)은 이 메서드만 단발성으로 호출하면 안전하게 무한 대기열로 진입합니다.
        """
        # 설정 파일에서 스캔 주기(분) 확보 (기본값 1분)
        strategy_config = self.config.get(self.strategy_type, self.config.get('trading', {}))
        interval_minutes = strategy_config.get('scan_interval', 1)
        
        logger.info(f"📅 [스케줄러 등록] {interval_minutes}분 간격으로 자동매매 루프를 배치합니다.")
        
        # schedule 라이브러리 연동
        schedule.clear() # 중복 방지 정화
        schedule.every(interval_minutes).minutes.do(self.trading_job)
        
        # 최초 기동 시 대기하지 않고 즉시 1회 우선 실행 (테스트 및 완결성 검증 가속화)
        self.trading_job()
        
        logger.info("🚀 스케줄 작업 실행 중... 루프 데몬 가동 완료.")
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.warning("👋 사용자에 의해 자동매매 엔진 스케줄러가 안전하게 종료되었습니다.")
        except Exception as e:
            logger.critical(f"💀 [🔥 엔진 셧다운] 스케줄러 루프가 치명적인 오류로 붕괴되었습니다: {str(e)}", exc_info=True)

    def _is_trading_time(self):
        """
        현재 장 운영 시간 여부를 판단하는 가드레일 함수
        """
        if os.environ.get("FORCE_BYPASS", "FALSE").upper() == "TRUE":
            return True
            
        now = datetime.now()
        if now.weekday() >= 5:  # 토, 일 스킵
            return False
            
        current_time = now.strftime("%H:%M")
        return "09:00" <= current_time <= "15:30"