# -*- coding: utf-8 -*-
"""
시장 거래 규칙 통합 연산 엔진 (calculator.py)
- KRX 한국거래소 법정 호가단위(Tick Size) 일치화 알고리즘
- 부동소수점 오차 방지 및 매수/매도 맞춤형 가격 정류 기능 내장
"""

import math
import logging

logger = logging.getLogger("MarketCalculator")

class MarketCalculator:
    @staticmethod
    def get_tick_size(price: int) -> int:
        """
        KRX 정규장 주가 구간별 법정 호가단위(Tick Size) 산출
        :param price: 정수형 주가
        :return: 해당 가격대의 호가 단위 (원)
        """
        abs_price = abs(int(price))
        
        if abs_price < 2000:
            return 1
        elif abs_price < 5000:
            return 5
        elif abs_price < 20000:
            return 10
        elif abs_price < 50000:
            return 50
        elif abs_price < 200000:
            return 100
        elif abs_price < 500000:
            return 500  # 현재 삼성전자 구간 (20만 원 ~ 50만 원 미만)
        else:
            return 1000

    @classmethod
    def adjust_to_tick(cls, target_price: float, direction: str = "floor") -> int:
        """
        이론가격을 거래소 법정 호가단위에 맞춰 정밀 정류 (부동소수점 가드 포함)
        
        :param target_price: 알고리즘(변동성 돌파 등)이 계산해낸 자산의 이론가
        :param direction: 정류 방향 결정
                          - 'floor': 내림 (매수 시 호가를 낮춰 자금 절약 및 안전지대 확보)
                          - 'ceil' : 올림 (매도 시 호가를 높여 단 1원이라도 수익 극대화)
                          - 'round': 반올림 (가장 가까운 법정 호가 매핑)
        :return: 호가 단위 정류가 완료된 정수형 가격
        """
        try:
            # 1. 원초적 부동소수점 오차 강제 진압 (예: 275380.00000001 -> 275380)
            base_price = int(math.floor(target_price + 1e-9))
            
            # 2. 해당 가격대의 거래소 규격 호가 틱 확보
            tick_size = cls.get_tick_size(base_price)
            
            # 3. 방향성 정류 알고리즘 가동
            if direction == "floor":
                adjusted_price = (base_price // tick_size) * tick_size
            elif direction == "ceil":
                if base_price % tick_size == 0:
                    adjusted_price = base_price
                else:
                    adjusted_price = ((base_price // tick_size) + 1) * tick_size
            elif direction == "round":
                adjusted_price = int(round(base_price / tick_size) * tick_size)
            else:
                logger.warning(f"⚠️ 정의되지 않은 정류 방향({direction})이 입력되어 기본값 'floor'를 적용합니다.")
                adjusted_price = (base_price // tick_size) * tick_size
                
            return adjusted_price
            
        except Exception as e:
            logger.error(f"💥 호가 정류 연산 중 예외 발생: {str(e)} | 입력값: {target_price}")
            # 시스템 다운 방지를 위한 최하단 안전 폴백 안전선 (원가격 정수 반환)
            return int