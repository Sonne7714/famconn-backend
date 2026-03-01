from pydantic import BaseModel
from typing import Literal

class FamilyCreate(BaseModel):
    name: str

class JoinFamily(BaseModel):
    invite_code: str

class FamilyOut(BaseModel):
    id: str
    name: str
    role: Literal["owner", "member"]

class InviteCreate(BaseModel):
    family_id: str

class InviteOut(BaseModel):
    code: str
    expires_at: str
