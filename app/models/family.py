from pydantic import BaseModel, Field


class FamilyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


class InviteCreate(BaseModel):
    family_id: str = Field(..., min_length=1)


class JoinFamily(BaseModel):
    invite_code: str = Field(..., min_length=1, max_length=32)
