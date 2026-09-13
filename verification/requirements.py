"""Version-controlled requirements shown to applicants and enforced at submission."""
from django.conf import settings
from .models import VerificationType

FILES = ["application/pdf", "image/jpeg", "image/png"]

DEFINITIONS = {
    VerificationType.IDENTITY: {
        "title": "Identity verification", "description": "Verify the person behind this account.",
        "scope": ["Identity evidence is consistent with the applicant"],
        "badge_meaning": "SurePlace verified supporting identity evidence for this person.",
        "badge_disclaimer": "Verification does not guarantee a transaction.", "prerequisites": [],
        "requirements": [{"key": "NATIONAL_ID", "label": "National ID or passport", "description": "A government-issued identity document.", "required": True, "mode": "ONE_OF", "alternatives": ["NATIONAL_ID", "PASSPORT"], "accepted_file_types": FILES}],
    },
    VerificationType.AGENCY: {
        "title": "Agency verification", "description": "Verify an agency and its authorised representative.",
        "scope": ["The agency exists", "The applicant is authorised to represent it", "Submitted details match evidence"],
        "badge_meaning": "SurePlace reviewed supporting evidence for this agency and its authorised representative.",
        "badge_disclaimer": "This does not mean every listing from the agency has been independently verified.",
        "prerequisites": [{"type": "IDENTITY", "required": True}],
        "requirements": [{"key": "COMPANY_REGISTRATION", "label": "Business registration", "description": "Official registration or incorporation document.", "required": True, "accepted_file_types": FILES}, {"key": "PROOF_OF_ADDRESS", "label": "Proof of business address", "description": "A recent business address document.", "required": True, "accepted_file_types": FILES}],
    },
    VerificationType.PROPERTY: {
        "title": "Property verification", "description": "Verify authority to advertise one specific property.",
        "scope": ["Supporting evidence connects the advertiser to this property"],
        "badge_meaning": "SurePlace reviewed supporting evidence connecting this advertiser to this property.",
        "badge_disclaimer": "SurePlace does not guarantee this property or a transaction.",
        "prerequisites": [{"type": "IDENTITY", "required": False}, {"type": "AGENCY", "required": False}],
        "requirements": [{"key": "authority_to_list", "label": "Authority to list", "description": "Upload ownership evidence or landlord authorisation.", "required": True, "mode": "ONE_OF", "alternatives": ["TITLE_DEED", "OWNER_AUTHORIZATION"], "accepted_file_types": FILES}],
    },
    VerificationType.AGENT: {"title":"Agent verification","description":"Verify identity and supporting professional association.","scope":["Identity and professional association evidence are reviewed"],"badge_meaning":"SurePlace verified this agent's identity and supporting professional association.","badge_disclaimer":"This does not represent a licensing claim.","prerequisites":[{"type":"IDENTITY","required":True}],"requirements":[{"key":"AGENT_IDENTIFICATION","label":"Professional identification","description":"Professional or agency supporting document.","required":True,"accepted_file_types":FILES},{"key":"professional_association","label":"Professional association","description":"A professional reference or employment confirmation.","required":True,"mode":"ONE_OF","alternatives":["PROFESSIONAL_REFERENCE","EMPLOYMENT_CONFIRMATION"],"accepted_file_types":FILES}]},
    VerificationType.STAY: {"title":"Stay verification","description":"Verify an accommodation and its operator.","scope":["Operator authority and accommodation details are reviewed"],"badge_meaning":"SurePlace reviewed supporting evidence for this accommodation and its operator.","badge_disclaimer":"Verification does not guarantee a booking.","prerequisites":[{"type":"IDENTITY","required":True}],"requirements":[{"key":"operator_authority","label":"Operator authority","description":"Business registration or tourism licence.","required":True,"mode":"ONE_OF","alternatives":["BUSINESS_REGISTRATION","TOURISM_LICENCE"],"accepted_file_types":FILES},{"key":"PROOF_OF_ADDRESS","label":"Proof of address","description":"Accommodation location evidence.","required":True,"accepted_file_types":FILES}]},
    VerificationType.BUSINESS: {"title":"Business verification","description":"Verify a business represented by this user.","scope":["Business existence and representative evidence are reviewed"],"badge_meaning":"SurePlace reviewed supporting evidence that this business exists and is represented by this user.","badge_disclaimer":"Verification does not guarantee a transaction.","prerequisites":[{"type":"IDENTITY","required":True}],"requirements":[{"key":"BUSINESS_REGISTRATION","label":"Business registration","description":"Official business registration document.","required":True,"accepted_file_types":FILES}]},
}

def definitions():
    return [
        {
            "type": code,
            "label": title,
            "disclaimer": DEFINITIONS[code]["badge_disclaimer"],
            "max_file_size_mb": settings.VERIFICATION_MAX_FILE_MB,
            **DEFINITIONS[code],
        }
        for code, title in VerificationType.choices
    ]
