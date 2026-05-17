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
    """한국투자증권 API 인증 클래스"""
    
    def __init__(self, config_path="config/api_config.yaml"):
        """한국투자증권 API 인증 클래스 초기화
        
        Args:
            config_path (str): API 설정 파일 경로
        """
        # 설정 파일 로드
        with open(config_path, 'r', encoding='utf-8') as file:
            self.config = yaml.safe_load(file)['api']
        
        self.base_url = self.config['base_url']
        
        # ==================================================================
        # [환경 독립형 아키텍처 완결] OS 환경변수(os.getenv) 최우선 흡수 레이어
        # 시스템에 등록된 환경변수가 있다면 우선 채택하고, 없을 때만 YAML 백업 설정을 적용합니다.
        # ==================================================================
        self.app_key = os.getenv("KIS_API_KEY") or os.getenv("KIS_PAPER_KEY") or self.config.get('app_key', '')
        self.app_secret = os.getenv("KIS_SECRET_KEY") or os.getenv("KIS_PAPER_SEC") or self.config.get('app_secret', '')
        
        if os.getenv("KIS_API_KEY") and os.getenv("KIS_SECRET_KEY"):
            logger.info("🔒 [인증 모듈] OS 표준 환경변수에서 상위 인프라 보안 키(Key) 세트를 정상 흡수했습니다.")
        else:
            logger.warning("⚠️ [인증 모듈] 표준 환경변수가 탐지되지 않아 YAML 설정 백업 데이터로 진입합니다.")
        # ==================================================================
        
        # 토큰 파일 경로
        token_dir = os.path.dirname(os.path.abspath(config_path))
        self.token_file = os.path.join(token_dir, "token_info.json")
        
        # 토큰 정보 초기화
        self.access_token = None
        self.token_issued_at = None
        self.token_expired_at = None
        
        # 저장된 토큰 정보 로드
        self._load_token_info()
    
    def authenticate(self):
        """인증 수행 - 액세스 토큰 발급"""
        try:
            self.get_access_token(force_new=True)
            return self.access_token is not None
        except Exception as e:
            logger.error(f"인증 실패: {str(e)}")
            return False
    
    def get_headers(self):
        """요청 헤더 반환"""
        return self.get_auth_headers()
    
    def call(self, endpoint, method="GET", params=None, data=None):
        """API 호출"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = self.get_auth_headers(include_hashkey=(data is not None), body=data)
        
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
                logger.error(f"응답 상태 코드: {response.status_code}")
                logger.error(f"응답 내용: {response.text}")
            raise
    
    def _load_token_info(self):
        """저장된 토큰 정보 로드"""
        if os.path.exists(self.token_file):
            try:
                with open(self.token_file, 'r', encoding='utf-8') as f:
                    token_info = json.load(f)
                    
                    self.access_token = token_info.get('access_token')
                    self.token_issued_at = token_info.get('issued_at')
                    self.token_expired_at = token_info.get('expired_at')
                    
                    logger.info("토큰 정보를 파일에서 로드했습니다.")
                    
                    current_time = time.time()
                    if self.token_expired_at and current_time >= self.token_expired_at:
                        logger.info("로드한 토큰이 만료되었습니다.")
                        self.access_token = None
                        self.token_expired_at = None
            except Exception as e:
                logger.error(f"토큰 정보 로드 중 오류 발생: {str(e)}")
                self.access_token = None
                self.token_issued_at = None
                self.token_expired_at = None

    def _save_token_info(self):
        """토큰 정보 저장"""
        token_info = {
            'access_token': self.access_token,
            'issued_at': self.token_issued_at,
            'expired_at': self.token_expired_at
        }
        
        try:
            token_dir = os.path.dirname(self.token_file)
            os.makedirs(token_dir, exist_ok=True)
            
            with open(self.token_file, 'w', encoding='utf-8') as f:
                json.dump(token_info, f, indent=2)
            logger.info(f"토큰 정보를 파일에 저장했습니다: {self.token_file}")
        except Exception as e:
            logger.error(f"토큰 정보 저장 중 오류 발생: {str(e)}")

    def get_access_token(self, force_new=False):
        """액세스 토큰 발급 또는 캐시된 토큰 반환"""
        current_time = time.time()
        
        token_is_valid = (
            self.access_token is not None and
            not force_new and
            self.token_expired_at is not None and
            current_time < self.token_expired_at
        )
        
        if token_is_valid:
            logger.debug("캐시된 토큰을 사용합니다.")
            return self.access_token
        
        if self.token_issued_at and not force_new:
            issued_date = datetime.fromtimestamp(self.token_issued_at).date()
            today = datetime.now().date()
            
            if issued_date == today:
                logger.warning("오늘 이미 토큰이 발급되었습니다. 기존 토큰을 사용합니다.")
                if self.access_token:
                    return self.access_token
                else:
                    logger.warning("기존 토큰이 유효하지 않습니다. 새 토큰을 발급합니다.")
        
        url = f"{self.base_url}/oauth2/tokenP"
        
        headers = {
            "content-type": "application/json"
        }
        
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            response.raise_for_status()
            
            token_data = response.json()
            self.access_token = token_data.get('access_token')
            
            expires_in = token_data.get('expires_in', 86400)
            self.token_issued_at = current_time
            self.token_expired_at = current_time + expires_in - 300
            
            self._save_token_info()
            
            logger.info(f"새 액세스 토큰이 발급되었습니다. 만료 시간: {expires_in}초")
            return self.access_token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"토큰 발급 중 오류 발생: {str(e)}")
            if 'response' in locals() and response:
                logger.error(f"응답: {response.text}")
            raise
    
    def get_hashkey(self, data):
        """데이터로부터 해시키 생성"""
        url = f"{self.base_url}/uapi/hashkey"
        
        headers = {
            "content-type": "application/json",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            response.raise_for_status()
            
            hashkey = response.json()['HASH']
            return hashkey
        except requests.exceptions.RequestException as e:
            logger.error(f"해시키 생성 중 오류 발생: {str(e)}")
            raise
    
    def get_auth_headers(self, include_hashkey=False, body=None):
        """인증 헤더 생성"""
        token = self.get_access_token()
        
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "",
        }
        
        if include_hashkey and body:
            headers["hashkey"] = self.get_hashkey(body)
        
        return headers
