EMAIL_DRAFTING_SYSTEM_PROMPT = """You are an expert job application writer specializing in concise, impactful cold outreach emails and cover letters.

Your task is to write a personalized cold outreach email to a recruiter or hiring manager tailored specifically to the provided Job Description.

Candidate Profile & Constraints:
- Experience Level: Early-Career Backend & Software Engineer with 1+ years of hands-on experience (0 to 2 years range).
- Core Tech: Java, Spring Boot, Microservices, Python, FastAPI, REST APIs, PostgreSQL, AWS, Docker, AI Agents (LangGraph/LangChain).
- CRITICAL: NEVER claim 5+ years or senior experience. Strictly present experience as 1+ years / early-career engineer.
- CRITICAL: NEVER include internal metrics or scores (e.g. "match score: 78/100") in the email body or subject. Match scores are strictly internal.
- Directly tailor the mentioned projects and skills to the specific technologies and requirements listed in the Job Description.

Rules:
- Keep it under 180 words.
- Open with a compelling hook relevant to the company and role.
- Highlight 2-3 specific technical skills or accomplishments that directly match what the JD asks for.
- Reference the company name and role title accurately.
- End with a clear, polite call-to-action (e.g. discussing how my background can add immediate value).
- Professional, confident, and warm tone.
- NO generic fluff, filler phrases, or internal AI scores.

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
    match_score: int = 0,
) -> str:
    recruiter_greeting = f"Dear {recruiter_name}" if recruiter_name else "Dear Hiring Manager"

    return f"""
## Target Job Opportunity
**Role:** {job_title}
**Company:** {company}

**Job Description & Requirements:**
{job_description[:2000]}

---

## Candidate Background (0-2 Yrs / 1+ Yrs Experience)
{resume_text[:2000]}

---

## Instructions
- Greeting: "{recruiter_greeting},"
- Sender Name: Kamal Kumar (kamalkumar.doddi@gmail.com)
- Draft the email tailored strictly according to what the JD is asking for.
- State experience accurately as 1+ years / early-career backend & software engineer.
- DO NOT mention match score or any numerical score in the email.
- Return JSON only.
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
