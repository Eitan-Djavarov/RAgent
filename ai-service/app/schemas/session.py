from app.schemas.base import ApiModel


class CacheClearResponse(ApiModel):
    success: bool
    deleted_keys: int
    message: str


class SessionClearResponse(ApiModel):
    success: bool
    session_id: str
    message: str
