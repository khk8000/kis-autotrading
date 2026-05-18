#!/usr/bin/env python
"""
자동 주식 거래 시스템 실행 스크립트
여러 실행 모드를 지원합니다:
- cli: 명령행 인터페이스 (기본)
- web: 웹 인터페이스
- daemon: 데몬 모드
"""

import argparse
import os
import sys
import logging
from datetime import datetime

# ==============================================================================
# [원칙 기반 정화] 구글 코랩 환경 자동 감지, 환경변수 일괄 바인딩 및 TA-Lib 빌드 통합 자동화
# ==============================================================================
try:
    from google.colab import userdata
    
    # 1. [환경 독립형 아키텍처] 코랩 Secrets 데이터를 가상 OS 레벨 표준 환경변수로 동기화 자동화
    try:
        paper_key = userdata.get('KIS_PAPER_KEY')
        paper_sec = userdata.get('KIS_PAPER_SEC')
        paper_acc = userdata.get('KIS_PAPER_ACC')
        
        if paper_key and paper_sec:
            os.environ["KIS_API_KEY"] = paper_key
            os.environ["KIS_SECRET_KEY"] = paper_sec
            os.environ["KIS_PAPER_KEY"] = paper_key
            os.environ["KIS_PAPER_SEC"] = paper_sec
            if paper_acc:
                os.environ["KIS_PAPER_ACC"] = paper_acc
                
            print("🔒 [인프라 브릿지] 구글 코랩 Secrets 데이터를 OS 표준 환경변수로 자동 동기화했습니다.")
    except AttributeError:
        # 코랩 내부에서 서브 프로세스(터미널 CLI)로 분기 실행될 때 커널 누락으로 인한 잔상 에러 숨김 처리
        pass
    except Exception as env_err:
        print(f"⚠️ [인프라 브릿지] 코랩 Secrets 로드 중 기타 예외 발생: {env_err}")

    # 2. 가상환경 의존성(TA-Lib C-Engine) 컴파일 및 파이썬 모듈 자동 빌드
    try:
        import talib
    except ImportError:
        print('📦 [컴파일 엔진 시동] 코랩 환경에서 TA-Lib 컴파일 및 빌드 자동화를 시작합니다.')
        print('=' * 70)
        os.system('wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz')
        os.system('tar -xzf ta-lib-0.4.0-src.tar.gz')
        os.system('cd ta-lib && ./configure --prefix=/usr && make && make install')
        os.system('rm -rf ta-lib ta-lib-0.4.0-src.tar.gz')
        os.system('pip install TA-Lib')
        print('=' * 70)
        print('✅ [빌드 마감] TA-Lib 핵심 C-Engine 컴파일 및 파이썬 모듈 바인딩이 완료되었습니다.')
except ImportError:
    # 코랩 환경이 아닐 경우(로컬 PC 또는 일반 AWS/GCP Linux 서버) 아무 작업도 하지 않고 유연하게 통과
    pass
# ==============================================================================

# 모듈 경로 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def setup_logging():
    """로깅 설정"""
    log_dir = os.path.abspath("logs")
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, f'run_{datetime.now().strftime("%Y%m%d")}.log')
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

def run_cli_mode(args):
    """CLI 모드 실행 (main.py의 서브파서 간섭 우회 및 실시간 루프 강제 주입)"""
    # 1. 기존 인자 찌꺼기를 완전히 초기화합니다.
    sys.argv = [sys.argv[0]]
    
    # 2. main.py가 단일 실행(--once)을 하지 않고 무한 루프를 돌도록 하위 아규먼트 강제 설계
    if args.force:
        sys.argv.append('--force')
        os.environ["FORCE_BYPASS"] = "True"
        
    # ==============================================================================
    # [최종 패치 완료] 사용자가 명령어로 지정한 전략 커스텀 타입을 main.py에 강제 바인딩
    # ==============================================================================
    if hasattr(args, 'strategy_type') and args.strategy_type:
        sys.argv.extend(['--strategy-type', args.strategy_type])
        
    print(f"🚀 [엔진 강제 전환] main.py로 무한 거래 루프 및 {args.strategy_type} 전략 신호를 전달합니다.")
    from main import main as cli_main
    cli_main()

