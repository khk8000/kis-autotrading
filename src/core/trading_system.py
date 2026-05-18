import os
import sys
import yaml
import json
import logging
import threading
import time
from datetime import datetime, timedelta
import glob
import importlib

# 기존 도메인 모듈 및 유틸 임포트 원본 보존
from src.strategy.strategy_factory import StrategyFactory
from src.ml.model import StockPredictionModel
from src.ml.training import train_model
from src.utils.data_utils import calculate_moving_average, calculate_rsi, calculate_bollinger_bands

logger = logging.getLogger(__name__)

class TradingSystem:
    """자동매매 시스템 래퍼 클래스
    
    이 클래스는 자동 주식 거래 시스템의 중앙 컨트롤러 역할을 합니다.
    최상단 진입점(start.py)에서 검증이 끝난 무결한 객체들을 주입받아 연동 구동됩니다.
    """
    
    def __init__(self, auth_client, market_data, order_api, config_manager, strategy_type="basic"):
        """시스템 초기화 및 의존성 주입"""
        # 로그 파일 경로 설정 및 초기화
        log_file = 'logs/trading_system.log'
        self.setup_logger(log_file)
        
        logger.info("Trading system initializing...")
        
        # 단일 공급원(Single Source of Truth)으로부터 객체 바인딩
        self.auth = auth_client
        self.market_data = market_data
        self.order_api = order_api
        self.config_manager = config_manager
        self.strategy_type = strategy_type
        
        # [인프라 정류] sys.argv 가로채기 방식 타파 -> 상위 start.py가 가공해준 OS 전역 플래그 참조
        self.force_bypass = os.environ.get("FORCE_BYPASS") == "True"
        if self.force_bypass:
            logger.warning("⚠️ [엔진 가드레일] FORCE_BYPASS 활성화 상태가 확인되었습니다. 시간 제한 차단선이 해제됩니다.")
        
        # 상태 제어 및 백그라운드 스레드 자원 초기화
        self.is_running = False
        self.trading_thread = None
        
        # 종목 및 데이터 실시간 캐시 원본 유지
        self.target_stocks = config_manager.load_target_stocks()
        self.current_data = {}
        self.account_info = {}
        
        # ML 모델 파이프라인 가동 (순정 기능 보존)
        self.ml_model = None
        self._load_or_train_model()
        
        # 전략 팩토리를 통한 결합 연동
        self.strategy = None
        self._create_strategy(strategy_type)
        
        logger.info("Trading system initialized successfully")
    
    def setup_logger(self, log_file):
        """로거 설정 (기존 순정 로직 100% 유지)"""
        log_dir = os.path.dirname(os.path.abspath(log_file))
        os.makedirs(log_dir, exist_ok=True)
        
        global logger
        logger = logging.getLogger(__name__)
        logger.setLevel(logging.INFO)
        
        if logger.hasHandlers():
            logger.handlers.clear()
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)
    
    def _create_strategy(self, strategy_type):
        """전략 팩토리를 이용한 하부 전략 빌드"""
        self.strategy = StrategyFactory.create_strategy(
            strategy_type=strategy_type, 
            market_data=self.market_data, 
            order_api=self.order_api, 
            config_manager=self.config_manager,
            ml_model=self.ml_model
        )
        logger.info(f"Strategy instance loaded: {strategy_type}")
    
    def _load_or_train_model(self):
        """ML 모델 로드 또는 학습 (기존 로직 보존)"""
        model = StockPredictionModel()
        try:
            model_files = glob.glob(os.path.join("models", "stock_model_*.pkl"))
            if model_files:
                latest_model = max(model_files)
                model.load(os.path.basename(latest_model))
                logger.info(f"ML 모델 로드됨: {latest_model}")
                self.ml_model = model
            else:
                logger.info("기존 모델이 없습니다. 새로운 모델을 학습합니다.")
                self.ml_model = train_model(self.market_data, self.target_stocks, days=300)
        except Exception as e:
            logger.error(f"ML 모델 로드/학습 실패: {str(e)}")
    
    def start(self):
        """매매 자동화 백그라운드 엔진 가동"""
        if self.is_running:
            logger.warning("거래 시스템이 이미 실행 중입니다.")
            return
        
        self.is_running = True
        self.trading_thread = threading.Thread(target=self._trading_loop)
        self.trading_thread.daemon = True
        self.trading_thread.start()
        logger.info("Trading system started (Thread launched)")
    
    def stop(self):
        """매매 자동화 엔진 정지 및 가드 소멸"""
        if not self.is_running:
            logger.warning("거래 시스템이 이미 중지되었습니다.")
            return
            
        self.is_running = False
        logger.info("Trading system stopping...")
        
        if self.trading_thread and self.trading_thread.is_alive():
            self.trading_thread.join(timeout=10)
            
        logger.info("Trading system stopped")
    
    def _trading_loop(self):
        """코어 엔진 매매 비즈니스 무한 루프 (기존 핵심 순정 스케줄러 보존)"""
        last_update_time = datetime.now()
        stock_update_interval = 10 * 60  # 10분마다 종목 갱신
        
        while self.is_running:
            try:
                # API 접근 토큰 수명 자동 검증 및 리프레시
                self.auth.get_access_token()
                
                # 거래 활성 시간 타임 가드 체크
                if self._is_trading_time():
                    current_time = datetime.now()
                    
                    # 주기적 타겟 종목 갱신 결합 파트
                    if (current_time - last_update_time).total_seconds() > stock_update_interval:
                        logger.info("주기적 종목 리스트 갱신 시작")
                        if hasattr(self.strategy, 'weekly_update'):
                            self.strategy.weekly_update()
                            if hasattr(self.strategy, 'selected_stocks'):
                                self.target_stocks = self.strategy.selected_stocks
                                self.config_manager.save_target_stocks(self.target_stocks)
                        logger.info(f"종목 리스트 갱신 완료: {len(self.target_stocks)}개 종목")
                        last_update_time = current_time
                    
                    # 매매 파이프라인에 투입할 종목 확정
                    stocks_to_use = []
                    if hasattr(self.strategy, 'selected_stocks') and self.strategy.selected_stocks:
                        stocks_to_use = self.strategy.selected_stocks
                    elif self.target_stocks:
                        stocks_to_use = self.target_stocks
                    
                    if not stocks_to_use:
                        logger.warning("선정된 종목이 없습니다. 종목 선정을 시도합니다.")
                        if hasattr(self.strategy, 'weekly_update'):
                            self.strategy.weekly_update()
                            if hasattr(self.strategy, 'selected_stocks'):
                                stocks_to_use = self.strategy.selected_stocks
                                self.target_stocks = self.strategy.selected_stocks
                    
                    # 전략 가동 구동 및 라우팅
                    if stocks_to_use:
                        if self.strategy.__class__.__name__ == 'HighFrequencyStrategy':
                            logger.info("고빈도 트레이딩 전략 실행 중...")
                            results = self.strategy.run()
                        else:
                            logger.info(f"{len(stocks_to_use)}개 종목으로 전략 실행 중")
                            results = self.strategy.run(stocks_to_use)
                        
                        # 트랜잭션 기록 및 로깅 핸들러 연동
                        self._handle_trading_results(results)
                    else:
                        logger.warning("선정된 종목이 없어 전략을 실행할 수 없습니다.")
                    
                    # 실시간 대시보드 표출 데이터 동기화
                    self._update_cache()
                else:
                    logger.info("거래 시간이 아닙니다. 대기 중...")
                
                # 전략 특성 기반 대기 시간 가드레일 배정
                if self.strategy.__class__.__name__ == 'HighFrequencyStrategy':
                    time.sleep(60)
                else:
                    interval_minutes = self.config_manager.get_interval() if hasattr(self.config_manager, 'get_interval') else 15
                    time.sleep(interval_minutes * 60)
                
            except Exception as e:
                logger.error(f"매매 루프 치명적 오류: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                time.sleep(60)
    
    def _handle_trading_results(self, results):
        """매수/매도 실행 트랙 레코드 출력 (원본 로직 완벽 보존)"""
        if not results:
            logger.warning("전략 실행 결과가 비어있습니다.")
            return
            
        buys_count = len(results.get('buys', []))
        sells_count = len(results.get('sells', []))
        errors_count = len(results.get('errors', []))
        
        logger.info(f"매수: {buys_count}건, 매도: {sells_count}건, 오류: {errors_count}건")
        
        if buys_count > 0:
            for buy in results['buys']:
                logger.info(f"매수 실행: {buy['stock_code']} - {buy.get('reason', '신호 없음')}")
        
        if sells_count > 0:
            for sell in results['sells']:
                logger.info(f"매도 실행: {sell['stock_code']} - {sell.get('reason', '신호 없음')}")
        
        if errors_count > 0:
            for error in results['errors']:
                logger.error(f"오류 발생: {error.get('stock_code', 'N/A')} - {error.get('error', '알 수 없는 오류')}")
    
    def _is_trading_time(self):
        """정규 매매 거래 시간 가드 판단 메커니즘"""
        if getattr(self, 'force_bypass', False):
            return True
            
        now = datetime.now()
        if now.weekday() >= 5:  # 주말 가드 차단
            return False
        
        market_open = now.replace(hour=9, minute=0, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return market_open <= now <= market_close
    
    def _update_cache(self):
        """웹 프론트 연동 데이터 로컬 실시간 캐싱"""
        try:
            account_data = self.market_data.get_account_balance()
            if account_data:
                logger.debug(f"계좌 정보 API 응답 수신 성공")
                self.account_info = account_data
            else:
                logger.warning("계좌 정보를 가져오지 못했습니다.")
            
            for stock_code in self.target_stocks:
                data = self.market_data.get_stock_current_price(stock_code)
                if data:
                    self.current_data[stock_code] = data
        except Exception as e:
            logger.error(f"캐시 메모리 동기화 중 오류: {str(e)}")
    
    def get_current_stock_data(self):
        """현재 종목 데이터 반환"""
        if not self.current_data:
            self._update_cache()
        return self.current_data
    
    def get_account_info(self):
        """더미 데이터 표출 메커니즘을 결합한 다목적 계좌 정보 피드백"""
        try:
            if not self.account_info:
                self._update_cache()

            if not self._is_trading_time() and not getattr(self, 'force_bypass', False) and not self.account_info:
                dummy_data = {
                    'account_summary': [{
                        'dnca_tot_amt': '500000',
                        'scts_evlu_amt': '500000',
                        'tot_evlu_amt': '1000000',
                        'pchs_amt_smtl_amt': '450000',
                        'evlu_pfls_smtl_amt': '50000',
                        'asst_icdc_erng_rt': '10.00'
                    }],
                    'stocks': []
                }
                return dummy_data
            
            result = {'account_summary': [], 'stocks': []}
            if (self.account_info and 'account_summary' in self.account_info 
                and not self.account_info['account_summary'] 
                and 'stocks' in self.account_info 
                and len(self.account_info['stocks']) > 0):
                account_summary_item = self.account_info['stocks'][0].copy()
                result['account_summary'] = [account_summary_item]
                if len(self.account_info['stocks']) > 1:
                    result['stocks'] = self.account_info['stocks'][1:]
            else:
                result = self.account_info
            
            if result and 'stocks' in result:
                for stock in result['stocks']:
                    if 'prpr' not in stock and 'pdno' in stock and stock.get('pdno') in self.current_data:
                        current_stock = self.current_data[stock['pdno']]
                        stock['prpr'] = current_stock.get('stck_prpr', '0')
                        stock['prdt_name'] = current_stock.get('prdt_name', '알 수 없음')
            return result
        except Exception as e:
            logger.error(f"계좌 정보 조회 장애 발생: {str(e)}")
            return {'account_summary': [], 'stocks': []}
    
    def get_strategy_config(self):
        return self.strategy.config if hasattr(self.strategy, 'config') else {}
    
    def update_strategy_config(self, config_updates):
        try:
            if hasattr(self.strategy, 'config'):
                for key, value in config_updates.items():
                    self.strategy.config[key] = value
                success = self.config_manager.update_strategy_config(self.strategy.config)
                if success: logger.info("전략 설정 정보 수정 및 디스크 동기화 완료.")
                return success
            return False
        except Exception as e:
            logger.error(f"전략 설정 동적 튜닝 실패: {str(e)}")
            return False
    
    def get_target_stocks(self):
        return self.target_stocks
    
    def update_target_stocks(self, stocks):
        try:
            self.target_stocks = stocks
            success = self.config_manager.save_target_stocks(stocks)
            return success
        except Exception as e:
            logger.error(f"대상 종목 커스텀 업데이트 실패: {str(e)}")
            return False
    
    def get_status(self):
        if self.is_running:
            return "running" if self._is_trading_time() else "waiting"
        return "stopped"
    
    def get_recent_logs(self, count=10):
        try:
            with open('logs/trading_system.log', 'r', encoding='utf-8') as f:
                logs = f.readlines()
            return logs[-count:] if count < len(logs) else logs
        except Exception:
            return []
    
    def get_stock_detail(self, stock_code, days=30):
        try:
            df = self.market_data.get_stock_daily_price(stock_code, period=days)
            if df.empty: return {'error': '데이터가 존재하지 않습니다.'}
            df = calculate_moving_average(df)
            df = calculate_rsi(df)
            df = calculate_bollinger_bands(df)
            df['date'] = df['stck_bsop_date'].dt.strftime('%Y-%m-%d')
            
            analysis = self.strategy.analyze_stock(stock_code) if hasattr(self.strategy, 'analyze_stock') else {}
            return {
                'code': stock_code,
                'data': df.to_dict('records'),
                'analysis': analysis,
                'current': self.current_data.get(stock_code, {})
            }
        except Exception as e:
            return {'error': str(e)}
    
    def retrain_model(self):
        try:
            self.ml_model = train_model(self.market_data, self.target_stocks, days=300)
            return True
        except Exception:
            return False
    
    def get_ml_model_info(self):
        if not self.ml_model or not hasattr(self.ml_model, 'get_model_info'):
            return {
                'model_type': 'None', 'last_training': 'Not available', 'accuracy': 0.0, 'f1_score': 0.0,
                'feature_importance': {'labels': ['RSI', '볼린저밴드', 'MACD', '이동평균', '거래량'], 'values': [0.2, 0.2, 0.2, 0.2, 0.2]},
                'performance_history': {'dates': [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(5, 0, -1)], 'accuracy': [0.65, 0.66, 0.67, 0.68, 0.69], 'f1_score': [0.62, 0.63, 0.64, 0.65, 0.66]}
            }
        try:
            return self.ml_model.get_model_info()
        except Exception:
            return {'model_type': 'Error', 'accuracy': 0.0}
            
    def save_selected_stocks_history(self, stocks_info):
        try:
            history_dir = "history"
            os.makedirs(history_dir, exist_ok=True)
            today = datetime.now().strftime('%Y%m%d')
            history_file = os.path.join(history_dir, f"selected_stocks_{today}.csv")
            
            with open(history_file, 'w', encoding='utf-8') as f:
                f.write("선정일자,종목코드,종목명,선정점수\n")
                for stock in stocks_info:
                    f.write(f"{stock.get('selected_date', today)},{stock.get('code', '')},{stock.get('name', '')},{stock.get('score', '') or ''}\n")
            return True
        except Exception:
            return False