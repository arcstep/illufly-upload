#!/usr/bin/env python
"""
基于MCP规范的文件上传服务器 - 使用FastMCP简化实现
"""
import anyio
import click
import json
import base64
import os
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

from mcp.server.fastmcp import FastMCP
from fastapi import UploadFile

from .upload import UploadService, FileStatus

logger = logging.getLogger(__name__)


class MockUploadFile:
    """模拟FastAPI的UploadFile对象"""
    def __init__(self, filename, content):
        self.filename = filename
        self._content = content
        self._position = 0
    
    async def read(self, size=-1):
        if size == -1:
            return self._content[self._position:]
        else:
            start = self._position
            end = min(start + size, len(self._content))
            self._position = end
            return self._content[start:end]


def create_mcp_server(
    base_dir: str,
    max_file_size: int = 10 * 1024 * 1024,
    max_total_size_per_user: int = 100 * 1024 * 1024,
    allowed_extensions: List[str] = None
):
    """创建MCP服务器实例
    
    Args:
        base_dir: 文件存储根目录
        max_file_size: 单个文件最大大小（字节）
        max_total_size_per_user: 每个用户最大存储空间（字节）
        allowed_extensions: 允许的文件扩展名列表
    
    Returns:
        MCP服务器实例
    """
    # 创建服务对象
    upload_service = UploadService(
        base_dir=base_dir,
        max_file_size=max_file_size,
        max_total_size_per_user=max_total_size_per_user,
        allowed_extensions=allowed_extensions
    )
    
    # 确保基本目录存在
    os.makedirs(os.path.join(base_dir, "files"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "meta"), exist_ok=True)
    
    # 创建FastMCP服务器
    mcp = FastMCP("illufly-upload-service")
    
    # 列出文件工具
    @mcp.tool()
    async def list_files(user_id: str = "default", include_deleted: bool = False) -> str:
        """列出用户的所有文件
        
        Args:
            user_id: 用户ID
            include_deleted: 是否包含已删除的文件
            
        Returns:
            JSON格式的文件列表
        """
        files = await upload_service.list_files(user_id, include_deleted)
        
        # 添加下载URL
        for file in files:
            file["download_url"] = upload_service.get_download_url(user_id, file["id"])
        
        return json.dumps(files, indent=2, ensure_ascii=False)
    
    # 获取文件信息工具
    @mcp.tool()
    async def get_file_info(file_id: str, user_id: str = "default") -> str:
        """获取文件信息
        
        Args:
            file_id: 文件ID
            user_id: 用户ID
            
        Returns:
            JSON格式的文件信息
        """
        file_info = await upload_service.get_file(user_id, file_id)
        
        if not file_info:
            return json.dumps({"error": f"文件{file_id}不存在"})
        
        if file_info.get("status") != FileStatus.ACTIVE:
            return json.dumps({"error": f"文件{file_id}已删除"})
        
        # 添加下载URL
        file_info["download_url"] = upload_service.get_download_url(user_id, file_id)
        
        return json.dumps(file_info, indent=2, ensure_ascii=False)
    
    # 上传文件工具
    @mcp.tool()
    async def upload_file(file_name: str, file_content: str, user_id: str = "default", metadata: Dict[str, Any] = None) -> str:
        """上传文件
        
        Args:
            file_name: 文件名
            file_content: Base64编码的文件内容
            user_id: 用户ID
            metadata: 文件元数据
            
        Returns:
            JSON格式的文件信息
        """
        if not metadata:
            metadata = {}
            
        try:
            file_content_bytes = base64.b64decode(file_content)
        except Exception as e:
            return json.dumps({"error": f"文件内容base64解码失败: {str(e)}"})
        
        # 创建模拟的UploadFile对象
        mock_file = MockUploadFile(file_name, file_content_bytes)
        
        # 保存文件
        file_info = await upload_service.save_file(user_id, mock_file, metadata)
        
        # 添加下载URL
        file_info["download_url"] = upload_service.get_download_url(user_id, file_info["id"])
        
        return json.dumps(file_info, indent=2, ensure_ascii=False)
    
    # 更新元数据工具
    @mcp.tool()
    async def update_metadata(file_id: str, metadata: Dict[str, Any], user_id: str = "default") -> str:
        """更新文件元数据
        
        Args:
            file_id: 文件ID
            metadata: 新的元数据
            user_id: 用户ID
            
        Returns:
            JSON格式的更新结果
        """
        success = await upload_service.update_metadata(user_id, file_id, metadata)
        
        if not success:
            return json.dumps({"error": f"文件{file_id}不存在或无法更新"})
        
        # 获取更新后的文件信息
        file_info = await upload_service.get_file(user_id, file_id)
        file_info["download_url"] = upload_service.get_download_url(user_id, file_id)
        
        return json.dumps(file_info, indent=2, ensure_ascii=False)
    
    # 删除文件工具
    @mcp.tool()
    async def delete_file(file_id: str, user_id: str = "default") -> str:
        """删除文件
        
        Args:
            file_id: 文件ID
            user_id: 用户ID
            
        Returns:
            JSON格式的删除结果
        """
        success = await upload_service.delete_file(user_id, file_id)
        
        if not success:
            return json.dumps({"error": f"文件{file_id}不存在或无法删除"})
        
        return json.dumps({"success": True, "message": f"文件{file_id}已成功删除"})
    
    # 保存到本地工具
    @mcp.tool()
    async def save_to_local(file_id: str, target_path: str, user_id: str = "default") -> str:
        """将文件保存到本地路径
        
        Args:
            file_id: 文件ID
            target_path: 本地保存路径
            user_id: 用户ID
            
        Returns:
            JSON格式的保存结果
        """
        # 获取文件信息
        file_info = await upload_service.get_file(user_id, file_id)
        
        if not file_info or file_info.get("status") != FileStatus.ACTIVE:
            return json.dumps({"error": f"文件{file_id}不存在或已删除"})
        
        # 源文件路径
        src_path = Path(file_info["path"])
        if not src_path.exists():
            return json.dumps({"error": f"文件{file_id}在服务器上不存在"})
        
        # 目标路径
        target_path = Path(target_path)
        os.makedirs(target_path.parent, exist_ok=True)
        
        # 复制文件
        import shutil
        shutil.copy2(src_path, target_path)
        
        return json.dumps({"success": True, "message": f"文件已保存到: {target_path}"})
    
    # 添加文件资源 - 通过模板URL访问文件内容
    @mcp.resource("file://{user_id}/{file_id}")
    async def get_file_content(user_id: str, file_id: str) -> bytes:
        """获取文件内容
        
        Args:
            user_id: 用户ID
            file_id: 文件ID
            
        Returns:
            文件内容
        """
        # 获取文件信息
        file_info = await upload_service.get_file(user_id, file_id)
        
        if not file_info or file_info.get("status") != FileStatus.ACTIVE:
            raise ValueError(f"文件{file_id}不存在或已删除")
        
        # 文件路径
        file_path = Path(file_info["path"])
        if not file_path.exists():
            raise ValueError(f"文件{file_id}在服务器上不存在")
        
        # 读取文件内容
        with open(file_path, "rb") as f:
            return f.read()
    
    return mcp


