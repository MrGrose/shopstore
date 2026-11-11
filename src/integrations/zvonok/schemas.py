from pydantic import BaseModel, ConfigDict, Field


class ZvonokStartData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    call_id: int | str | None = None
    phone: str | None = None
    pincode: str | int | None = None
    balance: float | str | None = None
    created: str | None = None


class ZvonokStartResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    data: ZvonokStartData | str | None = None


class ZvonokCallStatusItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    call_id: int | str | None = None
    call_status: str = Field(default="")


class ZvonokErrorResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    data: str | None = None
