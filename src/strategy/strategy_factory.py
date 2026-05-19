"""
전략 생성 관리자 통합 마스터 (src/strategy/strategy_factory.py)
"""

import logging

logger = logging.getLogger(__name__)

class StrategyFactory:
    @staticmethod
    def create_strategy(strategy_type: str, market_data, order_api, config=None, config_manager=None, ml_model=None, **kwargs):
        """외부 진입점의 어떤 인자 규격(config=...)이 들어와도 유연하게 수용합니다."""
        target_mode = strategy_type.lower().strip()
        
        # 주입된 모든 설정 규격을 하나의 단일 딕셔너리로 강제 정렬
        strategy_config = {}
        manager = config_manager or config
        if manager is not None:
            if hasattr(manager, 'get_strategy_config'):
                strategy_config = manager.get_strategy_config()
            elif hasattr(manager, 'get_config'):
                strategy_config = manager.get_config('strategy') or {}
            elif isinstance(manager, dict):
                strategy_config = manager.get('strategy', manager)
                
        if not strategy_config:
            kw_config = kwargs.get('config') or kwargs.get('config_manager')
            if isinstance(kw_config, dict):
                strategy_config = kw_config.get('strategy', kw_config)
            elif hasattr(kw_config, 'get_strategy_config'):
                strategy_config = kw_config.get_strategy_config()

        # 1. 기본 분산 투자 전략
        if target_mode == 'basic':
            try:
                from src.strategy.basic_strategy import BasicStrategy
                logger.info("🎯 [전략 팩토리] 기본 분산 투자 전략(BasicStrategy)을 활성화합니다.")
                return BasicStrategy(market_data, order_api, strategy_config)
            except ImportError as e:
                logger.critical(f"❌ 기본 전략 모듈 로드 실패: {e}")
                raise e

        # 2. 데이 트레이딩 전략
        elif target_mode == 'day_trading':
            try:
                from src.strategy.day_trading_strategy import DayTradingStrategy
                logger.info("🎯 [전략 팩토리] 일일 트레이딩 전략(DayTradingStrategy)을 활성화합니다.")
                return DayTradingStrategy(market_data, order_api, strategy_config)
            except ImportError:
                return StrategyFactory._get_default_fallback(market_data, order_api, strategy_config)

        # 3. 고빈도 스캘핑 전략
        elif target_mode == 'high_frequency':
            try:
                from src.strategy.HighFrequencyStrategy import HighFrequencyStrategy
                return HighFrequencyStrategy(market_data, order_api, strategy_config)
            except ImportError:
                try:
                    from src.strategy.high_frequency_strategy import HighFrequencyStrategy
                    return HighFrequencyStrategy(market_data, order_api, strategy_config)
                except ImportError:
                    return StrategyFactory._get_default_fallback(market_data, order_api, strategy_config)

        # 4. 머신러닝 고빈도 인공지능 전략
        elif target_mode == 'ml_high_frequency':
            try:
                from src.strategy.ml_high_frequency_strategy import MLHighFrequencyStrategy
                if ml_model is None:
                    return StrategyFactory._get_default_fallback(market_data, order_api, strategy_config)
                return MLHighFrequencyStrategy(market_data, order_api, ml_model, strategy_config)
            except ImportError:
                return StrategyFactory._get_default_fallback(market_data, order_api, strategy_config)

        else:
            return StrategyFactory._get_default_fallback(market_data, order_api, strategy_config)

    @staticmethod
    def _get_default_fallback(market_data, order_api, config):
        from src.strategy.basic_strategy import BasicStrategy
        logger.info("🛡️ 시스템을 안전한 BasicStrategy 인프라로 유도했습니다.")
        return BasicStrategy(market_data, order_api, config)