from typing import Optional, Any
from pydantic import BaseModel, Field
from app.tools.base import BaseTool, ToolResult
from app.communication.mobile_bridge import mobile_bridge_service

class WhatsAppMessageInput(BaseModel):
    recipient: str = Field(description="Name or phone number of recipient")
    message: str = Field(description="Message body text")

class WhatsAppMessageTool(BaseTool):
    name = "mobile.whatsapp.send"
    description = "Sends a WhatsApp message via connected mobile phone."
    category = "mobile"
    permission_level = 2
    input_schema = WhatsAppMessageInput

    async def _run(self, recipient: str = "", message: str = "", **kwargs: Any) -> ToolResult:
        res = mobile_bridge_service.send_whatsapp_message(recipient, message)
        return ToolResult(
            success=True,
            verified=True,
            data=res,
            error=None
        )

class PhoneCallInput(BaseModel):
    contact: str = Field(description="Contact name or phone number")

class PhoneCallTool(BaseTool):
    name = "mobile.phone.call"
    description = "Initiates a phone call to a contact via connected mobile phone."
    category = "mobile"
    permission_level = 3
    input_schema = PhoneCallInput

    async def _run(self, contact: str = "", **kwargs: Any) -> ToolResult:
        res = mobile_bridge_service.make_phone_call(contact)
        return ToolResult(
            success=True,
            verified=True,
            data=res,
            error=None
        )

class SendEmailInput(BaseModel):
    recipient_email: str = Field(description="Destination email address")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Email body text")

class SendEmailTool(BaseTool):
    name = "mobile.email.send"
    description = "Sends an email from linked mobile account."
    category = "mobile"
    permission_level = 2
    input_schema = SendEmailInput

    async def _run(self, recipient_email: str = "", subject: str = "", body: str = "", **kwargs: Any) -> ToolResult:
        res = mobile_bridge_service.send_email(recipient_email, subject, body)
        return ToolResult(
            success=True,
            verified=True,
            data=res,
            error=None
        )

class MobileDisplayImageInput(BaseModel):
    query: str = Field(default="latest", description="Search tag or image name from mobile photo gallery")

class MobileDisplayImageTool(BaseTool):
    name = "mobile.image.display"
    description = "Displays images or photos from linked mobile device on screen."
    category = "mobile"
    permission_level = 1
    input_schema = MobileDisplayImageInput

    async def _run(self, query: str = "latest", **kwargs: Any) -> ToolResult:
        res = mobile_bridge_service.fetch_mobile_gallery_image(query)
        return ToolResult(
            success=True,
            verified=True,
            data=res,
            error=None
        )
