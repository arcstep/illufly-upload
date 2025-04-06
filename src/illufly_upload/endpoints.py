from typing import List, Dict, Any, Optional, Tuple, Callable
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Body, FastAPI
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
import logging
import os
import time
from pathlib import Path
from pydantic import BaseModel, HttpUrl

from voidring import IndexedRocksDB

from .upload import UploadService, FileStatus, create_upload_endpoints

logger = logging.getLogger(__name__)

# 定义请求模型
class WebUrlRequest(BaseModel):
    url: HttpUrl
    title: Optional[str] = None
    description: Optional[str] = ""

def create_docs_endpoints(
    app, 
    require_user: Callable, 
    db: IndexedRocksDB,
    file_storage_dir: str = "./uploads",
    prefix: str = "/api"
) -> List[Tuple[str, str, callable]]:
    """创建文档相关的端点
    
    Args:
        app: FastAPI 应用实例
        tokens_manager: Token 管理器
        db: RocksDB 实例
        file_storage_dir: 文件存储目录
        prefix: API 前缀
        
    Returns:
        端点列表
    """
    # 初始化服务
    file_service = UploadService(file_storage_dir)
    doc_manager = DocumentManager(db, file_service)
    
    # 启动清理任务
    @app.on_event("startup")
    async def start_cleanup_task():
        # 启动文件清理任务
        file_service.start_cleanup_task()
    
    # API 启动时初始化向量检索器
    @app.on_event("startup")
    async def init_doc_retriever():
        await doc_manager.init_retriever()
    
    # 关闭时取消任务
    @app.on_event("shutdown")
    async def shutdown_tasks():
        # 取消清理任务
        file_service.cancel_cleanup_task()
    
    async def list_documents(token_claims: Dict = Depends(require_user)):
        """获取用户所有文档
        
        Args:
            token_claims: 用户Token声明（从token获取）
            
        Returns:
            文档列表
        """
        user_id = token_claims.get('user_id', None)
        if not user_id:
            raise HTTPException(status_code=401, detail="未授权")
        
        # 获取文档列表
        docs = await doc_manager.get_documents(user_id)
        
        # 转换为前端格式
        result = []
        for doc in docs:
            result.append({
                "id": doc.id,
                "title": doc.title,
                "description": doc.description,
                "type": doc.type,
                "source_type": doc.source_type,
                "source": doc.source,
                "created_at": doc.created_at,
                "chunks_count": doc.chunks_count,
                "file_url": file_service.get_download_url(user_id, doc.id) if doc.source_type == DocumentSource.UPLOAD else None
            })
        
        return result
    
    async def upload_document(
        file: UploadFile = File(...), 
        title: str = Form(None),
        description: str = Form(""),
        token_claims: Dict = Depends(require_user)
    ):
        """上传文档
        
        Args:
            file: 上传的文件
            title: 文档标题（可选，默认使用文件名）
            description: 文档描述（可选）
            token_claims: 用户Token声明（从token获取）
            
        Returns:
            上传成功的文档信息
        """
        user_id = token_claims.get('user_id', None)
        if not user_id:
            raise HTTPException(status_code=401, detail="未授权")
        
        try:
            # 保存文件
            file_info = await file_service.save_file(user_id, file)
            
            # 处理文档（切片、向量化）
            doc = await doc_manager.process_upload(
                user_id=user_id,
                file_info=file_info,
                title=title,
                description=description
            )
            
            # 返回文档信息
            return {
                "id": doc.id,
                "title": doc.title,
                "description": doc.description,
                "type": doc.type,
                "source_type": doc.source_type,
                "source": doc.source,
                "created_at": doc.created_at,
                "chunks_count": doc.chunks_count,
                "file_url": file_service.get_download_url(user_id, doc.id)
            }
            
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"上传文档失败: {str(e)}")
            raise HTTPException(status_code=500, detail="上传文档失败")
    
    async def download_document(
        doc_id: str, 
        token_claims: Dict = Depends(require_user)
    ):
        """下载文档
        
        Args:
            doc_id: 文档ID
            token_claims: 用户Token声明（从token获取）
            
        Returns:
            文件内容
        """
        user_id = token_claims.get('user_id', None)
        if not user_id:
            raise HTTPException(status_code=401, detail="未授权")
        
        # 获取文档
        doc = await doc_manager.get_document(user_id, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="文档不存在")
        
        # 如果是网页文档，返回错误
        if doc.source_type == DocumentSource.WEB:
            raise HTTPException(status_code=400, detail="网页文档不支持下载，请访问原始URL")
        
        # 获取文件路径
        file_path = Path(doc.file_path)
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="文件不存在")
        
        # 返回文件
        return FileResponse(
            path=file_path,
            filename=f"{doc.title}.{doc.type}",
            media_type=file_service.get_file_mimetype(file_path.name)
        )
    
    async def delete_document(
        doc_id: str, 
        token_claims: Dict = Depends(require_user)
    ):
        """删除文档
        
        Args:
            doc_id: 文档ID
            token_claims: 用户Token声明（从token获取）
            
        Returns:
            删除结果
        """
        user_id = token_claims.get('user_id', None)
        if not user_id:
            raise HTTPException(status_code=401, detail="未授权")
        
        # 删除文档及切片
        result = await doc_manager.delete_document(user_id, doc_id)
        if not result:
            raise HTTPException(status_code=404, detail="文档不存在")
        
        return {"success": True}
    
    # 返回端点列表
    return [
        ("get", f"{prefix}/docs", list_documents),
        ("post", f"{prefix}/docs/upload", upload_document),
        ("delete", f"{prefix}/docs/{{doc_id}}", delete_document),
        ("get", f"{prefix}/docs/{{doc_id}}/download", download_document),
    ]

def mount_upload_service(
    app: FastAPI,
    require_user,
    base_dir: str = "./uploads",
    max_file_size: int = 10 * 1024 * 1024,  # 10MB
    max_total_size_per_user: int = 100 * 1024 * 1024,  # 100MB
    allowed_extensions: list = None,
    prefix: str = "/api"
):
    """设置文件上传服务
    
    Args:
        app: FastAPI 应用实例
        require_user: 用户鉴权函数，需返回包含 user_id 的字典
        base_dir: 文件存储根目录
        max_file_size: 单个文件最大大小
        max_total_size_per_user: 每个用户允许的最大存储总大小
        allowed_extensions: 允许的文件扩展名列表
        prefix: API 前缀
        
    Returns:
        UploadService 实例
    """
    # 创建上传服务
    upload_service = UploadService(
        base_dir=base_dir,
        max_file_size=max_file_size,
        max_total_size_per_user=max_total_size_per_user,
        allowed_extensions=allowed_extensions
    )
    
    # 创建上传端点
    create_upload_endpoints(app, require_user, upload_service, prefix)
    
    return upload_service
