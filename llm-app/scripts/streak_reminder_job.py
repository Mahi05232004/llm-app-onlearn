import os
import asyncio
import logging
from datetime import datetime, timedelta, UTC
from bson import ObjectId
from core.mongo_db import mongo_db_manager
from services.mail_service import mail_service

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("streak_reminder_job")

async def run_streak_reminders():
    """
    Background job to send streak reminders to inactive students.
    """
    db = mongo_db_manager.get_database()
    users_col = db["users"]
    sessions_col = db["chatsessions"]  # Mongoose pluralizes ChatSession to chatsessions

    now = datetime.now(UTC)
    
    # 1. Fetch all verified users
    users = users_col.find({"isVerified": True})
    
    count_sent = 0
    
    for user in users:
        user_id = user["_id"]
        username = user.get("username", user.get("name", "Student"))
        email = user.get("email")
        
        if not email:
            continue

        # 2. Get the most recent chat session for this user
        last_session = sessions_col.find_one(
            {"userId": user_id},
            sort=[("updatedAt", -1)]
        )
        
        if not last_session:
            # Maybe they never started a session, or it's a new user
            # We can use createdAt from user as a fallback for "last active"
            last_active = user.get("updatedAt", user.get("createdAt"))
        else:
            last_active = last_session.get("updatedAt", last_session.get("createdAt"))

        if not last_active:
            continue

        # Ensure last_active is timezone-aware
        if last_active.tzinfo is None:
            last_active = last_active.replace(tzinfo=UTC)

        diff = now - last_active
        diff_hours = diff.total_seconds() / 3600
        
        # Determine last active module for personalization
        active_module = user.get("activeModule", "dsa")
        
        # Get current mailing state
        mailing_state = user.get("mailing_state", {
            "last_reminder_day": 0,
            "last_reminder_sent_at": None,
            "last_activity_seen_at": last_active
        })
        
        # Reset mailing state if new activity is detected
        if mailing_state.get("last_activity_seen_at") and last_active > mailing_state["last_activity_seen_at"]:
            logger.info(f"User {username} showed new activity. Resetting mailing state.")
            mailing_state = {
                "last_reminder_day": 0,
                "last_reminder_sent_at": None,
                "last_activity_seen_at": last_active
            }
            users_col.update_one({"_id": user_id}, {"$set": {"mailing_state": mailing_state}})

        # Reminder Logic
        # Day 1: 24h-48h
        # Day 2: 48h-72h
        # ...
        # Day 6: 144h+
        
        target_day = 0
        if 24 <= diff_hours < 48:
            target_day = 1
        elif 48 <= diff_hours < 72:
            target_day = 2
        elif 72 <= diff_hours < 96:
            target_day = 3
        elif 96 <= diff_hours < 120:
            target_day = 4
        elif 120 <= diff_hours < 144:
            target_day = 5
        elif diff_hours >= 144:
            target_day = 6

        if target_day > 0 and target_day > mailing_state["last_reminder_day"]:
            # Check if we should send the next reminder
            # We only send ONE reminder per 24h period of inactivity
            
            last_sent_at = mailing_state.get("last_reminder_sent_at")
            if last_sent_at:
                if last_sent_at.tzinfo is None:
                    last_sent_at = last_sent_at.replace(tzinfo=UTC)
                
                # Ensure at least 20 hours have passed since last reminder to avoid double-mailing on edge cases
                if (now - last_sent_at).total_seconds() < 20 * 3600:
                    continue

            # Send Email
            subject, html_content = mail_service.get_streak_reminder_template(
                day=target_day,
                username=username,
                module=active_module
            )
            
            success = await mail_service.send_email(
                to_email=email,
                to_name=username,
                subject=subject,
                html_content=html_content
            )
            
            if success:
                count_sent += 1
                # Update mailing state
                mailing_state["last_reminder_day"] = target_day
                mailing_state["last_reminder_sent_at"] = now
                mailing_state["last_activity_seen_at"] = last_active
                
                users_col.update_one(
                    {"_id": user_id},
                    {"$set": {"mailing_state": mailing_state}}
                )
                logger.info(f"Sent reminder Day {target_day} to {username} ({email})")

    logger.info(f"Finished streak reminder job. Sent {count_sent} emails.")

if __name__ == "__main__":
    # Load environment variables if not already loaded
    from dotenv import load_dotenv
    load_dotenv()
    
    asyncio.run(run_streak_reminders())
