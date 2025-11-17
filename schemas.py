"""
Database Schemas for the Unity Game Portal

Each Pydantic model represents a collection in MongoDB.
Collection name is the lowercase of the class name.
"""
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field, EmailStr

class User(BaseModel):
    name: str = Field(..., description="Display name")
    email: EmailStr = Field(..., description="Unique email address")
    password_hash: str = Field(..., description="Hashed password")
    avatar_url: Optional[str] = Field(None, description="Optional avatar URL")

class Game(BaseModel):
    title: str = Field(..., description="Game title")
    slug: str = Field(..., description="URL-friendly unique identifier")
    description: Optional[str] = Field(None, description="Short description")
    cover_image: Optional[str] = Field(None, description="Cover image URL")
    web_path: Optional[str] = Field(None, description="Path to WebGL index.html served by frontend")
    download_path: Optional[str] = Field(None, description="Path to downloadable archive (served by frontend)")

class Save(BaseModel):
    user_id: str = Field(..., description="User id as string")
    game_slug: str = Field(..., description="Slug of the game")
    data: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary save data JSON")
