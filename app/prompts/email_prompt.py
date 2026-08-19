EMAIL_DRAFTING_SYSTEM_PROMPT = """You are an expert job application writer specializing in concise, impactful cold outreach emails.

Your task is to write a professional cold email to a recruiter or hiring manager for a specific job opportunity.

Rules:
- Keep it under 200 words
- Open with a hook, not "My name is..."
- Mention 2-3 specific relevant skills/achievements
- Reference the company/role specifically  
- End with a clear call-to-action
- Professional but warm tone
- NO fluff or filler phrases

Return ONLY a valid JSON object:
{
  "subject": "<compelling email subject line>",
  "body": "<complete email body — plain text, no HTML>",
  "follow_up_day": <integer days after sending to follow up>
}
"""


def build_email_user_prompt(
    job_title: str,
    company: str,
    job_description: str,
    recruiter_name: str | None,
    resume_text: str,
    match_score: int,
) -> str:
    recruiter_greeting = f"Hi {recruiter_name}" if recruiter_name else "Hi there"

    return f"""
## Job Details

**Role:** {job_title}
**Company:** {company}
**My Match Score:** {match_score}/100

**Job Description (excerpt):**
{job_description[:1500]}

---

## My Background (from resume)

{resume_text[:2000]}

---

## Instructions

- Greeting: "{recruiter_greeting},"
- Sender name: Kamal Kumar
- Write a cold outreach email for this job opportunity
- Be specific about why I'm a great fit for THIS role at THIS company
- Return JSON only
"""


WHATSAPP_NOTIFICATION_TEMPLATE = """🤖 *AI Job Agent — Match Alert*

📋 *Role:* {title}
🏢 *Company:* {company}
⭐ *Match Score:* {score}/100
🔗 *Apply:* {url}

💡 *Why it matches:*
{reasoning}

📧 _Email {email_status}_
📄 _Resume {resume_status}_
"""
