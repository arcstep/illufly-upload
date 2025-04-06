from typing import List, Dict, Any, Optional
from pathlib import Path
import os
import shutil
import uuid
import time
import aiofiles
import logging
import mimetypes
import asyncio
import json
from fastapi import UploadFile, HTTPException, Depends, APIRouter, File, Form

logger = logging.getLogger(__name__)

class FileStatus:
    """文件状态枚举"""
    ACTIVE = "active"      # 活跃文件
    DELETED = "deleted"    # 已删除文件

class UploadService:
    """文件存储服务
    
    按用户分目录存储文件，提供上传、下载、删除和列表查询功能。
    支持元数据管理和文件服务。
    """
    
    def __init__(
        self, 
        base_dir: str, 
        max_file_size: int = 10 * 1024 * 1024,  # 默认10MB 
        max_total_size_per_user: int = 100 * 1024 * 1024,  # 默认100MB
        allowed_extensions: List[str] = None
    ):
        """初始化文件存储服务
        
        Args:
            base_dir: 文件存储根目录
            max_file_size: 单个文件最大大小（字节），默认10MB
            max_total_size_per_user: 每个用户允许的最大存储总大小，默认100MB
            allowed_extensions: 允许的文件扩展名列表，默认为None表示允许所有扩展名
        """
        self.base_dir = Path(base_dir)
        self.files_dir = self.base_dir / "files"
        self.meta_dir = self.base_dir / "meta"
        
        # 创建目录
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        
        self.max_file_size = max_file_size
        self.max_total_size_per_user = max_total_size_per_user
        self.allowed_extensions = allowed_extensions or [
            '.ppt', '.pptx',
            '.rmd', '.md', '.mdx', 'markdown',
            '.pdf', '.doc', '.docx', '.txt',
            '.jpg', '.jpeg', '.png',
            '.csv', '.xlsx', '.xls'
        ]
        
        # 文件MIME类型映射
        self._mime_types = {
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.txt': 'text/plain',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.csv': 'text/csv',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xls': 'application/vnd.ms-excel',
        }
    
    def get_user_files_dir(self, user_id: str) -> Path:
        """获取用户文件目录
        
        Args:
            user_id: 用户ID
            
        Returns:
            用户文件目录路径
        """
        user_dir = self.files_dir / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    
    def get_user_meta_dir(self, user_id: str) -> Path:
        """获取用户元数据目录
        
        Args:
            user_id: 用户ID
            
        Returns:
            用户元数据目录路径
        """
        user_meta_dir = self.meta_dir / user_id
        user_meta_dir.mkdir(parents=True, exist_ok=True)
        return user_meta_dir
    
    def get_file_path(self, user_id: str, file_id: str) -> Path:
        """获取文件路径
        
        Args:
            user_id: 用户ID
            file_id: 文件ID
            
        Returns:
            文件路径
        """
        return self.get_user_files_dir(user_id) / file_id
    
    def get_metadata_path(self, user_id: str, file_id: str) -> Path:
        """获取文件元数据路径
        
        Args:
            user_id: 用户ID
            file_id: 文件ID
            
        Returns:
            文件元数据路径
        """
        return self.get_user_meta_dir(user_id) / f"{file_id}.json"
    
    def generate_file_id(self, original_filename: str) -> str:
        """生成文件ID
        
        Args:
            original_filename: 原始文件名
            
        Returns:
            文件ID，格式为：uuid + 文件扩展名
        """
        _, ext = os.path.splitext(original_filename)
        return f"{uuid.uuid4()}{ext}"
    
    def is_valid_file_type(self, file_name: str) -> bool:
        """检查文件类型是否有效
        
        Args:
            file_name: 文件名
            
        Returns:
            文件类型是否有效
        """
        _, ext = os.path.splitext(file_name)
        return ext.lower() in self.allowed_extensions
    
    def get_file_extension(self, file_name: str) -> str:
        """获取文件扩展名
        
        Args:
            file_name: 文件名
            
        Returns:
            文件扩展名，如 '.pdf', '.doc'
        """
        _, ext = os.path.splitext(file_name)
        return ext.lower()
    
    def get_file_type(self, file_name: str) -> str:
        """获取文件类型
        
        Args:
            file_name: 文件名
            
        Returns:
            文件类型，如 'pdf', 'doc', 'docx', 'txt'
        """
        _, ext = os.path.splitext(file_name)
        return ext.lower()[1:]  # 去掉点号
    
    def get_file_mimetype(self, file_name: str) -> str:
        """获取文件MIME类型
        
        Args:
            file_name: 文件名
            
        Returns:
            文件MIME类型
        """
        _, ext = os.path.splitext(file_name)
        return self._mime_types.get(ext.lower(), 'application/octet-stream')
    
    async def calculate_user_storage_usage(self, user_id: str) -> int:
        """计算用户已使用的存储空间
        
        Args:
            user_id: 用户ID
            
        Returns:
            已使用的字节数
        """
        total_size = 0
        files = await self.list_files(user_id)
        
        for file_info in files:
            if file_info.get("status") == FileStatus.ACTIVE:
                total_size += file_info.get("size", 0)
        
        return total_size
    
    async def save_file(
        self, 
        user_id: str, 
        file: UploadFile,
        metadata: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """保存文件
        
        Args:
            user_id: 用户ID
            file: 上传的文件
            metadata: 额外的元数据
            
        Returns:
            文件信息，包含ID、原始文件名、大小等
            
        Raises:
            ValueError: 文件大小超过限制、文件类型不支持或用户存储空间不足
        """
        # 检查文件类型
        if not self.is_valid_file_type(file.filename):
            raise ValueError(f"不支持的文件类型: {file.filename}")
        
        # 检查用户存储空间
        current_usage = await self.calculate_user_storage_usage(user_id)
        
        # 生成文件ID和路径
        file_id = self.generate_file_id(file.filename)
        file_path = self.get_file_path(user_id, file_id)
        meta_path = self.get_metadata_path(user_id, file_id)
        
        # 保存文件
        file_size = 0
        async with aiofiles.open(file_path, 'wb') as out_file:
            # 分块读取并写入文件
            while content := await file.read(1024 * 1024):  # 每次读取1MB
                file_size += len(content)
                if file_size > self.max_file_size:
                    await out_file.close()
                    os.remove(file_path)
                    raise ValueError(f"文件大小超过限制: {self.max_file_size} bytes")
                await out_file.write(content)
        
        # 检查总存储空间
        if current_usage + file_size > self.max_total_size_per_user:
            os.remove(file_path)
            raise ValueError(f"用户存储空间不足，已使用 {current_usage} bytes，限制 {self.max_total_size_per_user} bytes")
        
        # 生成文件信息
        file_info = {
            "id": file_id,
            "original_name": file.filename,
            "size": file_size,
            "type": self.get_file_type(file.filename),
            "extension": self.get_file_extension(file.filename),
            "path": str(file_path),
            "created_at": time.time(),
            "updated_at": time.time(),
            "status": FileStatus.ACTIVE,
        }
        
        # 添加额外元数据
        if metadata:
            file_info.update(metadata)
        
        # 保存元数据
        async with aiofiles.open(meta_path, 'w') as meta_file:
            await meta_file.write(json.dumps(file_info, ensure_ascii=False))
        
        return file_info
    
    async def get_file(self, user_id: str, file_id: str) -> Optional[Dict[str, Any]]:
        """获取文件信息
        
        Args:
            user_id: 用户ID
            file_id: 文件ID
            
        Returns:
            文件信息，如果文件不存在则返回None
        """
        meta_path = self.get_metadata_path(user_id, file_id)
        
        if not meta_path.exists():
            return None
        
        # 读取元数据
        async with aiofiles.open(meta_path, 'r') as meta_file:
            meta_content = await meta_file.read()
            file_info = json.loads(meta_content)
            
            # 检查文件是否存在
            file_path = Path(file_info["path"])
            if not file_path.exists() and file_info.get("status") == FileStatus.ACTIVE:
                # 文件不存在但元数据显示为活跃状态，更新状态
                file_info["status"] = FileStatus.DELETED
                async with aiofiles.open(meta_path, 'w') as update_file:
                    await update_file.write(json.dumps(file_info, ensure_ascii=False))
            
            return file_info
    
    async def update_metadata(self, user_id: str, file_id: str, metadata: Dict[str, Any]) -> bool:
        """更新文件元数据
        
        Args:
            user_id: 用户ID
            file_id: 文件ID
            metadata: 新的元数据
            
        Returns:
            是否更新成功
        """
        file_info = await self.get_file(user_id, file_id)
        if not file_info or file_info.get("status") != FileStatus.ACTIVE:
            return False
        
        # 更新元数据，但保留核心字段
        core_fields = ["id", "original_name", "size", "path", "created_at", "status"]
        for key, value in metadata.items():
            if key not in core_fields:
                file_info[key] = value
        
        # 更新更新时间
        file_info["updated_at"] = time.time()
        
        # 保存元数据
        meta_path = self.get_metadata_path(user_id, file_id)
        async with aiofiles.open(meta_path, 'w') as meta_file:
            await meta_file.write(json.dumps(file_info, ensure_ascii=False))
        
        return True
    
    async def delete_file(self, user_id: str, file_id: str) -> bool:
        """删除文件
        
        Args:
            user_id: 用户ID
            file_id: 文件ID
            
        Returns:
            是否删除成功
        """
        file_info = await self.get_file(user_id, file_id)
        if not file_info or file_info.get("status") != FileStatus.ACTIVE:
            return False
        
        file_path = Path(file_info["path"])
        meta_path = self.get_metadata_path(user_id, file_id)
        
        success = True
        
        # 删除文件
        if file_path.exists():
            try:
                os.remove(file_path)
            except Exception as e:
                logger.error(f"删除文件失败: {file_path}, 错误: {e}")
                success = False
        
        # 更新元数据状态
        file_info["status"] = FileStatus.DELETED
        file_info["updated_at"] = time.time()
        
        # 保存元数据（保留记录）
        async with aiofiles.open(meta_path, 'w') as meta_file:
            await meta_file.write(json.dumps(file_info, ensure_ascii=False))
        
        return success
    
    async def list_files(self, user_id: str, include_deleted: bool = False) -> List[Dict[str, Any]]:
        """列出用户所有文件
        
        Args:
            user_id: 用户ID
            include_deleted: 是否包含已删除文件
            
        Returns:
            文件信息列表
        """
        user_meta_dir = self.get_user_meta_dir(user_id)
        files = []
        
        # 查找所有元数据文件
        for meta_path in user_meta_dir.glob("*.json"):
            try:
                async with aiofiles.open(meta_path, 'r') as meta_file:
                    meta_content = await meta_file.read()
                    file_info = json.loads(meta_content)
                    
                    # 处理删除状态
                    if file_info.get("status") == FileStatus.ACTIVE:
                        # 检查文件是否存在
                        file_path = Path(file_info["path"])
                        if not file_path.exists():
                            file_info["status"] = FileStatus.DELETED
                            async with aiofiles.open(meta_path, 'w') as update_file:
                                await update_file.write(json.dumps(file_info, ensure_ascii=False))
                    
                    # 根据筛选条件添加
                    if include_deleted or file_info.get("status") == FileStatus.ACTIVE:
                        files.append(file_info)
            except Exception as e:
                logger.error(f"读取文件元数据失败: {meta_path}, 错误: {e}")
        
        return files
    
    def get_download_url(self, user_id: str, file_id: str) -> str:
        """获取文件下载URL
        
        Args:
            user_id: 用户ID
            file_id: 文件ID
            
        Returns:
            文件下载URL
        """
        return f"/api/uploads/{file_id}/download"


def create_upload_endpoints(
    app, 
    require_user, 
    upload_service: UploadService,
    prefix: str = "/api"
) -> APIRouter:
    """创建文件上传相关的端点
    
    Args:
        app: FastAPI 应用实例
        require_user: 用户鉴权函数
        upload_service: 上传服务实例
        prefix: API 前缀
        
    Returns:
        路由对象
    """
    router = APIRouter(prefix=prefix)
    
    @router.get("/uploads")
    async def list_files(user_claims: Dict = Depends(require_user)):
        """获取用户所有文件
        
        Args:
            user_claims: 用户Token声明（从token获取）
            
        Returns:
            文件列表
        """
        user_id = user_claims.get('user_id')
        if not user_id:
            raise HTTPException(status_code=401, detail="未授权")
        
        files = await upload_service.list_files(user_id)
        
        # 转换为前端格式
        result = []
        for file_info in files:
            result.append({
                "id": file_info["id"],
                "original_name": file_info["original_name"],
                "size": file_info["size"],
                "type": file_info["type"],
                "created_at": file_info["created_at"],
                "updated_at": file_info.get("updated_at", file_info["created_at"]),
                "download_url": upload_service.get_download_url(user_id, file_info["id"]),
                # 添加其他自定义元数据
                "metadata": {k: v for k, v in file_info.items() 
                            if k not in ["id", "original_name", "size", "type", "path", 
                                        "created_at", "updated_at", "status"]}
            })
        
        return result
    
    @router.post("/uploads")
    async def upload_file(
        file: UploadFile = File(...), 
        title: str = Form(None),
        description: str = Form(None),
        user_claims: Dict = Depends(require_user)
    ):
        """上传文件
        
        Args:
            file: 上传的文件
            title: 文件标题（可选）
            description: 文件描述（可选）
            user_claims: 用户Token声明
            
        Returns:
            上传结果
        """
        user_id = user_claims.get('user_id')
        if not user_id:
            raise HTTPException(status_code=401, detail="未授权")
        
        # 准备元数据
        metadata = {}
        if title:
            metadata["title"] = title
        if description:
            metadata["description"] = description
        
        try:
            file_info = await upload_service.save_file(user_id, file, metadata)
            
            return {
                "id": file_info["id"],
                "original_name": file_info["original_name"],
                "size": file_info["size"],
                "type": file_info["type"],
                "created_at": file_info["created_at"],
                "download_url": upload_service.get_download_url(user_id, file_info["id"]),
                # 添加其他元数据
                "metadata": {k: v for k, v in file_info.items() 
                            if k not in ["id", "original_name", "size", "type", "path", 
                                        "created_at", "updated_at", "status"]}
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"上传文件失败: {str(e)}")
            raise HTTPException(status_code=500, detail="上传文件失败")
    
    @router.get("/uploads/{file_id}")
    async def get_file_info(
        file_id: str,
        user_claims: Dict = Depends(require_user)
    ):
        """获取文件信息
        
        Args:
            file_id: 文件ID
            user_claims: 用户Token声明
            
        Returns:
            文件信息
        """
        user_id = user_claims.get('user_id')
        if not user_id:
            raise HTTPException(status_code=401, detail="未授权")
        
        file_info = await upload_service.get_file(user_id, file_id)
        if not file_info or file_info.get("status") != FileStatus.ACTIVE:
            raise HTTPException(status_code=404, detail="文件不存在")
        
        return {
            "id": file_info["id"],
            "original_name": file_info["original_name"],
            "size": file_info["size"],
            "type": file_info["type"],
            "created_at": file_info["created_at"],
            "updated_at": file_info.get("updated_at", file_info["created_at"]),
            "download_url": upload_service.get_download_url(user_id, file_info["id"]),
            # 添加其他元数据
            "metadata": {k: v for k, v in file_info.items() 
                        if k not in ["id", "original_name", "size", "type", "path", 
                                    "created_at", "updated_at", "status"]}
        }
    
    @router.patch("/uploads/{file_id}")
    async def update_file_metadata(
        file_id: str,
        metadata: Dict[str, Any],
        user_claims: Dict = Depends(require_user)
    ):
        """更新文件元数据
        
        Args:
            file_id: 文件ID
            metadata: 新的元数据
            user_claims: 用户Token声明
            
        Returns:
            更新结果
        """
        user_id = user_claims.get('user_id')
        if not user_id:
            raise HTTPException(status_code=401, detail="未授权")
        
        success = await upload_service.update_metadata(user_id, file_id, metadata)
        if not success:
            raise HTTPException(status_code=404, detail="文件不存在或无法更新")
        
        # 获取更新后的文件信息
        file_info = await upload_service.get_file(user_id, file_id)
        
        return {
            "id": file_info["id"],
            "original_name": file_info["original_name"],
            "size": file_info["size"],
            "type": file_info["type"],
            "created_at": file_info["created_at"],
            "updated_at": file_info["updated_at"],
            "download_url": upload_service.get_download_url(user_id, file_info["id"]),
            # 添加其他元数据
            "metadata": {k: v for k, v in file_info.items() 
                        if k not in ["id", "original_name", "size", "type", "path", 
                                    "created_at", "updated_at", "status"]}
        }
    
    @router.delete("/uploads/{file_id}")
    async def delete_file(
        file_id: str,
        user_claims: Dict = Depends(require_user)
    ):
        """删除文件
        
        Args:
            file_id: 文件ID
            user_claims: 用户Token声明
            
        Returns:
            删除结果
        """
        user_id = user_claims.get('user_id')
        if not user_id:
            raise HTTPException(status_code=401, detail="未授权")
        
        success = await upload_service.delete_file(user_id, file_id)
        if not success:
            raise HTTPException(status_code=404, detail="文件不存在或无法删除")
        
        return {"success": True, "message": "文件已删除"}
    
    @router.get("/uploads/{file_id}/download")
    async def download_file(
        file_id: str,
        user_claims: Dict = Depends(require_user)
    ):
        """下载文件
        
        Args:
            file_id: 文件ID
            user_claims: 用户Token声明
            
        Returns:
            文件内容
        """
        from fastapi.responses import FileResponse
        
        user_id = user_claims.get('user_id')
        if not user_id:
            raise HTTPException(status_code=401, detail="未授权")
        
        file_info = await upload_service.get_file(user_id, file_id)
        if not file_info or file_info.get("status") != FileStatus.ACTIVE:
            raise HTTPException(status_code=404, detail="文件不存在")
        
        file_path = Path(file_info["path"])
        if not file_path.exists():
            # 更新元数据状态
            file_info["status"] = FileStatus.DELETED
            meta_path = upload_service.get_metadata_path(user_id, file_id)
            async with aiofiles.open(meta_path, 'w') as meta_file:
                await meta_file.write(json.dumps(file_info, ensure_ascii=False))
            
            raise HTTPException(status_code=404, detail="文件不存在")
        
        return FileResponse(
            path=file_path,
            filename=file_info["original_name"],
            media_type=upload_service.get_file_mimetype(file_info["original_name"])
        )
    
    # 添加路由到应用
    app.include_router(router)
    
    return router