@click.command()
@click.option("--base-dir", default="./storage", help="文件存储根目录")
@click.option("--max-file-size", default=10 * 1024 * 1024, help="单个文件最大大小（字节）")
@click.option("--max-total-size", default=100 * 1024 * 1024, help="每个用户最大存储空间（字节）")
@click.option("--port", default=31571, help="SSE传输的端口号")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse"]),
    default="stdio",
    help="传输类型",
)
def main(base_dir: str, max_file_size: int, max_total_size: int, port: int, transport: str) -> int:
    """启动MCP文件上传服务
    
    Args:
        base_dir: 文件存储根目录
        max_file_size: 单个文件最大大小（字节）
        max_total_size: 每个用户最大存储空间（字节）
        port: SSE传输的端口号
        transport: 传输类型（stdio或sse）
    
    Returns:
        状态码
    """
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    # 创建基本目录
    os.makedirs(base_dir, exist_ok=True)
    
    # 创建MCP服务器
    mcp = create_mcp_server(
        base_dir=base_dir,
        max_file_size=max_file_size,
        max_total_size_per_user=max_total_size
    )
    
    logger.info(f"启动文件上传服务 - 存储目录: {base_dir}")
    
    # 启动服务器
    if transport == "sse":
        logger.info(f"使用SSE传输 - 监听 0.0.0.0:{port}")
        import uvicorn
        from fastapi import FastAPI
        
        app = mcp.sse_app()
        uvicorn.run(app, host="0.0.0.0", port=port)
    else:
        logger.info("使用STDIO传输")
        asyncio.run(mcp.run_stdio_async())
    
    return 0


if __name__ == "__main__":
    main() 