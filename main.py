# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 主调度程序
(现代服务定制版 - 集成全频段毁灭扫描)
===================================
"""
import os
import sys

# 代理配置
if os.getenv("GITHUB_ACTIONS") != "true":
    pass

import argparse
import logging
import time
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import List, Optional

# 尝试引入飞书文档管理器
try:
    from src.feishu_doc import FeishuDocManager
except ImportError:
    class FeishuDocManager:
        def is_configured(self): return False
        def create_daily_doc(self, title, content): return None

from src.config import get_config, Config
from src.notification import NotificationService
from src.core.pipeline import StockAnalysisPipeline
from src.core.market_review import run_market_review
from src.search_service import SearchService
from src.analyzer import GeminiAnalyzer

# [现代服务] 引入全频段扫描探头
try:
    from src.scanner import scan_for_destruction
except ImportError:
    # 兼容性处理
    def scan_for_destruction(limit=3):
        return []

# 配置日志格式
LOG_FORMAT = '%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

def setup_logging(debug: bool = False, log_dir: str = "./logs") -> None:
    """配置日志系统"""
    level = logging.DEBUG if debug else logging.INFO
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now().strftime('%Y%m%d')
    log_file = log_path / f"stock_analysis_{today_str}.log"
    
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root_logger.addHandler(console_handler)
    
    # 降低第三方库日志级别
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('google').setLevel(logging.WARNING)

    # 强制打印一行，确保看到日志系统启动
    print(f"DEBUG: 日志系统已就绪，输出文件: {log_file}", flush=True)

logger = logging.getLogger(__name__)

def parse_arguments() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='A股自选股智能分析系统')
    parser.add_argument('--debug', action='store_true', help='调试模式')
    parser.add_argument('--dry-run', action='store_true', help='仅获取数据')
    parser.add_argument('--stocks', type=str, help='指定股票代码')
    parser.add_argument('--no-notify', action='store_true', help='不发送通知')
    parser.add_argument('--single-notify', action='store_true', help='单股推送')
    parser.add_argument('--workers', type=int, default=None, help='并发数')
    parser.add_argument('--schedule', action='store_true', help='定时任务模式')
    parser.add_argument('--market-review', action='store_true', help='仅大盘复盘')
    parser.add_argument('--no-market-review', action='store_true', help='跳过复盘')
    parser.add_argument('--webui', action='store_true', help='启动WebUI')
    parser.add_argument('--webui-only', action='store_true', help='仅启动WebUI')
    return parser.parse_args()

def run_full_analysis(config: Config, args: argparse.Namespace, stock_codes: Optional[List[str]] = None):
    """执行完整的分析流程"""
    try:
        if getattr(args, 'single_notify', False):
            config.single_stock_notify = True
        
        pipeline = StockAnalysisPipeline(config=config, max_workers=args.workers)
        
        # === [现代服务] 核心改造区：全频段扫描 ===
        if stock_codes is None:
            raw_list = getattr(config, 'stock_list', [])
            if isinstance(raw_list, str):
                stock_codes = [s.strip() for s in raw_list.split(',') if s.strip()]
            elif isinstance(raw_list, list):
                stock_codes = list(raw_list)
            else:
                stock_codes = []
            logger.info(f"[System] 基础自选股加载: {len(stock_codes)} 只")
        
        # 启动毁灭扫描
        if not args.dry_run:
            try:
                logger.info("📡 [现代服务] 启动全频段扫描探头...")
                panic_targets = scan_for_destruction(limit=3)
                added = 0
                for code in panic_targets:
                    if code not in stock_codes:
                        stock_codes.append(code)
                        added += 1
                        logger.info(f"➕ [自动捕获] {code} 已加入毁灭分析队列")
            except Exception as e:
                logger.error(f"❌ 扫描模块故障: {e}")

        # 运行分析
        results = pipeline.run(
            stock_codes=stock_codes,
            dry_run=args.dry_run,
            send_notification=not args.no_notify
        )

        # 大盘复盘
        market_report = ""
        if config.market_review_enabled and not args.no_market_review:
            # 延迟防限流
            time.sleep(getattr(config, 'analysis_delay', 2))
            review_result = run_market_review(
                notifier=pipeline.notifier,
                analyzer=pipeline.analyzer,
                search_service=pipeline.search_service
            )
            if review_result:
                market_report = review_result
        
        # 结果摘要
        if results:
            logger.info("\n===== 分析结果摘要 =====")
            for r in results:
                logger.info(f"{r.name}({r.code}): {r.operation_advice}")
        
        logger.info("\n任务执行完成")

    except Exception as e:
        logger.exception(f"分析流程执行失败: {e}")

def start_bot_stream_clients(config: Config) -> None:
    pass # GitHub Action 环境不需要 Stream Client

def main() -> int:
    """主入口函数"""
    # 强制打印启动信息
    print("DEBUG: 🔌 [System] main() 函数已启动！正在初始化...", flush=True)
    
    args = parse_arguments()
    config = get_config()
    setup_logging(debug=args.debug, log_dir=config.log_dir)
    
    logger.info("=" * 60)
    logger.info("A股自选股智能分析系统 (现代服务完全体) 启动")
    logger.info("=" * 60)
    
    # 验证配置
    config.validate()
    
    # 解析股票列表
    stock_codes = None
    if args.stocks:
        stock_codes = [code.strip() for code in args.stocks.split(',') if code.strip()]
    
    try:
        if args.market_review:
            logger.info("模式: 仅大盘复盘")
            # ... (简化的复盘逻辑)
            notifier = NotificationService()
            analyzer = GeminiAnalyzer(api_key=config.gemini_api_key) if config.gemini_api_key else None
            run_market_review(notifier, analyzer, None)
            return 0
        
        # 正常运行
        run_full_analysis(config, args, stock_codes)
        return 0
        
    except Exception as e:
        logger.exception(f"程序执行失败: {e}")
        return 1

# ==========================================
# ⚠️ 苍天，这一块是你之前缺失的启动开关！
# ==========================================
if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Fatal Error: {e}")
        sys.exit(1)
