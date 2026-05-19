import requests
import yaml
import json
import time
import logging
import os
from datetime import datetime
from .base import ApiClient

logger = logging.getLogger(__name__)

class KoreaInvestmentAuth(ApiClient):
    """한국투자증권 API 인증 및 규격 제어 클래스"""
    
    def __init__(self, config_path="config/api_config.yaml"):
        with open(config_path, 'r', encoding='utf-8') as file:
            self.config = yaml.safe_load(file)['api']
        
        self.base_url = self.config['base_url']
        
        # 환경변수 흡수
        self.app_key = os.getenv("KIS_API_KEY") or os.getenv("KIS_PAPER_KEY") or self.config.get('app_key', '')
        self.app_secret = os.getenv("KIS_SECRET_KEY") or os.getenv("KIS_PAPER_SEC") or self.config.get('app_secret', '')
        
        token_dir = os.path.dirname(os.path.abspath(config_path))
        self.token_file = os.path.join(token_dir, "token_info.json")
        
        self.access_token = None
        self.token_issued_at = None
        self.token_expired_at = None
        
        self._load_token_info()
    
    def authenticate(self):
        try:
            self.get_access_token(force_new=True)
            return self.access_token is not None
        except Exception as e:
            logger.error(f"인증 실패: {str(e)}")
            return False
            
    def get_headers(self):
        return self.get_auth_headers()

    # ==================================================================
    # 🎯 [한투 공식 매뉴얼 가드] 딕셔너리 키 대문자 및 자형 정류 필터
    # ==================================================================
    def _conform_to_korea_investment_spec(self, data):
        """매뉴얼 규격에 맞게 딕셔너리 구조를 대문자 및 문자열로 강제 정류"""
        if not isinstance(data, dict):
            return data
            
        conformed_dict = {}
        for k, v in data.items():
            # 1. Key를 무조건 대문자로 변환 (예: pdno -> PDNO)
            upper_key = str(k).upper()
            
            # 2. Value 처리: 숫자형인 경우 매뉴얼 규격에 따라 문자열(String)로 캐스팅
            if upper_key in ["ORD_QTY", "ORD_UNPR", "CNDT_PRIC", "CANO", "ACNT_PRDT_CD", "PDNO"]:
                if v is not None and not isinstance(v, str):
                    conformed_dict[upper_key] = str(v)
                else:
                    conformed_dict[upper_key] = v
            else:
                conformed_dict[upper_key] = v
                
        return conformed_dict

    def call(self, endpoint, method="GET", params=None, data=None):
        """API 호출단"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        # POST 전송 데이터인 경우 송신 전 정류 가드 작동
        if method.upper() == "POST" and data is not None:
            data = self._conform_to_korea_investment_spec(data)
            
        headers = self.get_auth_headers(include_hashkey=(method.upper() == "POST" and data is not None), body=data)
        
        try:
            if method.upper() == "GET":
                response = requests.get(url, headers=headers, params=params)
            elif method.upper() == "POST":
                response = requests.post(url, headers=headers, json=data)
            elif method.upper() == "PUT":
                response = requests.put(url, headers=headers, json=data)
            elif method.upper() == "DELETE":
                response = requests.delete(url, headers=headers, params=params)
            else:
                raise ValueError(f"지원하지 않는 HTTP 메서드: {method}")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"API 호출 실패 ({method} {url}): {str(e)}")
            if 'response' in locals() and response:
                logger.error(f"응답 코드: {response.status_code} | 내용: {response.text}")
            raise

    def _load_token_info(self):
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r', encoding='utf-8') as f:
                    token_info = json.load(f)
                    self.access_token = token_info.get('access_token')
                    self.token_issued_at = token_info.get('issued_at')
                    self.token_expired_at = token_info.get('expired_at')
                    current_time = time.time()
                    if self.token_expired_at and current_time >= self.token_expired_at:
                        self.access_token = None
            except Exception:
                pass

    def _save_token_info(self):
        token_info = {
            'access_token': self.access_token,
            'issued_at': self.token_issued_at,
            'expired_at': self.token_expired_at
        }
        try:
            os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
            with open(self.token_file, 'w', encoding='utf-8') as f:
                json.dump(token_info, f, indent=2)
        except Exception as e:
            logger.error(f"토큰 저장 실패: {str(e)}")

    def get_access_token(self, force_new=False):
        current_time = time.time()
        if self.access_token and not force_new and self.token_expired_at and current_time < self.token_expired_at:
            return self.access_token
            
        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        
        try:
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            token_data = response.json()
            self.access_token = token_data.get('access_token')
            expires_in = token_data.get('expires_in', 86400)
            self.token_issued_at = current_time
            self.token_expired_at = current_time + expires_in - 300
            self._save_token_info()
            return self.access_token
        except Exception as e:
            logger.error(f"토큰 발급 실패: {str(e)}")
            raise
    
    def get_hashkey(self, data):
        """해시키 생성 API 규격 동기화 및 빈 데이터 가드 추가"""
        # [안전 가드] 보낼 데이터가 없거나 빈 딕셔너리면 해시키를 발급받지 않고 즉시 반환
        if not data or f"{data}".strip() == "{}" or data is None:
            logger.warning("⚠️ 해시키 생성 요청에 유효한 Body 데이터가 없어 발급을 건너뜁니다.")
            return ""
            
        url = f"{self.base_url}/uapi/hashkey"
        headers = {
            "content-type": "application/json",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        
        # 해시 키 발급용 body 데이터 정류 적용
        valid_dict = self._conform_to_korea_investment_spec(data) if isinstance(data, dict) else {}
        
        try:
            response = requests.post(url, headers=headers, json=valid_dict)
            response.raise_for_status()
            return response.json().get('HASH', '')
        except Exception as e:
            logger.error(f"해시키 생성 실패: {str(e)}")
            return ""
    
    def get_auth_headers(self, include_hashkey=False, body=None):
        token = self.get_access_token()
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "",  # 실제 호출하는 API 단에서 tr_id를 주입하도록 비워둠
        }
        
        # [안전 가드] include_hashkey가 True이더라도 body가 실제로 채워져 있을 때만 해시키 조립 수행
        if include_hashkey and body and f"{body}".strip() != "{}":
            generated_hash = self.get_hashkey(body)
            if generated_hash:
                headers["hashkey"] = generated_hash
                
        return headers