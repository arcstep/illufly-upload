#!/usr/bin/env python
"""
独立文件上传服务模块

可以通过 python -m illufly_upload 直接启动服务
无需用户鉴权，使用 'default' 作为默认用户
"""

import os
import sys
import argparse
import uvicorn
from fastapi import FastAPI, Depends
from pathlib import Path
import logging

from .upload import UploadService
from .endpoints import mount_upload_service

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger("illufly_upload")

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="Illufly 文件上传服务")
    
    parser.add_argument(
        "--host", 
        default="127.0.0.1", 
        help="服务监听的主机地址 (默认: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=8000, 
        help="服务监听的端口 (默认: 8000)"
    )
    parser.add_argument(
        "--storage", 
        default="./storage", 
        help="文件存储目录 (默认: ./storage)"
    )
    parser.add_argument(
        "--max-file-size", 
        type=int, 
        default=10 * 1024 * 1024, 
        help="单个文件最大大小，单位字节 (默认: 10MB)"
    )
    parser.add_argument(
        "--max-total-size", 
        type=int, 
        default=100 * 1024 * 1024, 
        help="用户总存储容量，单位字节 (默认: 100MB)"
    )
    parser.add_argument(
        "--extensions", 
        help="允许的文件扩展名，以逗号分隔 (默认: .pdf,.doc,.docx,.txt,.jpg,.jpeg,.png)"
    )
    parser.add_argument(
        "--prefix", 
        default="/api", 
        help="API前缀 (默认: /api)"
    )
    
    return parser.parse_args()

def create_app(args):
    """创建FastAPI应用"""
    app = FastAPI(
        title="Illufly Upload Service",
        description="文件上传存储服务",
        version="0.1.0",
    )
    
    # 解析允许的文件扩展名
    allowed_extensions = None
    if args.extensions:
        allowed_extensions = [ext.strip() for ext in args.extensions.split(",")]
    
    # 创建存储目录
    storage_dir = Path(args.storage)
    storage_dir.mkdir(parents=True, exist_ok=True)
    
    # 默认认证函数 - 始终返回默认用户
    async def always_default_user():
        return {"user_id": "default"}
    
    # 设置上传服务
    upload_service = mount_upload_service(
        app=app,
        require_user=always_default_user,
        base_dir=args.storage,
        max_file_size=args.max_file_size,
        max_total_size_per_user=args.max_total_size,
        allowed_extensions=allowed_extensions,
        prefix=args.prefix
    )
    
    @app.get("/")
    async def root():
        """服务根路径，返回基本信息"""
        return {
            "service": "Illufly Upload Service",
            "version": "0.1.0",
            "upload_endpoint": f"{args.prefix}/uploads",
            "storage_dir": str(storage_dir.absolute()),
            "max_file_size": args.max_file_size,
            "max_total_size": args.max_total_size,
        }
    
    return app

def main():
    """主函数"""
    args = parse_args()
    
    logger.info("Starting Illufly Upload Service")
    logger.info(f"Storage directory: {args.storage}")
    logger.info(f"Listening on: {args.host}:{args.port}")
    
    app = create_app(args)
    
    # 启动服务
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info"
    )

if __name__ == "__main__":
    main() 