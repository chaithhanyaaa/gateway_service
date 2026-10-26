from pydantic_settings import BaseSettings
class Settings(BaseSettings):

    #DATABASE_URL: str

    PORT:int
    HOST:str
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
        
    OPERATION_TTL_SECONDS :int
    RUNNING_TTL_SECONDS :int   


    grokAPIKey:str
    JWT_SECRET: str
    JWT_ISSUER: str
    JWT_AUDIENCE: str
    JWT_ALGORITHM: str
    GROQ_FAILURE_THRESHOLD:int
    GROQ_RECOVERY_TIMEOUT:float

    #ACCESS_TOKEN_EXPIRE_MINUTES: int

    class Config:
        env_file = ".env"


settings = Settings()