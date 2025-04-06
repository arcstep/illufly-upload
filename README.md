# Illufly Upload

文件上传、存储和管理服务。支持多种集成方式，包括：
- 作为独立的MCP服务运行
- 集成到FastAPI应用中
- 使用Python客户端访问

## 功能特性

- 文件上传和存储
- 文件元数据管理
- 文件状态管理（活跃、删除）
- 多用户隔离
- 存储空间限制
- 文件类型过滤
- 多种集成方式

## 安装

```bash
pip install illufly-upload
```

## 使用方法

### 1. 作为独立MCP服务

```bash
# 使用stdio方式启动（推荐）
python -m illufly_upload --transport stdio

# 使用SSE方式启动（HTTP服务器）
python -m illufly_upload --transport sse --port 8000
```

### 2. 集成到FastAPI应用中（推荐方式）

在你的FastAPI应用中，通过子进程与MCP服务通信。这是推荐的集成方式，它提供了良好的进程隔离。

```python
import sys
from fastapi import FastAPI, Depends
from illufly_upload import mount_upload_service_stdio

app = FastAPI()

# 定义用户认证函数（你可以使用任何你想要的认证机制）
async def get_current_user():
    # 这里应该实现你的JWT认证逻辑
    return {"user_id": "your_user_id"}

# 通过子进程和stdio方式挂载MCP服务
process_command = sys.executable  # 当前Python解释器路径
process_args = ["-m", "illufly_upload", "--transport", "stdio"]

# 挂载服务到FastAPI应用
upload_client = mount_upload_service_stdio(
    app=app,
    require_user=get_current_user,
    process_command=process_command,
    process_args=process_args,
    prefix="/api"
)

# 你的应用其他路由...
@app.get("/")
async def root():
    return {"message": "Hello World"}
```

### 3. 使用Python客户端访问

```python
import asyncio
from illufly_upload import UploadClient, SyncUploadClient

# 异步客户端
async def main():
    # 连接到MCP服务
    client = UploadClient(
        user_id="your_user_id",
        process_command="python",
        process_args=["-m", "illufly_upload", "--transport", "stdio"],
        use_stdio=True
    )
    
    # 上传文件
    file_info = await client.upload_file("path/to/your/file.txt", {"description": "A test file"})
    print(f"上传成功: {file_info['id']}")
    
    # 列出所有文件
    files = await client.list_files()
    for file in files:
        print(f"文件: {file['original_name']}, ID: {file['id']}")
    
    # 关闭客户端
    await client.close()

asyncio.run(main())

# 或使用同步客户端
def sync_example():
    with SyncUploadClient(
        user_id="your_user_id",
        process_command="python",
        process_args=["-m", "illufly_upload", "--transport", "stdio"],
        use_stdio=True
    ) as client:
        # 上传文件
        file_info = client.upload_file("path/to/your/file.txt", {"description": "A test file"})
        print(f"上传成功: {file_info['id']}")
        
        # 列出所有文件
        files = client.list_files()
        for file in files:
            print(f"文件: {file['original_name']}, ID: {file['id']}")

sync_example()
```

## API参考

### REST API端点

以下是FastAPI集成时可用的端点：

- `GET /api/uploads` - 列出所有文件
- `POST /api/uploads` - 上传新文件
- `GET /api/uploads/{file_id}` - 获取文件信息
- `PATCH /api/uploads/{file_id}` - 更新文件元数据
- `DELETE /api/uploads/{file_id}` - 删除文件
- `GET /api/uploads/{file_id}/download` - 下载文件

### MCP工具

MCP服务提供以下工具：

- `list_files` - 列出用户文件
- `get_file_info` - 获取文件信息
- `upload_file` - 上传文件
- `update_metadata` - 更新文件元数据
- `delete_file` - 删除文件
- `save_to_local` - 保存文件到本地路径

## 参数配置

启动时支持以下参数：

- `--base-dir` - 文件存储根目录，默认为"./storage"
- `--max-file-size` - 单个文件最大大小（字节），默认为10MB
- `--max-total-size` - 每个用户最大存储空间（字节），默认为100MB
- `--extensions` - 允许的文件扩展名，以逗号分隔
- `--port` - HTTP服务监听端口（仅SSE或FastAPI模式有效），默认为8000
- `--transport` - 传输类型：stdio、sse或fastapi

## 开发说明

该项目基于MCP（Message Communication Protocol）和FastMCP实现，与主应用保持进程隔离，同时提供了方便的集成接口。

文件存储采用基于文件系统的存储结构，并通过元数据管理文件信息和状态。文件按用户隔离存储，每个用户有独立的存储空间限制。

## 关于MCP

Model Context Protocol (MCP) 是一个用于AI模型与应用程序交互的标准协议。通过MCP，AI模型可以使用工具、访问资源，以及与其他系统交互。本服务提供符合MCP规范的文件操作工具，可与支持MCP的AI应用无缝集成。

## 协议

MIT
