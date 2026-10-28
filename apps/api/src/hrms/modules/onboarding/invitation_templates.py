# ruff: noqa: E501 - long literal message copy
"""Built-in onboarding invitation templates HR can pick in the composer.

Each is plain text using only the placeholders in `invitation_compose.PLACEHOLDERS`; choosing one
just pre-fills the editable subject/body, which then go through the same validation, preview and
send path as any hand-written message (nothing here is trusted or rendered specially). The first
entry is the default. Keys are stable identifiers, safe to reference from the client.
"""

from dataclasses import dataclass

from hrms.modules.onboarding.invitation_compose import DEFAULT_BODY, DEFAULT_SUBJECT


@dataclass(frozen=True)
class InvitationTemplate:
    key: str
    name: str
    description: str
    subject: str
    body: str


_SHORT_BODY = """Hi {{candidate_first_name}},

Welcome to {{company_name}}! We are delighted that you are joining us on {{joining_date}}.

To get you set up before your first day, please fill in your details using your personal link below. It is valid until {{invitation_expiry}}, and you can save your progress and come back to it.

{{onboarding_url}}

If you get stuck or have any questions, just reach out to the HR team.

See you soon,
{{company_name}} HR Team"""

_FORMAL_BODY = """Dear {{candidate_name}},

On behalf of {{company_name}}, we are pleased to welcome you and to commence your pre-joining onboarding formalities.

Your proposed date of joining is {{joining_date}}.

You are requested to complete the online onboarding form, and to upload the supporting documents it asks for, using the secure link provided below. The link is issued to you personally and remains valid until {{invitation_expiry}}.

{{onboarding_url}}

Upon submission, your details and documents will be reviewed by the Human Resources department. Should any correction be required, you will be informed of the specific items to be updated. Kindly complete this process well in advance of your date of joining, and do not share the link with any other person.

For any clarification, please contact the Human Resources department.

Yours sincerely,
Human Resources
{{company_name}}"""

_FRESHER_BODY = """Dear {{candidate_name}},

Welcome to {{company_name}}! We are excited to have you start your career with us.

You will be joining the {{department}} team.

Your proposed joining date is {{joining_date}}.

Before your first day, we need a few details from you. Please use the secure link below to fill in your onboarding form. The link is personal to you and is valid until {{invitation_expiry}}.

{{onboarding_url}}

The form is made up of short sections: your personal details, address, emergency contact, bank details, statutory details, education, and nominee and family details. Your progress is saved as you go, so you can take a break and return using the same link.

Please keep these ready to upload as clear photos or scans: a passport-size photograph, your PAN card, your Aadhaar card, address proof, your education certificates, and bank proof such as a cancelled cheque or the first page of your passbook.

If a section or document does not apply to you, for example because you have no previous employment, please follow the instructions on the form or ask the HR team. Never guess or enter incorrect details.

After you submit, our HR team will review everything. If anything needs to be corrected, we will email you exactly what to update. Please do not share your link with anyone.

If you have any questions at all, we are happy to help. Just contact the HR team.

Regards,
{{company_name}} HR Team"""

INVITATION_TEMPLATES: tuple[InvitationTemplate, ...] = (
    InvitationTemplate(
        key="standard",
        name="Standard (detailed)",
        description="Full guide: what the form asks for, documents to keep ready, and the steps.",
        subject=DEFAULT_SUBJECT,
        body=DEFAULT_BODY,
    ),
    InvitationTemplate(
        key="short_friendly",
        name="Short & friendly",
        description="A brief, warm invitation with the link and the deadline.",
        subject="Welcome to {{company_name}} - please complete your details",
        body=_SHORT_BODY,
    ),
    InvitationTemplate(
        key="formal",
        name="Formal",
        description="A formal tone suited to senior or corporate hires.",
        subject="Pre-joining onboarding formalities - {{company_name}}",
        body=_FORMAL_BODY,
    ),
    InvitationTemplate(
        key="fresher",
        name="Fresher / first job",
        description="Extra guidance for candidates joining their first company.",
        subject="Welcome to {{company_name}} - get ready for your first day",
        body=_FRESHER_BODY,
    ),
)
