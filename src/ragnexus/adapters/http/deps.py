"""HTTP 层依赖注入——重新导出鉴权核心的工厂函数。"""

from ragnexus.core.auth import make_get_current_tenant

__all__ = ["make_get_current_tenant"]
