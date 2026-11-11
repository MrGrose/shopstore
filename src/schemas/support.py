from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from src.utils.pagination import catalog_total_pages


class SupportAttachmentSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content_type: str
    byte_size: int


class SupportMessageSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    author_type: str
    author_user_id: int | None
    body: str
    created_at: datetime
    attachments: list[SupportAttachmentSchema] = Field(default_factory=list)


class SupportMessageAdminSchema(SupportMessageSchema):
    telegram_delivered: bool | None = None


class SupportTicketListItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic: str
    topic_label: str
    status: str
    order_id: int | None
    created_at: datetime
    updated_at: datetime
    last_message_preview: str | None = None


class SupportTicketListPageSchema(BaseModel):
    items: list[SupportTicketListItemSchema]
    total: int = Field(..., ge=0)
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)

    @computed_field
    def total_pages(self) -> int:
        return catalog_total_pages(self.total, self.page_size)


class SupportTicketDetailSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    topic: str
    topic_label: str
    status: str
    order_id: int | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    messages: list[SupportMessageSchema]


class SupportTicketDetailAdminSchema(SupportTicketDetailSchema):
    messages: list[SupportMessageAdminSchema]


class SupportTicketCreateSchema(BaseModel):
    topic: str = Field(min_length=1, max_length=32)
    body: str = Field(default="", max_length=4000)
    order_id: int | None = None


class SupportMessageCreateSchema(BaseModel):
    body: str = Field(default="", max_length=4000)


class SupportLinkableOrderSchema(BaseModel):
    id: int
    status: str
    total_amount: str
    created_at: datetime
