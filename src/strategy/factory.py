import logging
import importlib

logger = logging.getLogger(__name__)

class StrategyFactory:
    """전략 팩토리 클래스
    
    상대 경로 오류를 원천 차단하기 위해 표준 패키지 임포트 아키텍처로 교정되었습니다.
    """
    
    @staticmethod
    def create_strategy(strategy_type, market_data, order_api, config=None, ml_model=None):
        """전략 생성
        
        Args:
            strategy_type (str): 전략 유형 ('basic', 'day_trading', 'high_frequency', 'ml_high_frequency')
            market_data (MarketData): 시장 데이터 객체
            order_api (OrderAPI): 주문 API 객체
            config (dict, optional): 전략 설정
            ml_model (object, optional): ML 모델 객체
            
        Returns:
            Strategy: 생성된 전략 객체
        """
        # 1. 기본 전략은 항상 안전하게 절대 경로로 로드
        from src.strategy.basic_strategy import BasicStrategy
        
        # 동적 로드할 전략 클래스 초기화
        DayTradingStrategy = None
        HighFrequencyStrategy = None
        MLHighFrequencyStrategy = None
        
        # 2. 표준 패키지 경로를 통해 동적 임포트 (상대 경로 에러 발생하지 않음)
        try:
            day_trading_module = importlib.import_module("src.strategy.day_trading_strategy")
            DayTradingStrategy = getattr(day_trading_module, "DayTradingStrategy", None)
        except ImportError:
            pass  # 파일이 없거나 임포트 실패 시 유연하게 통과
        except Exception as e:
            logger.warning(f"일일 트레이딩 전략 모듈 구문 분석 오류: {str(e)}")
            
        try:
            high_frequency_module = importlib.import_module("src.strategy.high_frequency_strategy")
            HighFrequencyStrategy = getattr(high_frequency_module, "HighFrequencyStrategy", None)
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"고빈도 전략 모듈 구문 분석 오류: {str(e)}")
            
        try:
            ml_high_frequency_module = importlib.import_module("src.strategy.ml_high_frequency_strategy")
            MLHighFrequencyStrategy = getattr(ml_high_frequency_module, "MLHighFrequencyStrategy", None)
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"ML 고빈도 전략 모듈 구문 분석 오류: {str(e)}")
        
        # 3. 전략 매칭 및 생성 (대소문자 구분 없음)
        target_mode = strategy_type.lower()
        
        if target_mode == 'basic':
            logger.info("기본 전략(Basic Strategy)을 생성합니다.")
            return BasicStrategy(market_data, order_api, config)
            
        elif target_mode == 'day_trading':
            if DayTradingStrategy:
                logger.info("🎯 일일 트레이딩 전략(Day Trading Strategy)을 활성화합니다.")
                return DayTradingStrategy(market_data, order_api, config)
            else:
                logger.warning("일일 트레이딩 모듈 파일이 없거나 내부 오류가 있습니다. 기본 전략으로 우회합니다.")
                return BasicStrategy(market_data, order_api, config)
                
        elif target_mode == 'high_frequency':
            if HighFrequencyStrategy:
                logger.info("⚡ 고빈도 스캘핑 전략(High Frequency Strategy)을 활성화합니다.")
                return HighFrequencyStrategy(market_data, order_api, config)
            else:
                logger.warning("고빈도 스캘핑 모듈 파일이 없거나 내부 오류가 있습니다. 기본 전략으로 우회합니다.")
                return BasicStrategy(market_data, order_api, config)
                
        elif target_mode == 'ml_high_frequency':
            if MLHighFrequencyStrategy and ml_model:
                logger.info("🤖 머신러닝 고빈도 인공지능 전략(ML High Frequency Strategy)을 활성화합니다.")
                return MLHighFrequencyStrategy(market_data, order_api, ml_model, config)
            else:
                logger.warning("ML 모델이 누락되었거나 모듈 파일에 오류가 있습니다. 기본 전략으로 우회합니다.")
                return BasicStrategy(market_data, order_api, config)
                
        else:
            logger.info(f"요청한 전략 유형({strategy_type})이 유효하지 않습니다. 기본 전략을 사용합니다.")
            return BasicStrategy(market_data, order_api, config)