def run_web_mode(args):
    """웹 인터페이스 모드 실행"""
    try:
        from src.web.app import start_web_server
        start_web_server(host=args.host, port=args.port)
    except ImportError:
        logging.error("웹 인터페이스 모듈을 찾을 수 없습니다.")
        sys.exit(1)

def run_daemon_mode(args):
    """데몬 모드 실행"""
    import daemon
    import lockfile
    
    log_dir = os.path.abspath("logs")
    os.makedirs(log_dir, exist_ok=True)
    
    pid_file = os.path.join(log_dir, 'trading_daemon.pid')
    log_file = os.path.join(log_dir, 'trading_daemon.log')
    
    daemon_logger = logging.getLogger()
    daemon_logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_file)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    daemon_logger.addHandler(handler)
    
    context = daemon.DaemonContext(
        working_directory=os.path.abspath('.'),
        umask=0o002,
        pidfile=lockfile.FileLock(pid_file)
    )
    
    context.stdout = open(log_file, 'a+')
    context.stderr = open(log_file, 'a+')
    
    with context:
        logging.info("데몬 모드로 거래 시스템 시작")
        if len(sys.argv) > 1 and sys.argv[1] == 'daemon':
            sys.argv.pop(1)
        from main import main as daemon_main
        daemon_main()

def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description='자동 주식 거래 시스템')
    subparsers = parser.add_subparsers(dest='mode', help='실행 모드')
    
    # CLI 모드 인자
    cli_parser = subparsers.add_parser('cli', help='명령행 인터페이스')
    cli_parser.add_argument('--config', default='config/api_config.yaml', help='API 설정 파일 경로')
    cli_parser.add_argument('--strategy', default='config/trading_config.yaml', help='전략 설정 파일 경로')
    cli_parser.add_argument('--strategy-type', default='basic', choices=['basic', 'day_trading', 'high_frequency', 'ml_high_frequency'], help='전략 유형')
    cli_parser.add_argument('--once', action='store_true', help='한 번만 실행')
    # [인프라 주입] CLI 모드 서브파서에 디버그용 --force 관제 인자 확장
    cli_parser.add_argument('--force', action='store_true', help='장 종료 후에도 가드레일을 우회하여 거래 루프 강제 실행')
    
    # 웹 모드 인자
    web_parser = subparsers.add_parser('web', help='웹 인터페이스')
    web_parser.add_argument('--host', default='127.0.0.1', help='호스트 주소')
    web_parser.add_argument('--port', type=int, default=5000, help='포트 번호')
    
    # 데몬 모드 인자
    daemon_parser = subparsers.add_parser('daemon', help='데몬 모드')
    daemon_parser.add_argument('--config', default='config/api_config.yaml', help='API 설정 파일 경로')
    daemon_parser.add_argument('--strategy', default='config/trading_config.yaml', help='전략 설정 파일 경로')
    daemon_parser.add_argument('--strategy-type', default='basic', help='전략 유형')
    # [인프라 주입] 백그라운드 스케줄 데몬 모드에도 상시 모니터링을 위한 --force 인자 세트 백업 추가
    daemon_parser.add_argument('--force', action='store_true', help='장 종료 후에도 가드레일을 우회하여 데몬 강제 실행')
    
    # 명시적 서브 명령어가 누락되었을 때 기본값으로 cli를 밀어넣어주는 로직
    if len(sys.argv) > 1 and sys.argv[1] not in ['cli', 'web', 'daemon', '-h', '--help']:
        sys.argv.insert(1, 'cli')
    
    args = parser.parse_args()
    
    if not args.mode:
        args.mode = 'cli'
    
    setup_logging()
    logging.info(f"실행 모드: {args.mode}")
    
    if args.mode == 'cli':
        run_cli_mode(args)
    elif args.mode == 'web':
        run_web_mode(args)
    elif args.mode == 'daemon':
        run_daemon_mode(args)
    else:
        logging.error(f"알 수 없는 모드: {args.mode}")
        sys.exit(1)

if __name__ == "__main__":
    main()