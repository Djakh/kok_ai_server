from pydantic import BaseModel


class AchievementResponse(BaseModel):
    id: str
    code: str
    title: str
    description: str
