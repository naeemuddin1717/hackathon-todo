from pydantic import BaseModel, EmailStr, Field

class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)

class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
