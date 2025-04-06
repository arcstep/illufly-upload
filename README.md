# Illufly Upload 文件上传服务

一个简单、高效的文件上传和存储服务模块，支持多种使用方式。

## 特性

- 文件上传、下载、查询和删除功能
- 支持元数据管理和更新
- 多种集成方式：直接作为Python模块使用，集成到FastAPI应用，或独立运行
- 基于用户的文件隔离存储
- 文件大小和存储空间限制
- 支持文件类型校验

## 安装

```bash
pip install illufly-upload
```

## 使用方法

### 作为独立服务运行

```bash
# 默认配置启动
python -m illufly_upload

# 指定参数启动
python -m illufly_upload --host 0.0.0.0 --port 5000 --storage ./my_files
```

启动后可以通过 `http://localhost:8000/docs` 访问Swagger文档。

### 在Python代码中使用 (同步方式)

```python
from illufly_upload import SyncUploadClient

# 创建客户端
client = SyncUploadClient(base_dir="./storage", user_id="user123")

# 上传文件
file_info = client.upload_file("./example.pdf", {"title": "示例文档"})
print(f"文件ID: {file_info['id']}")

# 列出所有文件
files = client.list_files()
for file in files:
    print(f"{file['original_name']} - {file['size']} bytes")

# 下载文件
client.save_to_local(file_info["id"], "./downloaded_example.pdf")

# 更新元数据
client.update_metadata(file_info["id"], {"description": "这是一个示例PDF文件"})

# 删除文件
client.delete_file(file_info["id"])

# 关闭客户端
client.close()
```

### 在异步代码中使用

```python
import asyncio
from illufly_upload import UploadClient

async def main():
    # 创建客户端
    client = UploadClient(base_dir="./storage", user_id="user123")
    
    # 上传文件
    file_info = await client.upload_file("./example.pdf", {"title": "示例文档"})
    
    # 列出所有文件
    files = await client.list_files()
    for file in files:
        print(f"{file['original_name']} - {file['size']} bytes")
    
    # 关闭客户端
    await client.close()

asyncio.run(main())
```

### 集成到FastAPI应用

```python
from fastapi import FastAPI, Depends
from illufly_upload import setup_upload_service

app = FastAPI()

# 用户认证函数
async def get_current_user():
    # 实际应用中应该实现真正的认证逻辑
    return {"user_id": "user123"}

# 设置上传服务
upload_service = setup_upload_service(
    app=app,
    require_user=get_current_user,
    base_dir="./storage",
    max_file_size=20 * 1024 * 1024,  # 20MB
    prefix="/api"
)

@app.get("/")
async def root():
    return {"message": "服务已启动"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
```

## API端点

当集成到FastAPI或作为独立服务运行时，提供以下API端点：

- `GET /api/uploads` - 列出用户所有文件
- `POST /api/uploads` - 上传新文件
- `GET /api/uploads/{file_id}` - 获取文件信息
- `PATCH /api/uploads/{file_id}` - 更新文件元数据
- `DELETE /api/uploads/{file_id}` - 删除文件
- `GET /api/uploads/{file_id}/download` - 下载文件

## 配置选项

- `base_dir` - 文件存储根目录
- `max_file_size` - 单个文件最大大小 (默认 10MB)
- `max_total_size_per_user` - 每个用户最大存储空间 (默认 100MB)
- `allowed_extensions` - 允许的文件扩展名列表
- `prefix` - API前缀 (默认 "/api")

## 目录结构

文件存储在以下结构中：
```
base_dir/
  ├── files/           # 存储用户文件
  │   └── {user_id}/   # 按用户隔离
  └── meta/            # 存储元数据
      └── {user_id}/   # 按用户隔离
```

## 协议

MIT
