from pydantic_settings import BaseSettings
class Settings(BaseSettings):

    #DATABASE_URL: str

    #REDIS_PORT:int

    #REDIS_HOST:str


    grokAPIKey:str

    #JWT_SECRET: str

    #JWT_ALGORITHM: str

    #ACCESS_TOKEN_EXPIRE_MINUTES: int

    class Config:
        env_file = ".env"


settings = Settings()