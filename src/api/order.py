import os
import requests
import logging
import yaml
from .auth import KoreaInvestmentAuth

logger = logging.getLogger(__name__)

class OrderAPI:
    def __init__(self, auth, config_path="config/api_config.yaml"):
        """주문 실행 클래스 초기화
        
        Args:
            auth (KoreaInvestmentAuth): 인증 객체
            config_path (str): 설정 파일 경로
        """
        self.auth = auth
        
        # 설정 파일 로드
        with open(config_path, 'r', encoding='utf-8') as file:
            self.config = yaml.safe_load(file)['api']
            
        # ==================================================================
        # [원칙 기반 정화] 코랩 백그라운드 프로세스 커널 누락 충돌 방지 레이어
        # 상위 세션 영역에서 바인딩해 둔 표준 환경변수(os.getenv)를 우선 흡수합니다.
        # ==================================================================
        env_api_key = os.getenv("KIS_API_KEY")
        env_secret_key = os.getenv("KIS_SECRET_KEY")
        
        is_mock_url = "vts" in self.config['base_url'].lower()
        
        if env_api_key and env_secret_key:
            # 환경변수에 키가 존재한다면 코랩/로컬 공통으로 환경변수 값 매핑
            self.config['app_key'] = env_api_key
            self.config['app_secret'] = env_secret_key
            
            if is_mock_url:
                # 모의투자 환경인 경우 계좌번호 매핑 (환경변수 또는 코랩 Secrets 백업)
                self.config['account_no'] = os.getenv("KIS_PAPER_ACC") or self.config.get('account_no', '')
                logger.info("🔒 [환경변수 동기화] 표준 환경변수에서 모의투자 계정 정보를 정상 흡수했습니다.")
            else:
                # 실전투자 환경인 경우 계좌번호 매핑
                self.config['account_no'] = os.getenv("KIS_REAL_ACC") or self.config.get('account_no', '')
                logger.info("🔒 [환경변수 동기화] 표준 환경변수에서 실전투자 계정 정보를 정상 흡수했습니다.")
        else:
            # 환경변수가 없을 경우에만 기존 구글 코랩 내장 userdata 엔진 백업 작동
            try:
                from google.colab import userdata
                if is_mock_url:
                    self.config['app_key'] = userdata.get('KIS_PAPER_KEY')
                    self.config['app_secret'] = userdata.get('KIS_PAPER_SEC')
                    self.config['account_no'] = userdata.get('KIS_PAPER_ACC')
                    logger.info("🔒 [모의투자] 코랩 Secrets에서 모의투자 계정 정보를 로드했습니다.")
                else:
                    self.config['app_key'] = userdata.get('KIS_REAL_KEY')
                    self.config['app_secret'] = userdata.get('KIS_REAL_SEC')
                    self.config['account_no'] = userdata.get('KIS_REAL_ACC')
                    logger.info("🔒 [실전투자] 코랩 Secrets에서 실전투자 계정 정보를 로드했습니다.")
            except (ImportError, Exception):
                # 코랩 환경이 아니거나 로컬인 경우 YAML 기본값 유지
                pass
        # ==================================================================
        
        self.base_url = self.config['base_url']
        self.account_no = self.config.get('account_no', '')
        
        # base_url을 기준으로 모의투자 여부 자동 판별 (전체 메서드에서 재사용)
        self.is_mock = "vts" in self.base_url.lower()
    
    def place_order(self, stock_code, order_type, quantity, price=0, account_no=None, order_division="00"):
        """주식 주문 실행"""
        if not account_no:
            account_no = self.account_no
        
        if quantity <= 0:
            logger.warning(f"주문 수량이 0 또는 음수입니다: {quantity}, 종목코드: {stock_code}")
            return None
        
        min_order_amount = 10000
        estimated_amount = quantity * price
        if estimated_amount < min_order_amount and price > 0:
            logger.warning(f"최소 주문 금액({min_order_amount}원) 미만입니다: {estimated_amount}원, 종목코드: {stock_code}")
            adjusted_quantity = max(1, int(min_order_amount / price))
            logger.info(f"주문 수량을 조정합니다: {quantity} -> {adjusted_quantity}")
            quantity = adjusted_quantity
            
        send_price = "0" if order_division == "01" else str(price)
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        
        body = {
            "CANO": account_no[:8],
            "ACNT_PRDT_CD": account_no[8:],
            "PDNO": stock_code,
            "ORD_DVSN": order_division,
            "ORD_QTY": str(quantity),
            "ORD_UNPR": send_price,
            "CTAC_TLNO": "",
            "SLL_BUY_DVSN_CD": order_type,
            "YNGCLNG_PBLC_OTHR_ISNC_YN_P": ""
        }
        
        headers = self.auth.get_auth_headers(include_hashkey=True, body=body)
        
        if order_type == "01":
            headers["tr_id"] = "VTTC0801U" if self.is_mock else "TTTC0801U"
        else:
            headers["tr_id"] = "VTTC0802U" if self.is_mock else "TTTC0802U"
        
        try:
            logger.info(f"주문 시도: 종목={stock_code}, 구분={'시장가' if order_division=='01' else '지정가'} {'매도' if order_type=='01' else '매수'}, "
                        f"수량={quantity}주, 전송단가={send_price} (참고금액={quantity*price}원)")
            
            response = requests.post(url, headers=headers, json=body)
            
            if response.status_code != 200:
                logger.error(f"주문 API 응답 오류: HTTP {response.status_code}")
                logger.error(f"응답 내용: {response.text}")
                return None
            
            data = response.json()
            
            if data.get('rt_cd') != '0':
                error_code = data.get('msg_cd', 'UNKNOWN')
                error_msg = data.get('msg1', '알 수 없는 오류')
                logger.error(f"주문 오류: [{error_code}] {error_msg}")
                
                if "잔고" in error_msg or "예수금" in error_msg:
                    logger.error("잔고 부족으로 주문이 거부되었습니다.")
                elif "수량" in error_msg:
                    logger.error("주문 수량 오류로 주문이 거부되었습니다.")
                elif "시간" in error_msg:
                    logger.error("거래 시간 외 주문으로 거부되었습니다.")
                
                return None
            
            output = data.get('output')
            krx_order_no = output.get('KRX_FWDG_ORD_ORGNO', 'N/A') if output else 'N/A'
            order_no = output.get('ODNO', 'N/A') if output else 'N/A'
            
            logger.info(f"주문 성공: {stock_code}, 수량: {quantity}주, 구분={'시장가' if order_division=='01' else '지정가'}")
            logger.info(f"주문번호: 한국투자증권={order_no}, KRX={krx_order_no}")
            
            return output
            
        except requests.exceptions.RequestException as e:
            logger.error(f"주문 요청 중 네트워크 오류: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"주문 처리 중 예상치 못한 오류: {str(e)}")
            return None
            
    def cancel_order(self, original_order_no, stock_code, quantity, account_no=None):
        """주문 취소"""
        if not account_no:
            account_no = self.account_no
        
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        
        body = {
            "CANO": account_no[:8],
            "ACNT_PRDT_CD": account_no[8:],
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": original_order_no,
            "ORD_DVSN": "00",
            "RVSE_CNCL_DVSN_CD": "02",
            "PDNO": stock_code,
            "ORD_QTY": str(quantity),
            "ORD_UNPR": "0",
            "CTAC_TLNO": "",
            "RSVN_ORD_YN": "N"
        }
        
        headers = self.auth.get_auth_headers(include_hashkey=True, body=body)
        headers["tr_id"] = "VTTC0803U" if self.is_mock else "TTTC0803U"
        
        try:
            response = requests.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
            
            if data.get('rt_cd') != '0':
                logger.error(f"Cancel Error: {data.get('msg_cd')} - {data.get('msg1')}")
                return None
            
            logger.info(f"Order cancelled successfully: {data}")
            return data.get('output')
        except Exception as e:
            logger.error(f"Error cancelling order: {str(e)}")
            raise
            
    def get_order_status(self, order_no, stock_code=None, account_no=None):
        """주문 상태 조회"""
        if not account_no:
            account_no = self.account_no
        
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-order"
        
        params = {
            "CANO": account_no[:8],
            "ACNT_PRDT_CD": account_no[8:],
            "INQR_DVSN_1": "0",
            "INQR_DVSN_2": "0",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "ODNO": order_no,
            "PDNO": stock_code or "",
            "SORT_SQNO": "1",
            "ORD_GNO_BRNO": "",
            "ODNO_TYPE": "1"
        }
        
        headers = self.auth.get_auth_headers()
        headers["tr_id"] = "VTTC8001R" if self.is_mock else "TTTC8001R"
        
        try:
            response = requests.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            if data.get('rt_cd') != '0':
                logger.error(f"API Error: {data.get('msg_cd')} - {data.get('msg1')}")
                return None
                
            return data.get('output')
        except Exception as e:
            logger.error(f"Error getting order status: {str(e)}")
            raise
