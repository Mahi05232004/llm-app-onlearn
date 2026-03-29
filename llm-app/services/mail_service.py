import os
import httpx
import logging
from typing import Any, Dict, List, Optional
from jinja2 import Template
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class MailService:
    """Service to handle emailing via Brevo (formerly Sendinblue)."""

    def __init__(self):
        self.api_key = os.getenv("BREVO_API_KEY")
        self.sender_email = os.getenv("BREVO_SENDER_EMAIL", "admin@onlearn.app")
        self.sender_name = os.getenv("BREVO_SENDER_NAME", "onLearn admin")
        self.api_url = "https://api.brevo.com/v3/smtp/email"

    async def send_email(
        self, 
        to_email: str, 
        to_name: str, 
        subject: str, 
        html_content: str
    ) -> bool:
        """Send a transactional email via Brevo API."""
        if not self.api_key:
            logger.error("BREVO_API_KEY not found in environment")
            return False

        headers = {
            "accept": "application/json",
            "api-key": self.api_key,
            "content-type": "application/json",
        }

        payload = {
            "sender": {"name": self.sender_name, "email": self.sender_email},
            "to": [{"email": to_email, "name": to_name}],
            "subject": subject,
            "htmlContent": html_content,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(self.api_url, headers=headers, json=payload)
                response.raise_for_status()
                logger.info(f"Email sent successfully to {to_email}")
                return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            return False

    def get_streak_reminder_template(
        self, 
        day: int, 
        username: str, 
        module: str
    ) -> tuple[str, str]:
        """
        Get the subject and HTML content for a streak reminder.
        
        Args:
            day: Reminder day (1 to 6).
            username: Student's name/username.
            module: Last active module ('dsa' or 'ds').
        """
        module_name = "Data Structures & Algorithms" if module == "dsa" else "Data Science"
        
        subjects = {
            1: f"🔥 Don't lose your streak, {username}!",
            2: "⏰ A quick reminder to stay on track",
            3: "🚀 Your goals are waiting for you!",
            4: "📈 Consistency is key to success",
            5: "⚠️ Last chance to save your progress this week!",
            6: "👋 We'll stop bugging you (for now)"
        }
        
        subject = subjects.get(day, "onLearn Update")
        
        # Simple HTML templates
        templates = {
            1: f"""
                <h1>Hi {username}! 👋</h1>
                <p>It's been 24 hours since your last session in <strong>{module_name}</strong>.</p>
                <p>Don't let your streak slip away! Just a few minutes today will keep you on track towards your goals.</p>
                <a href="https://onlearn.app/tutor">Keep Learning</a>
            """,
            2: f"""
                <h1>Hey {username}, we miss you! 😢</h1>
                <p>You were doing so well with <strong>{module_name}</strong>.</p>
                <p>Taking a break is fine, but consistency is what makes a great developer. Come back and solve just one problem today!</p>
                <a href="https://onlearn.app/tutor">Back to Dashboard</a>
            """,
            3: f"""
                <h1>Ready for a challenge? 🚀</h1>
                <p>You've been away for a few days, and your <strong>{module_name}</strong> skills might be getting rusty!</p>
                <p>We've picked some great topics for you to tackle today. Don't let your hard work go to waste.</p>
                <a href="https://onlearn.app/tutor">See My Plan</a>
            """,
            4: f"""
                <h1>Consistency = Results 📈</h1>
                <p>Hi {username}, the most successful students on onLearn are those who show up every day.</p>
                <p>Even if you only have 10 minutes, that's enough to make progress in <strong>{module_name}</strong>.</p>
                <a href="https://onlearn.app/tutor">Start Learning</a>
            """,
            5: f"""
                <h1>⚠️ Almost there, {username}!</h1>
                <p>We noticed you've been inactive for 5 days. We don't want you to lose momentum in <strong>{module_name}</strong>.</p>
                <p>This is our final reminder for this week. We believe in you!</p>
                <a href="https://onlearn.app/tutor">Save My Streak</a>
            """,
            6: f"""
                <h1>Goodbye for now 👋</h1>
                <p>Hi {username}, we haven't seen you in a while, so we'll stop sending these reminders.</p>
                <p>We're still here whenever you're ready to pick up <strong>{module_name}</strong> again. Your progress is saved!</p>
                <a href="https://onlearn.app/">Visit onLearn</a>
            """
        }
        
        content = templates.get(day, templates[1])
        return subject, content

# Singleton instance
mail_service = MailService()
