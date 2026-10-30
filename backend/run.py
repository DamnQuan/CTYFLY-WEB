"""启动脚本：python run.py"""
import uvicorn

from app.config import PORT, PROXY_HEADERS, env

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        # 默认只监听本机回环，127.0.0.1，由同机 Nginx 反代对外；
        # 需要直连监听时用 HOST 环境变量覆盖，如 HOST=0.0.0.0，生产不要开放。
        host=env("HOST", "127.0.0.1"),
        port=PORT,
        server_header=False,   # 不暴露 Server: uvicorn 指纹
        date_header=True,
        # 反向代理部署，Nginx 时在 .env 设 PROXY_HEADERS=true：
        # uvicorn 会依据 X-Forwarded-For 重写 request.client，仅信任
        # forwarded_allow_ips 来源，默认即本机，使限流/日志/人机验证
        # 豁免拿到真实客户端 IP。直连部署保持 false，防止伪造 XFF。
        proxy_headers=PROXY_HEADERS,
    )
