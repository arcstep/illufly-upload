from typing import Dict, List, Any, Optional
import asyncio
from pathlib import Path
import aiofiles
import aiohttp
import mimetypes
import os

from .upload import UploadService, FileStatus

class UploadClient:
    """上传客户端 - SDK接口
    
    提供直接的文件操作API，适合SDK集成
    """
    
    def __init__(
        self, 
        base_dir: str,
        user_id: str = "default",
        max_file_size: int = 10 * 1024 * 1024,  # 默认10MB
        max_total_size_per_user: int = 100 * 1024 * 1024,  # 默认100MB
        allowed_extensions: List[str] = None
    ):
        """初始化上传客户端
        
        Args:
            base_dir: 文件存储根目录
            user_id: 用户ID，默认为"default"
            max_file_size: 单个文件最大大小
            max_total_size_per_user: 每个用户允许的最大存储空间
            allowed_extensions: 允许的文件扩展名列表
        """
        self.service = UploadService(
            base_dir=base_dir,
            max_file_size=max_file_size,
            max_total_size_per_user=max_total_size_per_user,
            allowed_extensions=allowed_extensions
        )
        self.user_id = user_id
    
    async def upload_file(self, file_path: str, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """上传文件
        
        Args:
            file_path: 文件路径
            metadata: 文件元数据
            
        Returns:
            文件信息
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        # 创建模拟的UploadFile对象
        class MockUploadFile:
            def __init__(self, path):
                self.filename = path.name
                self._path = path
                self._file = None
            
            async def read(self, size=-1):
                if self._file is None:
                    self._file = await aiofiles.open(self._path, 'rb')
                return await self._file.read(size)
            
            async def close(self):
                if self._file is not None:
                    await self._file.close()
        
        try:
            mock_file = MockUploadFile(file_path)
            return await self.service.save_file(self.user_id, mock_file, metadata)
        finally:
            await mock_file.close()
    
    async def list_files(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        """列出用户文件
        
        Args:
            include_deleted: 是否包含已删除文件
            
        Returns:
            文件信息列表
        """
        return await self.service.list_files(self.user_id, include_deleted)
    
    async def get_file_info(self, file_id: str) -> Optional[Dict[str, Any]]:
        """获取文件信息
        
        Args:
            file_id: 文件ID
            
        Returns:
            文件信息
        """
        return await self.service.get_file(self.user_id, file_id)
    
    async def update_metadata(self, file_id: str, metadata: Dict[str, Any]) -> bool:
        """更新文件元数据
        
        Args:
            file_id: 文件ID
            metadata: 新的元数据
            
        Returns:
            是否更新成功
        """
        return await self.service.update_metadata(self.user_id, file_id, metadata)
    
    async def delete_file(self, file_id: str) -> bool:
        """删除文件
        
        Args:
            file_id: 文件ID
            
        Returns:
            是否删除成功
        """
        return await self.service.delete_file(self.user_id, file_id)
    
    def get_file_path(self, file_id: str) -> str:
        """获取文件在服务器上的路径
        
        Args:
            file_id: 文件ID
            
        Returns:
            文件路径
        """
        return str(self.service.get_file_path(self.user_id, file_id))
    
    async def save_to_local(self, file_id: str, target_path: str) -> bool:
        """将文件保存到本地
        
        Args:
            file_id: 文件ID
            target_path: 目标保存路径
            
        Returns:
            是否保存成功
        """
        file_info = await self.service.get_file(self.user_id, file_id)
        if not file_info or file_info.get("status") != FileStatus.ACTIVE:
            return False
        
        file_path = Path(file_info["path"])
        if not file_path.exists():
            return False
        
        # 复制文件
        target_path = Path(target_path)
        os.makedirs(target_path.parent, exist_ok=True)
        
        async with aiofiles.open(file_path, 'rb') as src_file:
            content = await src_file.read()
            
        async with aiofiles.open(target_path, 'wb') as dst_file:
            await dst_file.write(content)
        
        return True
    
    async def close(self):
        """关闭客户端（释放资源）"""
        pass  # 当前实现不需要特别的清理操作

# 同步包装器，便于非异步代码调用
class SyncUploadClient:
    """同步上传客户端
    
    UploadClient的同步包装，方便在非异步代码中使用
    """
    
    def __init__(
        self, 
        base_dir: str,
        user_id: str = "default",
        max_file_size: int = 10 * 1024 * 1024,
        max_total_size_per_user: int = 100 * 1024 * 1024,
        allowed_extensions: List[str] = None
    ):
        """初始化同步上传客户端
        
        Args:
            base_dir: 文件存储根目录
            user_id: 用户ID，默认为"default"
            max_file_size: 单个文件最大大小
            max_total_size_per_user: 每个用户允许的最大存储空间
            allowed_extensions: 允许的文件扩展名列表
        """
        self._client = UploadClient(
            base_dir=base_dir,
            user_id=user_id,
            max_file_size=max_file_size,
            max_total_size_per_user=max_total_size_per_user,
            allowed_extensions=allowed_extensions
        )
        self._loop = asyncio.new_event_loop()
    
    def _run_async(self, coro):
        """运行异步方法并返回结果"""
        return self._loop.run_until_complete(coro)
    
    def upload_file(self, file_path: str, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """上传文件（同步版本）"""
        return self._run_async(self._client.upload_file(file_path, metadata))
    
    def list_files(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        """列出用户文件（同步版本）"""
        return self._run_async(self._client.list_files(include_deleted))
    
    def get_file_info(self, file_id: str) -> Optional[Dict[str, Any]]:
        """获取文件信息（同步版本）"""
        return self._run_async(self._client.get_file_info(file_id))
    
    def update_metadata(self, file_id: str, metadata: Dict[str, Any]) -> bool:
        """更新文件元数据（同步版本）"""
        return self._run_async(self._client.update_metadata(file_id, metadata))
    
    def delete_file(self, file_id: str) -> bool:
        """删除文件（同步版本）"""
        return self._run_async(self._client.delete_file(file_id))
    
    def get_file_path(self, file_id: str) -> str:
        """获取文件在服务器上的路径（同步版本）"""
        return self._client.get_file_path(file_id)
    
    def save_to_local(self, file_id: str, target_path: str) -> bool:
        """将文件保存到本地（同步版本）"""
        return self._run_async(self._client.save_to_local(file_id, target_path))
    
    def close(self):
        """关闭客户端"""
        self._run_async(self._client.close())
        self._loop.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close() 