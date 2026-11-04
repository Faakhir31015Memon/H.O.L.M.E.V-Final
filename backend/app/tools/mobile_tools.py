"""Mobile tools: the bridge's own answer is the tool's answer.

These tools used to return `success=True, verified=True` no matter what, because the
bridge underneath only printed a status string. Now each one reports the bridge's
result, including the refusals, and leaves `verified` for the verification engine.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.communication.mobile_bridge import mobile_bridge_service
from app.tools.base import BaseTool, ToolResult


class WhatsAppMessageInput(BaseModel):
    recipient: str = Field(description="Name or phone number of recipient")
    message: str = Field(description="Message body text")


class WhatsAppMessageTool(BaseTool):
    name = "mobile.whatsapp.send"
    description = "Hands a WhatsApp message to the paired phone bridge for sending."
    category = "mobile"
    permission_level = 3
    input_schema = WhatsAppMessageInput

    async def _run(self, recipient: str = "", message: str = "", **kwargs: Any) -> ToolResult:
        res = await mobile_bridge_service.send_whatsapp_message(recipient, message)
        return ToolResult(
            success=bool(res.get("sent")),
            verified=False,
            data=res,
            error=None if res.get("sent") else res.get("reason"),
        )


class PhoneCallInput(BaseModel):
    contact: str = Field(description="Contact name or phone number")


class PhoneCallTool(BaseTool):
    name = "mobile.phone.call"
    description = "Asks the paired phone bridge to dial a contact."
    category = "mobile"
    permission_level = 3
    input_schema = PhoneCallInput

    async def _run(self, contact: str = "", **kwargs: Any) -> ToolResult:
        res = await mobile_bridge_service.make_phone_call(contact)
        return ToolResult(
            success=bool(res.get("called")),
            verified=False,
            data=res,
            error=None if res.get("called") else res.get("reason"),
        )


class SendEmailInput(BaseModel):
    recipient_email: str = Field(description="Destination email address")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Email body text")


class SendEmailTool(BaseTool):
    name = "mobile.email.send"
    description = "Sends an email through the SMTP server configured in .env."
    category = "mobile"
    permission_level = 3
    input_schema = SendEmailInput

    async def _run(self, recipient_email: str = "", subject: str = "", body: str = "", **kwargs: Any) -> ToolResult:
        res = await mobile_bridge_service.send_email(recipient_email, subject, body)
        return ToolResult(
            success=bool(res.get("sent")),
            verified=False,
            data=res,
            error=None if res.get("sent") else res.get("reason"),
        )


class MobileDisplayImageInput(BaseModel):
    query: str = Field(default="latest", description="Search tag or image name from the paired phone's gallery")


class MobileDisplayImageTool(BaseTool):
    name = "mobile.image.display"
    description = "Fetches a photo from the paired phone's gallery through the bridge."
    category = "mobile"
    permission_level = 2
    input_schema = MobileDisplayImageInput

    async def _run(self, query: str = "latest", **kwargs: Any) -> ToolResult:
        res = await mobile_bridge_service.fetch_mobile_gallery_image(query)
        return ToolResult(
            success=bool(res.get("retrieved")),
            verified=False,
            data=res,
            error=None if res.get("retrieved") else res.get("reason"),
        )
