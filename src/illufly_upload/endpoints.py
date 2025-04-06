"""
文件上传服务的FastAPI接口
"""
import os
import logging
from typing import Any, Dict, List, Optional, Callable, Awaitable, Union
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, UploadFile, Query, Body
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from pydantic import BaseModel, HttpUrl

from .upload import UploadService, FileStatus
from .mcp_client import UploadMcpClient

logger = logging.getLogger(__name__)

# 定义请求模型
class WebUrlRequest(BaseModel):
    url: HttpUrl
    title: Optional[str] = None
    description: Optional[str] = ""

class UpdateMetadataRequest(BaseModel):
    """更新元数据请求"""
    metadata: Dict[str, Any]

# 定义用户类型
UserDict = Dict[str, Any]

def setup_upload_service(
    app: FastAPI,
    require_user: Callable[[], Awaitable[UserDict]],
    host: str = "localhost",
    port: int = 8000,
    prefix: str = "/api"
) -> UploadMcpClient:
    """设置上传服务 - 连接到现有的MCP服务器 (SSE方式)
    
    Args:
        app: FastAPI应用
        require_user: 获取当前用户的函数
        host: MCP服务器主机
        port: MCP服务器端口
        prefix: API前缀
        
    Returns:
        UploadMcpClient: MCP客户端
    """
    # 创建MCP客户端
    client = UploadMcpClient(
        host=host,
        port=port,
        use_stdio=False
    )
    
    router = APIRouter()
    
    @router.get("/uploads")
    async def list_files(user: UserDict = Depends(require_user), include_deleted: bool = False):
        """列出用户文件"""
        # 确保客户端已连接
        client.user_id = user["user_id"]
        files = await client.list_files(include_deleted)
        return files
    
    @router.post("/uploads")
    async def upload_file(
        file: UploadFile = File(...),
        metadata: str = Form("{}"),
        user: UserDict = Depends(require_user)
    ):
        """上传文件"""
        import json
        
        try:
            metadata_dict = json.loads(metadata)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="无效的元数据JSON格式")
        
        # 读取文件内容
        content = await file.read()
        
        # 确保客户端已连接
        client.user_id = user["user_id"]
        
        try:
            # 直接上传文件内容，不保存临时文件
            file_info = await client.upload_file_content(file.filename, content, metadata_dict)
            return file_info
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/uploads/{file_id}")
    async def get_file_info(file_id: str, user: UserDict = Depends(require_user)):
        """获取文件信息"""
        client.user_id = user["user_id"]
        try:
            file_info = await client.get_file_info(file_id)
            return file_info
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    
    @router.patch("/uploads/{file_id}")
    async def update_metadata(
        file_id: str, 
        update: UpdateMetadataRequest, 
        user: UserDict = Depends(require_user)
    ):
        """更新文件元数据"""
        client.user_id = user["user_id"]
        try:
            file_info = await client.update_metadata(file_id, update.metadata)
            return file_info
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    
    @router.delete("/uploads/{file_id}")
    async def delete_file(file_id: str, user: UserDict = Depends(require_user)):
        """删除文件"""
        client.user_id = user["user_id"]
        try:
            success = await client.delete_file(file_id)
            return {"success": success}
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    
    @router.get("/uploads/{file_id}/download")
    async def download_file(file_id: str, user: UserDict = Depends(require_user)):
        """下载文件"""
        client.user_id = user["user_id"]
        
        try:
            # 获取文件信息
            file_info = await client.get_file_info(file_id)
            
            # 下载到临时文件
            temp_dir = Path("/tmp/illufly-downloads")
            temp_dir.mkdir(exist_ok=True)
            
            temp_path = temp_dir / f"{file_id}_{file_info['original_name']}"
            
            # 保存文件到临时目录
            await client.save_to_local(file_id, str(temp_path))
            
            # 返回下载响应
            return FileResponse(
                path=temp_path,
                filename=file_info["original_name"],
                media_type=file_info.get("mime_type", "application/octet-stream")
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    
    # 注册路由
    app.include_router(router, prefix=prefix)
    
    return client


def mount_upload_service_stdio(
    app: FastAPI,
    require_user: Callable[[], Awaitable[UserDict]],
    process_command: str,
    process_args: List[str] = None,
    prefix: str = "/api"
) -> UploadMcpClient:
    """
    挂载上传服务到FastAPI应用 - 使用子进程STDIO方式
    
    通过子进程和stdio方式与MCP服务通信，推荐在主应用中使用此方法
    
    Args:
        app: FastAPI应用
        require_user: 获取当前用户的函数
        process_command: 子进程命令 (如 python 或 /usr/bin/python)
        process_args: 子进程参数列表 (如 ["-m", "illufly_upload", "--transport", "stdio"])
        prefix: API前缀
        
    Returns:
        UploadMcpClient: MCP客户端
    """
    # 创建MCP客户端 - 使用子进程方式
    client = UploadMcpClient(
        user_id="service",  # 初始使用服务级别用户ID
        process_command=process_command,
        process_args=process_args or [],
        use_stdio=True
    )
    
    # 全局共享客户端实例（单例模式）
    app.state.upload_client = client
    
    router = APIRouter()
    
    # 用于获取客户端的依赖
    async def get_upload_client():
        return app.state.upload_client
    
    @router.get("/uploads")
    async def list_files(
        user: UserDict = Depends(require_user), 
        include_deleted: bool = False,
        client: UploadMcpClient = Depends(get_upload_client)
    ):
        """列出用户文件"""
        # 使用用户的ID
        client.user_id = user["user_id"]
        try:
            files = await client.list_files(include_deleted)
            return files
        except Exception as e:
            logger.error(f"列出文件时出错: {e}")
            raise HTTPException(status_code=500, detail=f"获取文件列表失败: {str(e)}")
    
    @router.post("/uploads")
    async def upload_file(
        file: UploadFile = File(...),
        metadata: str = Form("{}"),
        user: UserDict = Depends(require_user),
        client: UploadMcpClient = Depends(get_upload_client)
    ):
        """上传文件"""
        import json
        
        try:
            metadata_dict = json.loads(metadata)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="无效的元数据JSON格式")
        
        # 读取文件内容
        content = await file.read()
        
        # 设置客户端用户ID
        client.user_id = user["user_id"]
        
        try:
            # 直接上传文件内容，不保存临时文件
            file_info = await client.upload_file_content(file.filename, content, metadata_dict)
            return file_info
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.get("/uploads/{file_id}")
    async def get_file_info(
        file_id: str, 
        user: UserDict = Depends(require_user),
        client: UploadMcpClient = Depends(get_upload_client)
    ):
        """获取文件信息"""
        client.user_id = user["user_id"]
        try:
            file_info = await client.get_file_info(file_id)
            return file_info
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    
    @router.patch("/uploads/{file_id}")
    async def update_metadata(
        file_id: str, 
        update: UpdateMetadataRequest, 
        user: UserDict = Depends(require_user),
        client: UploadMcpClient = Depends(get_upload_client)
    ):
        """更新文件元数据"""
        client.user_id = user["user_id"]
        try:
            file_info = await client.update_metadata(file_id, update.metadata)
            return file_info
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    
    @router.delete("/uploads/{file_id}")
    async def delete_file(
        file_id: str, 
        user: UserDict = Depends(require_user),
        client: UploadMcpClient = Depends(get_upload_client)
    ):
        """删除文件"""
        client.user_id = user["user_id"]
        try:
            success = await client.delete_file(file_id)
            return {"success": success}
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    
    @router.get("/uploads/{file_id}/download")
    async def download_file(
        file_id: str, 
        user: UserDict = Depends(require_user),
        client: UploadMcpClient = Depends(get_upload_client)
    ):
        """下载文件"""
        client.user_id = user["user_id"]
        
        try:
            # 获取文件信息
            file_info = await client.get_file_info(file_id)
            
            # 下载到临时文件
            temp_dir = Path("/tmp/illufly-downloads")
            temp_dir.mkdir(exist_ok=True)
            
            temp_path = temp_dir / f"{file_id}_{file_info['original_name']}"
            
            # 保存文件到临时目录
            await client.save_to_local(file_id, str(temp_path))
            
            # 返回下载响应
            return FileResponse(
                path=temp_path,
                filename=file_info["original_name"],
                media_type=file_info.get("mime_type", "application/octet-stream")
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    
    # 注册路由
    app.include_router(router, prefix=prefix)
    
    # 在应用关闭时关闭客户端
    @app.on_event("shutdown")
    async def close_upload_client():
        logger.info("关闭MCP客户端连接...")
        await app.state.upload_client.close()
    
    return client


def mount_upload_service(
    app: FastAPI,
    require_user: Callable[[], Awaitable[UserDict]],
    host: str = "localhost",
    port: int = 8000,
    prefix: str = "/api",
) -> UploadMcpClient:
    """
    挂载上传服务到FastAPI应用 - 使用SSE方式连接
    
    此方法保留用于向后兼容，推荐使用 mount_upload_service_stdio 代替
    """
    # 直接使用setup_upload_service连接到MCP服务器
    return setup_upload_service(
        app=app,
        require_user=require_user,
        host=host,
        port=port,
        prefix=prefix
    )
