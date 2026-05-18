"""
전략 생성 관리자 (src/strategy/strategy_factory.py)
"""

import logging

logger = logging.getLogger(__name__)

class StrategyFactory:
    @staticmethod
    def create_strategy(strategy_type: str, market_data, order_api, config_manager, ml_model=None):
        target_mode = strategy_type.lower().strip()
        strategy_config = config_manager.get_strategy_config() if hasattr(config_manager, 'get_strategy_config') else {}
        
        # 1. 기본 전략
        if target_mode == 'basic':
            try:
                from src.strategy.basic_strategy import BasicStrategy
                logger.info("🎯 [전략 팩토리] 기본 분산 투자 전략(BasicStrategy)을 활성화합니다.")
                return BasicStrategy(market_data, order_api, strategy_config)
            except ImportError as e:
                logger.critical(f"기본 전략 로드 실패: {e}")
                raise e

        # 2. 데이 트레이딩 전략
        elif target_mode == 'day_trading':
            try:
                from src.strategy.day_trading_strategy import DayTradingStrategy
                logger.info("🎯 [전략 팩토리] 일일 트레이딩 전략(DayTradingStrategy)을 활성화합니다.")
                return DayTradingStrategy(market_data, order_api, strategy_config)
            except ImportError:
                logger.warning("⚠️ DayTradingStrategy 모듈이 없습니다. 기본 전략으로 우회합니다.")
                return StrategyFactory._get_default_fallback(market_data, order_api, strategy_config)

        # 3. 고빈도 스캘핑 전략 (대소문자 파일명 매칭 대응)
        elif target_mode == 'high_frequency':
            try:
                # 트리에 표기된 HighFrequencyStrategy.py 파일에서 클래스 추출 시도
                from src.strategy.HighFrequencyStrategy import HighFrequencyStrategy
                logger.info("⚡ [전략 팩토리] 고빈도 스캘핑 전략(HighFrequencyStrategy)을 활성화합니다.")
                return HighFrequencyStrategy(market_data, order_api, strategy_config)
            except ImportError:
                try:
                    from src.strategy.high_frequency_strategy import HighFrequencyStrategy
                    logger.info("⚡ [전략 팩토리] 고빈도 스캘핑 전략(HighFrequencyStrategy)을 활성화합니다.")
                    return HighFrequencyStrategy(market_data, order_api, strategy_config)
                except ImportError:
                    logger.warning("⚠️ HighFrequencyStrategy 모듈이 없습니다. 기본 전략으로 우회합니다.")
                    return StrategyFactory._get_default_fallback(market_data, order_api, strategy_config)

        # 4. 머신러닝 고빈도 인공지능 전략
        elif target_mode == 'ml_high_frequency':
            try:
                from src.strategy.ml_high_frequency_strategy import MLHighFrequencyStrategy
                if ml_model is None:
                    return StrategyFactory._get_default_fallback(market_data, order_api, strategy_config)
                logger.info("🤖 [전략 팩토리] 머신러닝 고빈도 전략(MLHighFrequencyStrategy)을 활성화합니다.")
                return MLHighFrequencyStrategy(market_data, order_api, ml_model, strategy_config)
            except ImportError:
                logger.warning("⚠️ MLHighFrequencyStrategy 모듈이 없습니다. 기본 전략으로 우회합니다.")
                return StrategyFactory._get_default_fallback(market_data, order_api, strategy_config)

        else:
            return StrategyFactory._get_default_fallback(market_data, order_api, strategy_config)

    @staticmethod
    def _get_default_fallback(market_data, order_api, config):
        from src.strategy.basic_strategy import BasicStrategy
        logger.info("🛡️ [가드레일] 인프라 안정성을 위해 순정 BasicStrategy 엔진을 강제 배정합니다.")
        return BasicStrategy(market_data, order_api, config)