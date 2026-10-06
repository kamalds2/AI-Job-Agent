import asyncio
import os
import sys
sys.path.insert(0, os.path.abspath("."))
from app.services.linkedin_browser_agent import LinkedInBrowserAgent
from app.services.indeed_browser_agent import IndeedBrowserAgent
from app.services.form_self_healer import FormSelfHealer
from app.utils.gemini_client import get_gemini_client

async def test_answers():
    l_agent = LinkedInBrowserAgent()
    i_agent = IndeedBrowserAgent()

    test_cases = [
        ("What is your notice period in days?", "number", None, "0"),
        ("What is your notice period (in days)?", "text", None, "0"),
        ("Notice period in days", "text", None, "0"),
        ("What is your current CTC in lakhs?", "text", None, "1.4"),
        ("What is your current CTC (in LPA)?", "text", None, "1.4"),
        ("What is your current CTC?", "number", None, "140000"),
        ("What is your expected CTC in lakhs?", "text", None, "5"),
        ("What is your expected CTC (in LPA)?", "text", None, "5"),
        ("What is your expected CTC?", "number", None, "500000"),
        ("Select your Notice Period", "select", ["Immediate", "15 Days", "30 Days", "60 Days"], "Immediate"),
        ("Select your Current CTC", "select", ["0-2 Lakhs", "2-4 Lakhs", "4-6 Lakhs"], "0-2 Lakhs"),
        ("Select your Expected CTC", "select", ["0-2 Lakhs", "2-4 Lakhs", "4-6 Lakhs", "6-8 Lakhs"], "4-6 Lakhs"),
        ("Are you willing to work from Bengaluru (hybrid)?", "radio", ["Yes", "No"], "Yes"),
    ]

    print("=== Testing LinkedIn Form Answers ===")
    for q, ft, opts, exp in test_cases:
        ans = await l_agent.answer_form_field(q, ft, opts)
        status = "✅ PASS" if (ans == exp or exp.lower() in ans.lower()) else f"❌ FAIL (got {ans}, exp {exp})"
        print(f'{status} | "{q}" -> "{ans}"')

    print("\n=== Testing Indeed Form Answers ===")
    for q, ft, opts, exp in test_cases:
        ans = await i_agent.answer_form_field(q, ft, opts)
        status = "✅ PASS" if (ans == exp or exp.lower() in ans.lower()) else f"❌ FAIL (got {ans}, exp {exp})"
        print(f'{status} | "{q}" -> "{ans}"')

if __name__ == "__main__":
    asyncio.run(test_answers())
