"""
基于MCP规范的文件上传客户端 - 参考官方示例实现
"""
import asyncio
import base64
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Union

import aiofiles
from mcp import ClientSession, StdioServerParameters 
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

# 设置更详细的日志输出
DEBUG = os.environ.get("MCP_DEBUG", "").lower() in ("1", "true", "yes")
if DEBUG:
    logging.basicConfig(level=logging.DEBUG)
    logger.setLevel(logging.DEBUG)


class UploadMcpClient:
    """基于官方MCP SDK的文件上传客户端"""
    
    def __init__(
        self,
        user_id: str = "default",
        process_command: Optional[str] = None,
        process_args: Optional[List[str]] = None,
        host: str = "localhost",
        port: int = 8000,
        use_stdio: bool = True
    ):
        """初始化MCP客户端
        
        Args:
            user_id: 用户ID
            process_command: 子进程命令（用于stdio传输）
            process_args: 子进程参数（用于stdio传输）
            host: 服务器主机地址（用于SSE传输）
            port: 服务器端口（用于SSE传输）
            use_stdio: 是否使用stdio传输
        """
        self.user_id = user_id
        self._session = None
        self._exit_stack = None
        
        # 保存传输相关参数
        self._host = host
        self._port = port
        self._process_command = process_command
        self._process_args = process_args or []
        self._use_stdio = use_stdio
        
        # 记录初始化信息
        logger.info(f"初始化MCP客户端: user_id={user_id}, use_stdio={use_stdio}")
        if use_stdio:
            logger.info(f"准备使用子进程: {process_command} {' '.join(process_args)}")
        else:
            logger.info(f"准备连接到服务器: {host}:{port}")
    
    async def _ensure_connected(self):
        """确保连接到MCP服务器"""
        if self._session is None:
            from contextlib import AsyncExitStack
            
            logger.debug("创建MCP连接...")
            self._exit_stack = AsyncExitStack()
            
            # 创建传输层
            if self._use_stdio:
                if not self._process_command:
                    raise ValueError("使用stdio传输时必须提供process_command")
                
                logger.debug(f"创建stdio连接: {self._process_command} {' '.join(self._process_args)}")
                server_params = StdioServerParameters(
                    command=self._process_command,
                    args=self._process_args
                )
                
                try:
                    stdio_transport = await self._exit_stack.enter_async_context(
                        stdio_client(server_params)
                    )
                    read, write = stdio_transport
                    
                    logger.debug("创建ClientSession...")
                    self._session = await self._exit_stack.enter_async_context(
                        ClientSession(read, write)
                    )
                    logger.debug("初始化ClientSession...")
                    await self._session.initialize()
                    logger.info("MCP客户端连接成功")
                except Exception as e:
                    logger.error(f"连接MCP服务器失败: {str(e)}")
                    if self._exit_stack:
                        await self._exit_stack.aclose()
                        self._exit_stack = None
                    raise
            else:
                # SSE传输暂不实现
                logger.error("SSE传输暂不支持")
                raise NotImplementedError("SSE传输暂不支持")
    
    async def _call_tool_safe(self, tool_name: str, params: Dict[str, Any]) -> Any:
        """安全地调用MCP工具并处理结果
        
        Args:
            tool_name: 工具名称
            params: 参数
            
        Returns:
            工具返回的结果（已解析为Python对象）
            
        Raises:
            ValueError: 如果调用失败
        """
        await self._ensure_connected()
        
        try:
            logger.debug(f"调用工具: {tool_name}, 参数: {json.dumps(params)}")
            result = await self._session.call_tool(tool_name, params)
            
            # 记录结果类型信息，便于调试
            logger.debug(f"工具返回类型: {type(result)}")
            
            # 获取结果中的实际内容
            # CallToolResult对象结构: 
            # - content: 列表，包含TextContent对象
            # - TextContent对象有text属性，包含实际的JSON字符串
            if hasattr(result, 'content') and result.content and hasattr(result.content[0], 'text'):
                json_str = result.content[0].text
                logger.debug(f"提取到结果内容（前100字符）: {json_str[:100]}...")
            else:
                # 如果不是预期的结构，尝试直接使用result
                logger.debug(f"无法从结果中提取内容，尝试直接使用结果: {result!r}")
                json_str = result
            
            # 检查是否为错误消息（非JSON格式）
            if json_str and isinstance(json_str, str) and json_str.startswith('Error executing tool'):
                logger.warning(f"服务器返回错误消息: {json_str}")
                # 提取错误消息，通常格式为"Error executing tool xxx: 具体错误信息"
                error_parts = json_str.split(':', 1)
                error_msg = error_parts[1].strip() if len(error_parts) > 1 else json_str
                raise ValueError(error_msg)
            
            # 解析JSON结果
            try:
                parsed_result = json.loads(json_str)
                return parsed_result
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"解析结果失败: {str(e)}, 原始结果: {json_str!r}")
                # 如果解析失败，把原始消息当作错误信息返回
                if isinstance(json_str, str):
                    raise ValueError(json_str)
                else:
                    raise ValueError(f"无法解析工具返回的结果: {str(e)}")
        except Exception as e:
            logger.error(f"调用工具失败: {tool_name}, 错误: {str(e)}", exc_info=DEBUG)
            raise ValueError(f"调用工具失败: {str(e)}")
    
    async def list_files(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        """列出文件
        
        Args:
            include_deleted: 是否包含已删除的文件
            
        Returns:
            文件列表
        """
        logger.info(f"列出文件 (用户: {self.user_id}, 包含已删除: {include_deleted})")
        
        result = await self._call_tool_safe(
            "list_files",
            {
                "user_id": self.user_id,
                "include_deleted": include_deleted
            }
        )
        
        logger.debug(f"找到 {len(result)} 个文件")
        return result
    
    async def get_file_info(self, file_id: str) -> Dict[str, Any]:
        """获取文件信息
        
        Args:
            file_id: 文件ID
            
        Returns:
            文件信息
            
        Raises:
            ValueError: 如果文件不存在或已删除
        """
        logger.info(f"获取文件信息 (用户: {self.user_id}, 文件ID: {file_id})")
        
        result = await self._call_tool_safe(
            "get_file_info",
            {
                "user_id": self.user_id,
                "file_id": file_id
            }
        )
        
        if "error" in result:
            logger.warning(f"获取文件信息失败: {result['error']}")
            raise ValueError(result["error"])
            
        logger.debug(f"文件信息: {json.dumps(result)}")
        return result
    
    async def upload_file_content(self, filename: str, content: bytes, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """直接上传文件内容，无需保存为临时文件
        
        Args:
            filename: 文件名
            content: 文件内容（二进制）
            metadata: 文件元数据
            
        Returns:
            文件信息
            
        Raises:
            ValueError: 如果上传失败
        """
        logger.info(f"上传文件 (用户: {self.user_id}, 文件名: {filename}, 大小: {len(content)} 字节)")
        
        # Base64编码
        content_base64 = base64.b64encode(content).decode('utf-8')
        logger.debug(f"文件内容已Base64编码，长度: {len(content_base64)}")
        
        result = await self._call_tool_safe(
            "upload_file",
            {
                "user_id": self.user_id,
                "file_name": filename,
                "file_content": content_base64,
                "metadata": metadata or {}
            }
        )
        
        if "error" in result:
            logger.warning(f"上传文件失败: {result['error']}")
            raise ValueError(result["error"])
            
        logger.info(f"文件上传成功: {filename} -> {result.get('id', 'unknown')}")
        return result
    
    async def upload_file(self, file_path: str, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """上传文件（从本地路径）
        
        Args:
            file_path: 文件路径
            metadata: 文件元数据
            
        Returns:
            文件信息
            
        Raises:
            FileNotFoundError: 如果文件不存在
            ValueError: 如果上传失败
        """
        file_path = Path(file_path)
        logger.info(f"从路径上传文件: {file_path}")
        
        if not file_path.exists():
            logger.error(f"文件不存在: {file_path}")
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        # 读取文件内容
        try:
            async with aiofiles.open(file_path, 'rb') as file:
                content = await file.read()
                logger.debug(f"文件读取成功: {file_path}, 大小: {len(content)} 字节")
        except Exception as e:
            logger.error(f"读取文件失败: {file_path}, 错误: {str(e)}")
            raise ValueError(f"读取文件失败: {str(e)}")
        
        # 使用文件内容上传
        return await self.upload_file_content(file_path.name, content, metadata)
    
    async def update_metadata(self, file_id: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """更新文件元数据
        
        Args:
            file_id: 文件ID
            metadata: 新的元数据
            
        Returns:
            更新后的文件信息
            
        Raises:
            ValueError: 如果文件不存在或更新失败
        """
        logger.info(f"更新文件元数据 (用户: {self.user_id}, 文件ID: {file_id})")
        
        result = await self._call_tool_safe(
            "update_metadata",
            {
                "user_id": self.user_id,
                "file_id": file_id,
                "metadata": metadata
            }
        )
        
        if "error" in result:
            logger.warning(f"更新元数据失败: {result['error']}")
            raise ValueError(result["error"])
            
        logger.info(f"元数据更新成功: {file_id}")
        return result
    
    async def delete_file(self, file_id: str) -> bool:
        """删除文件
        
        Args:
            file_id: 文件ID
            
        Returns:
            是否删除成功
            
        Raises:
            ValueError: 如果文件不存在或删除失败
        """
        logger.info(f"删除文件 (用户: {self.user_id}, 文件ID: {file_id})")
        
        result = await self._call_tool_safe(
            "delete_file",
            {
                "user_id": self.user_id,
                "file_id": file_id
            }
        )
        
        if "error" in result:
            logger.warning(f"删除文件失败: {result['error']}")
            raise ValueError(result["error"])
            
        success = result.get("success", False)
        logger.info(f"文件删除{'成功' if success else '失败'}: {file_id}")
        return success
    
    async def save_to_local(self, file_id: str, target_path: str) -> bool:
        """将文件保存到本地
        
        Args:
            file_id: 文件ID
            target_path: 目标路径
            
        Returns:
            是否保存成功
            
        Raises:
            ValueError: 如果文件不存在或保存失败
        """
        logger.info(f"保存文件到本地 (用户: {self.user_id}, 文件ID: {file_id}, 路径: {target_path})")
        
        result = await self._call_tool_safe(
            "save_to_local",
            {
                "user_id": self.user_id,
                "file_id": file_id,
                "target_path": target_path
            }
        )
        
        if "error" in result:
            logger.warning(f"保存文件失败: {result['error']}")
            raise ValueError(result["error"])
            
        success = result.get("success", False)
        logger.info(f"文件保存{'成功' if success else '失败'}: {file_id} -> {target_path}")
        return success
    
    async def close(self):
        """关闭客户端连接"""
        if self._session and self._exit_stack:
            logger.info("关闭MCP客户端连接")
            try:
                await self._exit_stack.aclose()
                logger.debug("MCP客户端连接已关闭")
            except Exception as e:
                logger.error(f"关闭连接时出错: {str(e)}")
            finally:
                self._session = None
                self._exit_stack = None


# 同步包装器，便于非异步代码调用
class SyncUploadMcpClient:
    """同步MCP客户端"""
    
    def __init__(
        self,
        user_id: str = "default",
        process_command: Optional[str] = None,
        process_args: Optional[List[str]] = None,
        host: str = "localhost",
        port: int = 8000,
        use_stdio: bool = True
    ):
        """初始化同步MCP客户端
        
        Args:
            user_id: 用户ID
            process_command: 子进程命令（用于stdio传输）
            process_args: 子进程参数（用于stdio传输）
            host: 服务器主机地址（用于SSE传输）
            port: 服务器端口（用于SSE传输）
            use_stdio: 是否使用stdio传输
        """
        self._client = UploadMcpClient(
            user_id=user_id,
            process_command=process_command,
            process_args=process_args,
            host=host,
            port=port,
            use_stdio=use_stdio
        )
        self._loop = asyncio.get_event_loop()
    
    def _run_async(self, coro):
        """运行异步方法并返回结果"""
        return self._loop.run_until_complete(coro)
    
    def list_files(self, include_deleted: bool = False) -> List[Dict[str, Any]]:
        """列出文件（同步版本）"""
        return self._run_async(self._client.list_files(include_deleted))
    
    def get_file_info(self, file_id: str) -> Dict[str, Any]:
        """获取文件信息（同步版本）"""
        return self._run_async(self._client.get_file_info(file_id))
    
    def upload_file_content(self, filename: str, content: bytes, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """直接上传文件内容（同步版本）"""
        return self._run_async(self._client.upload_file_content(filename, content, metadata))
    
    def upload_file(self, file_path: str, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """上传文件（同步版本）"""
        return self._run_async(self._client.upload_file(file_path, metadata))
    
    def update_metadata(self, file_id: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """更新文件元数据（同步版本）"""
        return self._run_async(self._client.update_metadata(file_id, metadata))
    
    def delete_file(self, file_id: str) -> bool:
        """删除文件（同步版本）"""
        return self._run_async(self._client.delete_file(file_id))
    
    def save_to_local(self, file_id: str, target_path: str) -> bool:
        """将文件保存到本地（同步版本）"""
        return self._run_async(self._client.save_to_local(file_id, target_path))
    
    def close(self):
        """关闭客户端"""
        self._run_async(self._client.close())
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close() 