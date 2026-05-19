import os
import requests
import logging
import yaml
from .auth import KoreaInvestmentAuth
from src.utils.calculator import MarketCalculator  # 🛡️ [호가 정류 엔진 주입]

logger = logging.getLogger(__name__)

class OrderAPI:
    # 🎯 auth, auth_client는 물론 외부에서 직접 주입되는 account_no와 mode까지 완벽 수용 가드 구축
    def __init__(self, auth=None, auth_client=None, config_path="config/api_config.yaml", mode='paper', account_no=None, market_data=None):
        """주문 및 계좌 연동 클래스 초기화"""
        
        # 1. 두 가지 인증 인자명 대응 (정방향 인프라 주입)
        self.auth = auth if auth is not None else auth_client
        self.mode = mode  # 실전(prod) / 모의(paper) 구분을 위한 확장 변수 저장
        self.market_data = market_data  # 🤝 상위 자산 데이터 동기화를 위한 인프라 참조 바인딩
        
        # 2. 설정 파일 로드 (기존 자산운용 로직 100% 보존)
        with open(config_path, 'r', encoding='utf-8') as file:
            self.config = yaml.safe_load(file)['api']
            
        self.base_url = self.config['base_url']
        
        # 3. [확장성 확보] 모의투자 여부에 따른 TR ID 자동 스위칭 가드 구축
        if self.mode == 'paper':
            self.balance_tr_id = "VTTC8434R"  # 모의투자 잔고 조회 ID
        else:
            self.balance_tr_id = "TTTC8434R"  # 실전투자 잔고 조회 ID
            
        # ==================================================================
        # [원칙 기반 정화] 코랩 백그라운드 프로세스 커널 누락 충돌 방지 레이어
        # ==================================================================
        env_api_key = os.getenv("KIS_API_KEY")
        env_secret_key = os.getenv("KIS_SECRET_KEY")
        
        is_mock_url = "vts" in self.config['base_url'].lower()
        
        # 호출부나 시스템 환경변수, 코랩 Secrets 중 가장 명확한 계좌 정보를 정방향 정렬
        if env_api_key and env_secret_key:
            self.config['app_key'] = env_api_key
            self.config['app_secret'] = env_secret_key
            
            if is_mock_url:
                self.config['account_no'] = account_no or os.getenv("KIS_PAPER_ACC") or self.config.get('account_no', '')
                logger.info("🔒 [환경변수 동기화] 표준 환경변수에서 모의투자 계정 정보를 정상 흡수했습니다.")
            else:
                self.config['account_no'] = account_no or os.getenv("KIS_REAL_ACC") or self.config.get('account_no', '')
                logger.info("🔒 [환경변수 동기화] 표준 환경변수에서 실전투자 계정 정보를 정상 흡수했습니다.")
        else:
            try:
                from google.colab import userdata
                if is_mock_url:
                    self.config['app_key'] = userdata.get('KIS_PAPER_KEY')
                    self.config['app_secret'] = userdata.get('KIS_PAPER_SEC')
                    self.config['account_no'] = account_no or userdata.get('KIS_PAPER_ACC') or self.config.get('account_no', '')
                    logger.info("🔒 [모의투자] 코랩 Secrets에서 모의투자 계정 정보를 로드했습니다.")
                else:
                    self.config['app_key'] = userdata.get('KIS_REAL_KEY')
                    self.config['app_secret'] = userdata.get('KIS_REAL_SEC')
                    self.config['account_no'] = account_no or userdata.get('KIS_REAL_ACC') or self.config.get('account_no', '')
                    logger.info("🔒 [실전투자] 코랩 Secrets에서 실전투자 계정 정보를 로드했습니다.")
            except (ImportError, Exception):
                pass
        
        self.base_url = self.config['base_url']
        # 최종 결정된 계좌번호를 마스터 변수에 바인딩 (외부 유입 변수가 최우선 순위)
        self.account_no = account_no if account_no is not None else self.config.get('account_no', '')
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
            
        # ==================================================================
        # 🛡️ [호가단위 자동 방어막 가동] 지정가 주문일 경우 거래소 틱 사이즈 강제 정류
        # ==================================================================
        if order_division == "00" and price > 0:
            direction = "ceil" if order_type == "01" else "floor"
            adjusted_price = MarketCalculator.adjust_to_tick(price, direction=direction)
            send_price = str(adjusted_price)
            
            if price != adjusted_price:
                logger.info(f"🛡️ [호가 정류기 가동] 원본가격: {price} -> 거래소 호가 규격 동기화: {adjusted_price}원 ({direction})")
        else:
            send_price = "0"
            
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        
        body = {
            "CANO": account_no[:8],
            "ACNT_PRDT_CD": account_no[8:],
            "PDNO": str(stock_code),
            "ORD_DVSN": str(order_division),
            "ORD_QTY": str(quantity),
            "ORD_UNPR": send_price,
            "CTAC_TLNO": "",
            "SLL_BUY_DVSN_CD": str(order_type),
            "YNGCLNG_PBLC_OTHR_ISNC_YN_P": ""
        }
        
        # POST 요청이므로 유효 바디를 주입하여 해시키 발행
        headers = self.auth.get_auth_headers(include_hashkey=True, body=body)
        
        if order_type == "01":
            headers["tr_id"] = "VTTC0011U" if self.is_mock else "TTTC0011U"
        else:
            headers["tr_id"] = "VTTC0012U" if self.is_mock else "TTTC0012U"
        
        try:
            logger.info(f"🚀 주문 전송: 종목={stock_code}, 구분={'시장가' if order_division=='01' else '지정가'} {'매도' if order_type=='01' else '매수'}, 수량={quantity}주, 단가={send_price}원")
            response = requests.post(url, headers=headers, json=body)
            
            if response.status_code != 200:
                logger.error(f"주문 API 응답 오류: HTTP {response.status_code} | {response.text}")
                return None
            
            data = response.json()
            if data.get('rt_cd') != '0':
                error_code = data.get('msg_cd', 'UNKNOWN')
                error_msg = data.get('msg1', '알 수 없는 오류')
                logger.error(f"❌ 한투 서버 거절: [{error_code}] {error_msg}")
                return None
            
            return data.get('output', {})
        except Exception as e:
            logger.error(f"주문 처리 중 예상치 못한 오류: {str(e)}", exc_info=True)
            return None

    def buy_market_order(self, stock_code, quantity):
        """[긴급 매수 브릿지] 시장가 매수 단발성 래퍼"""
        return self.place_order(stock_code=stock_code, order_type="02", quantity=quantity, price=0, order_division="01")

    def sell_market_order(self, stock_code, quantity):
        """[긴급 매도 브릿지] 시장가 매도 단발성 래퍼"""
        return self.place_order(stock_code=stock_code, order_type="01", quantity=quantity, price=0, order_division="01")
            
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
            "PDNO": str(stock_code),
            "ORD_QTY": str(quantity),
            "ORD_UNPR": "0",
            "CTAC_TLNO": "",
            "RSVN_ORD_YN": "N"
        }
        
        headers = self.auth.get_auth_headers(include_hashkey=True, body=body)
        headers["tr_id"] = "VTTC0803U" if self.is_mock else "TTTC0803U"
        
        try:
            response = requests.post(url, headers=headers, json=body)
            return response.json().get('output')
        except Exception as e:
            logger.error(f"주문 취소 중 예외 발생: {str(e)}")
            return None
            
    def get_order_status(self, order_no, stock_code=None, account_no=None):
        """주문 상태 조회"""
        if not account_no:
            account_no = self.account_no
        
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-order"
        params = {
            "CANO": account_no[:8],
            "ACNT_PRDT_CD": account_no[8:],
            "INQR_DVSN_1": "0", "INQR_DVSN_2": "0", "CTX_AREA_FK100": "", "CTX_AREA_NK100": "",
            "ODNO": order_no, "PDNO": stock_code or "", "SORT_SQNO": "1", "ORD_GNO_BRNO": "", "ODNO_TYPE": "1"
        }
        
        headers = self.auth.get_auth_headers(include_hashkey=False, body=None)  # GET이므로 바디/해시 제외
        headers["tr_id"] = "VTTC8001R" if self.is_mock else "TTTC8001R"
        
        try:
            response = requests.get(url, params=params, headers=headers)
            return response.json().get('output')
        except Exception as e:
            logger.error(f"주문 상태 조회 실패: {str(e)}")
            return None

    # ==================================================================
    # 💰 [대시보드 동기화 개혁] 실시간 대시보드 연동용 정방향 통합 브릿지
    # ==================================================================
    def get_present_balance(self):
        """스트림릿 대시보드와 UI 변수명이 정확히 일치하도록 캡슐화한 통합 잔고 조회 엔진"""
        if self.market_data and hasattr(self.market_data, 'get_present_balance'):
            return self.market_data.get_present_balance()
            
        try:
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
            params = {
                "CANO": self.account_no[:8],
                "ACNT_PRDT_CD": self.account_no[8:],
                "AFHR_FLPR_YN": "N", "OFL_YN": "", "INQR_DVSN": "02", "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "01",
                "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
            }
            # 🛡️ 안전 가드: GET 통신이므로 include_hashkey=False, body=None 강제 집행
            headers = self.auth.get_auth_headers(include_hashkey=False, body=None)
            headers["tr_id"] = self.balance_tr_id
            
            response = requests.get(url, params=params, headers=headers)
            if response.status_code == 200:
                data = response.json()
                summaries = data.get('output2', [])
                summary = summaries[0] if summaries else {}
                
                formatted_positions = []
                for stock in data.get('output1', []):
                    if int(stock.get('hldg_qty', 0)) > 0:
                        formatted_positions.append({
                            "주식코드": stock.get('pdno', ''),
                            "종목명": stock.get('prdt_name', '보유 종목'),
                            "보유수량": int(stock.get('hldg_qty', 0)),
                            "매입단가": int(float(stock.get('pchs_avg_pric', 0))),
                            "현재가": int(float(stock.get('prpr', 0) if stock.get('prpr') else stock.get('pchs_avg_pric', 0))),
                            "평가손익": int(float(stock.get('evlu_asst_amt', 0))) - int(float(stock.get('pchs_amt', 0)))
                        })
                
                # 🎯 app.py 메트릭 수신 인터페이스 키 네임과 완전 동화 (개혁 완료)
                return {
                    "cash": int(float(summary.get('dnca_tot_amt', 0))),
                    "total_eval_amount": int(float(summary.get('tot_evlu_amt', 0))),
                    "total_buy_amount": int(float(summary.get('pchs_amt_smtl_amt', 0))),
                    "total_profit_loss": int(float(summary.get('evlu_pfls_smtl_amt', 0))),
                    "positions": formatted_positions
                }
        except Exception as e:
            logger.error(f"❌ OrderAPI 내 잔고 동기화 예외 발생: {str(e)}")
            
        return {"cash": 0, "total_eval_amount": 0, "total_buy_amount": 0, "total_profit_loss": 0, "positions": []}