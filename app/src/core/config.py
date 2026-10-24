from pydantic_settings import BaseSettings
class Settings(BaseSettings):

    #DATABASE_URL: str

    PORT:int
    HOST:str

    #REDIS_HOST:str


    grokAPIKey:str

    JWT_SECRET: str
    JWT_ISSUER: str
    JWT_AUDIENCE: str

    JWT_ALGORITHM: str

    #ACCESS_TOKEN_EXPIRE_MINUTES: int

    class Config:
        env_file = ".env"


settings = Settings()