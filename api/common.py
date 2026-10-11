from functools import wraps

from pydantic import BaseModel, Field
from typing import Any, Optional, Dict

# ===================== 统一返回结构 =====================
def resp(code: int, msg: str, data: Optional[Any] = None, extra: Optional[Dict] = None) -> Dict:
    """全局标准返回体"""
    return {
        "code": code,
        "msg": msg,
        "data": data if data is not None else {},
        "extra": extra if extra is not None else {}
    }

# 业务状态码规范
CODE_OK = 200
CODE_PARAM_ERR = 400
CODE_SERVER_ERR = 500

# ===================== 请求参数模型 =====================
class ChatRequest(BaseModel):
    user_input: str = Field(..., description="用户提问文本")
    situation: Optional[str] = Field(None, description="可选的真实问题情境，用于产出可执行建议")
    role: str = Field("advisor", description="[兼容保留] advisor=建议者/总结者, guide=自我推理引导者；被 mode 取代")
    mode: Optional[str] = Field(None, description="direct=直接咨询, guided=引导咨询；会话首条消息锁定，之后忽略")

# ===================== 通用序列化工具 =====================
from dataclasses import asdict

def safe_serialize(obj):
    """dataclass / 集合 安全转字典，过滤内部冗余字段"""
    if isinstance(obj, set):
        return list(obj)
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj)
    return obj

# ===================== 通用异常包装 =====================
def catch_exception(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            return resp(
                CODE_SERVER_ERR,
                f"服务内部异常: {str(e)}",
                extra={"error_detail": str(e)}
            )
    return wrapper