#!/usr/bin/env python
"""
文件上传服务主入口

默认启动MCP服务器，支持通过命令行参数配置
"""

import os
import sys
import asyncio
import click
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("illufly_upload")


@click.command()
@click.option("--base-dir", default="./storage", help="文件存储根目录")
@click.option("--max-file-size", default=10 * 1024 * 1024, help="单个文件最大大小（字节）")
@click.option("--max-total-size", default=100 * 1024 * 1024, help="每个用户最大存储空间（字节）")
@click.option(
    "--extensions",
    default=None,
    help="允许的文件扩展名，以逗号分隔"
)
@click.option(
    "--port", 
    default=8000, 
    help="HTTP服务监听端口（仅当使用FastAPI或SSE传输时有效）"
)
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse", "fastapi"]),
    default="stdio",
    help="传输类型: stdio (标准MCP STDIO传输)、sse (标准MCP SSE传输)、fastapi (模拟FastAPI服务用于测试)"
)
def main(base_dir: str, max_file_size: int, max_total_size: int, extensions: str, port: int, transport: str):
    """启动文件上传服务
    
    默认启动MCP服务器，支持多种传输方式
    """
    # 解析允许的文件扩展名
    allowed_extensions = None
    if extensions:
        allowed_extensions = [ext.strip() for ext in extensions.split(",")]
    
    # 创建存储目录
    storage_dir = Path(base_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("启动 Illufly Upload 服务")
    logger.info(f"存储目录: {base_dir}")
    
    # 根据传输类型选择不同的服务启动方式
    if transport == "fastapi":
        logger.info(f"启动测试FastAPI服务 - 监听: 0.0.0.0:{port}")
        start_fastapi_server(
            base_dir=base_dir,
            max_file_size=max_file_size,
            max_total_size_per_user=max_total_size,
            allowed_extensions=allowed_extensions,
            port=port
        )
    else:
        logger.info(f"启动MCP服务 - 传输类型: {transport}")
        start_mcp_server(
            base_dir=base_dir,
            max_file_size=max_file_size,
            max_total_size_per_user=max_total_size,
            allowed_extensions=allowed_extensions,
            port=port,
            transport=transport
        )


def start_mcp_server(
    base_dir: str,
    max_file_size: int,
    max_total_size_per_user: int,
    allowed_extensions: list = None,
    port: int = 8000,
    transport: str = "stdio"
):
    """启动MCP服务器
    
    Args:
        base_dir: 文件存储根目录
        max_file_size: 单个文件最大大小（字节）
        max_total_size_per_user: 每个用户最大存储空间（字节）
        allowed_extensions: 允许的文件扩展名列表
        port: 服务监听端口（仅SSE模式有效）
        transport: 传输类型 (stdio或sse)
    """
    from .mcp_server import create_mcp_server
    
    # 创建MCP服务器
    mcp = create_mcp_server(
        base_dir=base_dir,
        max_file_size=max_file_size,
        max_total_size_per_user=max_total_size_per_user,
        allowed_extensions=allowed_extensions
    )
    
    # 根据传输类型启动服务器
    if transport == "sse":
        logger.info(f"使用SSE传输 - 监听 0.0.0.0:{port}")
        import uvicorn
        
        app = mcp.sse_app()
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        logger.info("使用STDIO传输")
        asyncio.run(mcp.run_stdio_async())


def start_fastapi_server(
    base_dir: str,
    max_file_size: int,
    max_total_size_per_user: int,
    allowed_extensions: list = None,
    port: int = 8000
):
    """启动测试用FastAPI服务器
    
    创建一个与内部MCP子进程通信的FastAPI应用程序，用于测试和验证API功能
    
    Args:
        base_dir: 文件存储根目录
        max_file_size: 单个文件最大大小（字节）
        max_total_size_per_user: 每个用户最大存储空间（字节）
        allowed_extensions: 允许的文件扩展名列表
        port: 服务监听端口
    """
    import sys
    import uvicorn
    import socket
    from fastapi import FastAPI, Depends, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    
    # 查找可用端口，避免端口冲突
    def find_free_port(start_port):
        """查找可用端口，从指定端口开始尝试"""
        current_port = start_port
        while current_port < start_port + 100:  # 最多尝试100个端口
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind(('0.0.0.0', current_port))
                    return current_port
            except OSError:
                logger.warning(f"端口 {current_port} 已被占用，尝试下一个端口")
                current_port += 1
        raise RuntimeError(f"无法找到可用端口（尝试范围：{start_port}-{start_port+99}）")
    
    # 确保使用可用的端口
    try:
        port = find_free_port(port)
        logger.info(f"找到可用端口: {port}")
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)
    
    # 创建FastAPI应用
    app = FastAPI(
        title="文件上传服务",
        description="文件上传管理API（测试用）",
        version="0.1.0",
        docs_url="/docs",  # 使用标准的/docs路径
    )
    
    # 添加CORS中间件，允许前端访问
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 简单的用户认证函数，始终返回default用户
    async def always_default_user():
        """固定返回default用户，仅用于测试"""
        return {"user_id": "default"}
    
    # 准备MCP子进程启动命令
    process_command = sys.executable  # 当前Python解释器路径
    process_args = [
        "-m", "illufly_upload", 
        "--transport", "stdio",
        "--base-dir", base_dir,
        f"--max-file-size={max_file_size}",
        f"--max-total-size={max_total_size_per_user}"
    ]
    
    if allowed_extensions:
        extensions_str = ",".join(allowed_extensions)
        process_args.append(f"--extensions={extensions_str}")
    
    # 挂载文件上传服务到FastAPI应用
    from .endpoints import mount_upload_service_stdio
    
    logger.info(f"启动MCP子进程: {process_command} {' '.join(process_args)}")
    
    # 使用stdio方式连接到MCP子进程
    upload_client = mount_upload_service_stdio(
        app=app,
        require_user=always_default_user,
        process_command=process_command,
        process_args=process_args,
        prefix="/api"
    )
    
    # 系统信息端点
    @app.get("/info")
    async def get_info():
        """获取系统信息"""
        return {
            "service": "文件上传服务（测试模式）",
            "version": "0.1.0",
            "storage_dir": str(Path(base_dir).absolute()),
            "max_file_size": max_file_size,
            "max_total_size": max_total_size_per_user,
            "allowed_extensions": allowed_extensions,
            "api_endpoints": {
                "文件列表": "/api/uploads",
                "文件上传": "/api/uploads",
                "文件信息": "/api/uploads/{file_id}",
                "更新元数据": "/api/uploads/{file_id}",
                "删除文件": "/api/uploads/{file_id}",
                "下载文件": "/api/uploads/{file_id}/download"
            }
        }
    
    # 提供根路径访问
    @app.get("/")
    async def root():
        """返回API根路径文档链接"""
        return {
            "message": "文件上传服务API",
            "docs": f"http://localhost:{port}/docs",
            "info": f"http://localhost:{port}/info"
        }
    
    # 启动FastAPI服务
    os.environ["MCP_DEBUG"] = "1"  # 设置MCP调试模式，增加日志输出
    logger.info(f"启动FastAPI服务 - 监听: 0.0.0.0:{port}")
    logger.info(f"API文档地址: http://localhost:{port}/docs")
    
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main() 