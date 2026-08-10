from pydantic import BaseModel, Field


class UsernameSignInRequest(BaseModel):
    identity: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class UsernameSignInResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str
