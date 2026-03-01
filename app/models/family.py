from pydantic import BaseModel, Field
from typing import Literal, Optional

Role = Literal["owner", "admin", "member"]

class FamilyCreate(BaseModel):
    name: str

class JoinFamily(BaseModel):
    invite_code: str

class FamilyOut(BaseModel):
    id: str
    name: str
    role: Role

class InviteCreate(BaseModel):
    family_id: str
    # optional override if you later want it; backend currently uses settings.INVITE_TTL_MINUTES
    ttl_minutes: Optional[int] = Field(default=None, ge=1, le=1440)

class InviteOut(BaseModel):
    id: str
    code: str
    expires_at: str

class MemberOut(BaseModel):
    user_id: str
    email: str
    role: Role
    joined_at: Optional[str] = None

class MemberRoleUpdate(BaseModel):
    role: Literal["admin", "member"]

class TransferOwner(BaseModel):
    new_owner_user_id: str
